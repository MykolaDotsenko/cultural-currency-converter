from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.contrib.auth import get_user_model
from django.db import IntegrityError, close_old_connections, transaction
from django.test import TestCase, TransactionTestCase, override_settings, skipUnlessDBFeature
from django.urls import reverse

from apps.countries.models import Country, CountryCurrency, Currency
from apps.travel.models import FavouritePair
from apps.travel.services import sync_user_favourites

User = get_user_model()


def create_reference_data():
    eur = Currency.objects.create(code="EUR", name="Euro")
    jpy = Currency.objects.create(code="JPY", name="Japanese yen", minor_units=0)
    fi = Country.objects.create(iso2="FI", iso3="FIN", name="Finland")
    jp = Country.objects.create(iso2="JP", iso3="JPN", name="Japan")
    CountryCurrency.objects.create(
        country=fi,
        currency=eur,
        is_primary=True,
        source="https://example.test/fi-eur",
    )
    CountryCurrency.objects.create(
        country=jp,
        currency=jpy,
        is_primary=True,
        source="https://example.test/jp-jpy",
    )
    return eur, jpy, fi, jp


def pair_payload():
    return {
        "sourceCurrency": "EUR",
        "destinationCurrency": "JPY",
        "sourceCountry": "FI",
        "destinationCountry": "JP",
    }


@override_settings(VITE_DEV_SERVER_ENABLED=True)
class FavouriteSyncWebTests(TestCase):
    def setUp(self):
        self.eur, self.jpy, self.fi, self.jp = create_reference_data()
        self.user = User.objects.create_user(username="owner", password="StrongPass-482!")
        self.other = User.objects.create_user(username="other", password="StrongPass-482!")

    def post_sync(self, payload, *, client=None):
        target = client or self.client
        return target.post(
            reverse("sync_favourites"),
            data=json.dumps(payload),
            content_type="application/json",
        )

    def test_sync_requires_authentication(self):
        response = self.post_sync({"favourites": [pair_payload()]})

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "authentication_required")
        self.assertEqual(FavouritePair.objects.count(), 0)

    def test_database_rejects_duplicate_pair_identity_for_all_country_shapes(self):
        country_shapes = (
            (None, None),
            (self.fi, None),
            (None, self.jp),
            (self.fi, self.jp),
        )

        for source_country, destination_country in country_shapes:
            with self.subTest(
                source_country=source_country.iso2 if source_country else None,
                destination_country=destination_country.iso2 if destination_country else None,
            ):
                FavouritePair.objects.create(
                    user=self.user,
                    source_currency=self.eur,
                    destination_currency=self.jpy,
                    source_country=source_country,
                    destination_country=destination_country,
                )

                with self.assertRaises(IntegrityError), transaction.atomic():
                    FavouritePair.objects.create(
                        user=self.user,
                        source_currency=self.eur,
                        destination_currency=self.jpy,
                        source_country=source_country,
                        destination_country=destination_country,
                    )

                FavouritePair.objects.filter(user=self.user).delete()

    def test_sync_unions_and_deduplicates_pair_identity(self):
        self.client.force_login(self.user)

        first = self.post_sync({"favourites": [pair_payload(), pair_payload()]})
        second = self.post_sync({"favourites": [pair_payload()]})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["createdCount"], 1)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["createdCount"], 0)
        self.assertEqual(FavouritePair.objects.filter(user=self.user).count(), 1)

    def test_malformed_sync_is_rejected_before_any_write(self):
        self.client.force_login(self.user)
        invalid = pair_payload()
        invalid["destinationCountry"] = "FI"

        response = self.post_sync(
            {"favourites": [pair_payload(), invalid]},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(FavouritePair.objects.filter(user=self.user).count(), 0)

    def test_sync_rejects_unexpected_fields(self):
        self.client.force_login(self.user)
        item = pair_payload()
        item["savedAt"] = "2026-09-22T12:00:00Z"

        response = self.post_sync({"favourites": [item]})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(FavouritePair.objects.count(), 0)

    def test_cross_user_delete_does_not_reveal_or_delete_favourite(self):
        favourite = FavouritePair.objects.create(
            user=self.user,
            source_currency=self.eur,
            destination_currency=self.jpy,
            source_country=self.fi,
            destination_country=self.jp,
        )
        self.client.force_login(self.other)

        response = self.client.post(reverse("delete_favourite", args=[favourite.pk]))

        self.assertEqual(response.status_code, 404)
        self.assertTrue(FavouritePair.objects.filter(pk=favourite.pk).exists())

    def test_clear_favourites_is_scoped_to_authenticated_owner(self):
        FavouritePair.objects.create(
            user=self.user,
            source_currency=self.eur,
            destination_currency=self.jpy,
            source_country=self.fi,
            destination_country=self.jp,
        )
        other_favourite = FavouritePair.objects.create(
            user=self.other,
            source_currency=self.jpy,
            destination_currency=self.eur,
            source_country=self.jp,
            destination_country=self.fi,
        )
        self.client.force_login(self.user)

        response = self.client.post(reverse("clear_favourites"))

        self.assertRedirects(response, reverse("saved_state"))
        self.assertFalse(FavouritePair.objects.filter(user=self.user).exists())
        self.assertTrue(FavouritePair.objects.filter(pk=other_favourite.pk).exists())

    def test_signed_in_saved_page_renders_only_owner_favourites(self):
        own = FavouritePair.objects.create(
            user=self.user,
            source_currency=self.eur,
            destination_currency=self.jpy,
            source_country=self.fi,
            destination_country=self.jp,
        )
        hidden = FavouritePair.objects.create(
            user=self.other,
            source_currency=self.jpy,
            destination_currency=self.eur,
            source_country=self.jp,
            destination_country=self.fi,
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("saved_state"))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn(f'data-account-favourite-id="{own.pk}"', content)
        self.assertNotIn(f'data-account-favourite-id="{hidden.pk}"', content)
        self.assertIn('aria-label="Use pair: EUR to JPY"', content)
        self.assertIn('aria-label="Reverse pair: EUR to JPY"', content)
        self.assertIn('aria-label="Remove saved pair: EUR to JPY"', content)
        self.assertIn("qa-destructive-button", content)
        self.assertIn('data-account-history-enabled="false"', content)
        self.assertIn("Browser-only history", content)


class FavouriteConcurrentSyncTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        create_reference_data()
        self.user = User.objects.create_user(username="parallel", password="StrongPass-482!")

    @skipUnlessDBFeature("has_select_for_update")
    def test_concurrent_duplicate_sync_creates_one_row(self):
        barrier = Barrier(2)
        payload = [pair_payload()]

        def worker():
            close_old_connections()
            try:
                user = User.objects.get(pk=self.user.pk)
                barrier.wait()
                sync_user_favourites(user, payload)
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(worker) for _ in range(2)]
            for future in futures:
                future.result(timeout=10)

        self.assertEqual(FavouritePair.objects.filter(user=self.user).count(), 1)
