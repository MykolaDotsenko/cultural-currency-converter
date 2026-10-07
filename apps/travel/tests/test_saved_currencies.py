from __future__ import annotations

import json

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.countries.models import Currency
from apps.travel.models import SavedCurrency
from apps.travel.personalization import sync_user_saved_currencies

User = get_user_model()


@override_settings(VITE_DEV_SERVER_ENABLED=True)
class SavedCurrencyTests(TestCase):
    def setUp(self):
        self.eur = Currency.objects.create(code="EUR", name="Euro")
        self.jpy = Currency.objects.create(code="JPY", name="Japanese yen", minor_units=0)
        self.inactive = Currency.objects.create(code="ZZZ", name="Inactive", is_active=False)
        self.user = User.objects.create_user(
            username="currency-owner",
            password="StrongPass-482!",
        )
        self.other = User.objects.create_user(
            username="currency-other",
            password="StrongPass-482!",
        )

    def test_sync_is_owner_scoped_and_idempotent(self):
        first = sync_user_saved_currencies(self.user, ["eur", "JPY", "EUR"])
        second = sync_user_saved_currencies(self.user, ["EUR"])

        self.assertEqual(first.created_count, 2)
        self.assertEqual(second.created_count, 0)
        self.assertEqual(
            set(
                SavedCurrency.objects.filter(user=self.user).values_list(
                    "currency__code",
                    flat=True,
                )
            ),
            {"EUR", "JPY"},
        )

    def test_database_rejects_duplicate_currency_for_owner(self):
        SavedCurrency.objects.create(user=self.user, currency=self.eur)

        with self.assertRaises(IntegrityError), transaction.atomic():
            SavedCurrency.objects.create(user=self.user, currency=self.eur)

    def test_json_sync_requires_auth_and_rejects_inactive_currency(self):
        unauthenticated = self.client.post(
            reverse("sync_saved_currencies"),
            data=json.dumps({"currencies": ["EUR"]}),
            content_type="application/json",
        )
        self.assertEqual(unauthenticated.status_code, 401)

        self.client.force_login(self.user)
        invalid = self.client.post(
            reverse("sync_saved_currencies"),
            data=json.dumps({"currencies": ["ZZZ"]}),
            content_type="application/json",
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertFalse(SavedCurrency.objects.exists())

    def test_no_js_save_delete_and_clear_are_owner_scoped(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("save_currency"),
            {"currency_code": "EUR"},
        )
        self.assertRedirects(response, reverse("saved_state"))
        own = SavedCurrency.objects.get(user=self.user, currency=self.eur)
        other = SavedCurrency.objects.create(user=self.other, currency=self.jpy)

        hidden = self.client.post(reverse("delete_saved_currency", args=[other.pk]))
        self.assertEqual(hidden.status_code, 404)
        self.assertTrue(SavedCurrency.objects.filter(pk=other.pk).exists())

        removed = self.client.post(reverse("delete_saved_currency", args=[own.pk]))
        self.assertRedirects(removed, reverse("saved_state"))
        self.assertFalse(SavedCurrency.objects.filter(pk=own.pk).exists())

        SavedCurrency.objects.create(user=self.user, currency=self.eur)
        cleared = self.client.post(reverse("clear_saved_currencies"))
        self.assertRedirects(cleared, reverse("saved_state"))
        self.assertFalse(SavedCurrency.objects.filter(user=self.user).exists())
        self.assertTrue(SavedCurrency.objects.filter(pk=other.pk).exists())

    def test_saved_page_exposes_canonical_currency_reentry(self):
        SavedCurrency.objects.create(user=self.user, currency=self.eur)
        self.client.force_login(self.user)

        response = self.client.get(reverse("saved_state"))
        content = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn("Saved currencies", content)
        self.assertIn('data-account-currency-id="', content)
        self.assertIn("source_currency=EUR", content)
        self.assertIn("destination_currency=EUR", content)
        self.assertIn("Import browser currencies to account", content)

    def test_currency_options_are_loaded_explicitly(self):
        response = self.client.get(reverse("saved_currency_options"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            payload["currencies"],
            [
                {"code": "EUR", "name": "Euro"},
                {"code": "JPY", "name": "Japanese yen"},
            ],
        )

    def test_status_returns_only_owner_active_currency_codes(self):
        SavedCurrency.objects.create(user=self.user, currency=self.eur)
        SavedCurrency.objects.create(user=self.other, currency=self.jpy)
        self.client.force_login(self.user)

        response = self.client.get(reverse("saved_currencies_status"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"codes": ["EUR"]})
