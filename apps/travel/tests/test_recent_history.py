from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import DatabaseError, close_old_connections
from django.test import TestCase, TransactionTestCase, override_settings, skipUnlessDBFeature
from django.urls import reverse

from apps.accounts.models import AccountPreferences
from apps.countries.models import Country, CountryCurrency, Currency
from apps.travel.history import MAX_ACCOUNT_RECENTS, record_recent_conversion
from apps.travel.models import RecentConversion

User = get_user_model()
PASSWORD = "StrongPass-482!"


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


def record_kwargs(*, amount: str = "10", output: str = "1745"):
    return {
        "source_currency_code": "EUR",
        "destination_currency_code": "JPY",
        "source_country_code": "FI",
        "destination_country_code": "JP",
        "input_amount": Decimal(amount),
        "output_amount": Decimal(output),
        "historical": False,
        "requested_date": None,
        "effective_date": date(2026, 9, 22),
    }


class RecentHistoryServiceTests(TestCase):
    def setUp(self):
        create_reference_data()
        self.user = User.objects.create_user(username="history-owner", password=PASSWORD)

    def test_history_is_off_by_default(self):
        recent = record_recent_conversion(self.user, **record_kwargs())

        self.assertIsNone(recent)
        self.assertEqual(RecentConversion.objects.count(), 0)

    def test_enabled_history_records_successful_snapshot(self):
        AccountPreferences.objects.create(user=self.user, sync_recent_history=True)

        recent = record_recent_conversion(self.user, **record_kwargs())

        self.assertIsNotNone(recent)
        assert recent is not None
        self.assertEqual(recent.input_amount, "10")
        self.assertEqual(recent.output_amount, "1745")
        self.assertEqual(recent.rate_mode, RecentConversion.RateMode.LATEST)
        self.assertIsNone(recent.requested_date)
        self.assertEqual(recent.effective_date, date(2026, 9, 22))

    def test_duplicate_intent_updates_one_recent_row(self):
        AccountPreferences.objects.create(user=self.user, sync_recent_history=True)
        first = record_recent_conversion(self.user, **record_kwargs(output="1745"))
        second = record_recent_conversion(self.user, **record_kwargs(output="1750"))

        self.assertEqual(RecentConversion.objects.filter(user=self.user).count(), 1)
        self.assertEqual(first.pk, second.pk)
        second.refresh_from_db()
        self.assertEqual(second.output_amount, "1750")

    def test_historical_snapshot_preserves_requested_and_effective_dates(self):
        AccountPreferences.objects.create(user=self.user, sync_recent_history=True)
        recent = record_recent_conversion(
            self.user,
            source_currency_code="EUR",
            destination_currency_code="JPY",
            source_country_code="FI",
            destination_country_code="JP",
            input_amount=Decimal("100"),
            output_amount=Decimal("16000"),
            historical=True,
            requested_date=date(2020, 1, 4),
            effective_date=date(2020, 1, 3),
        )

        assert recent is not None
        self.assertEqual(recent.rate_mode, RecentConversion.RateMode.HISTORICAL)
        self.assertEqual(recent.requested_date, date(2020, 1, 4))
        self.assertEqual(recent.effective_date, date(2020, 1, 3))

    def test_account_history_is_bounded_to_fifty_rows(self):
        AccountPreferences.objects.create(user=self.user, sync_recent_history=True)

        for index in range(MAX_ACCOUNT_RECENTS + 1):
            record_recent_conversion(
                self.user,
                **record_kwargs(amount=str(index + 1), output=str(1700 + index)),
            )

        recents = RecentConversion.objects.filter(user=self.user)
        self.assertEqual(recents.count(), MAX_ACCOUNT_RECENTS)
        self.assertFalse(recents.filter(input_amount="1").exists())
        self.assertTrue(recents.filter(input_amount=str(MAX_ACCOUNT_RECENTS + 1)).exists())


@override_settings(VITE_DEV_SERVER_ENABLED=True)
class RecentHistoryWebTests(TestCase):
    def setUp(self):
        self.eur, self.jpy, self.fi, self.jp = create_reference_data()
        self.user = User.objects.create_user(username="history-owner", password=PASSWORD)
        self.other = User.objects.create_user(username="other-user", password=PASSWORD)

    def _create_recent(self, *, user, amount="10"):
        AccountPreferences.objects.get_or_create(
            user=user,
            defaults={"sync_recent_history": True},
        )
        return record_recent_conversion(user, **record_kwargs(amount=amount))

    def test_cross_user_recent_delete_returns_not_found(self):
        recent = self._create_recent(user=self.user)
        assert recent is not None
        self.client.force_login(self.other)

        response = self.client.post(reverse("delete_recent_conversion", args=[recent.pk]))

        self.assertEqual(response.status_code, 404)
        self.assertTrue(RecentConversion.objects.filter(pk=recent.pk).exists())

    def test_clear_recent_history_is_owner_scoped(self):
        own = self._create_recent(user=self.user)
        other = self._create_recent(user=self.other, amount="20")
        assert own is not None
        assert other is not None
        self.client.force_login(self.user)

        response = self.client.post(reverse("clear_recent_conversions"))

        self.assertRedirects(response, reverse("saved_state"))
        self.assertFalse(RecentConversion.objects.filter(pk=own.pk).exists())
        self.assertTrue(RecentConversion.objects.filter(pk=other.pk).exists())

    def test_saved_page_separates_account_and_browser_history(self):
        recent = self._create_recent(user=self.user)
        assert recent is not None
        self.client.force_login(self.user)

        response = self.client.get(reverse("saved_state"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Account recent history")
        self.assertContains(response, "Browser-only history")
        self.assertContains(response, f'data-account-recent-id="{recent.pk}"')
        self.assertContains(response, 'aria-label="Repeat conversion: 10 EUR to JPY"')
        self.assertContains(response, 'aria-label="Compare destination: Japan"')
        self.assertContains(response, 'href="/compare/?left_destination=JP"')
        self.assertContains(response, 'aria-label="Swap conversion: 10 EUR to JPY"')
        self.assertContains(response, 'aria-label="Remove recent conversion: 10 EUR to JPY"')
        self.assertContains(response, "qa-destructive-button")
        self.assertContains(response, "never uploaded automatically")

    def test_disabling_history_keeps_existing_account_rows(self):
        recent = self._create_recent(user=self.user)
        assert recent is not None
        AccountPreferences.objects.filter(user=self.user).update(sync_recent_history=False)
        self.client.force_login(self.user)

        response = self.client.get(reverse("saved_state"))

        self.assertContains(response, "Off. No future conversions are added to your account.")
        self.assertContains(response, f'data-account-recent-id="{recent.pk}"')

    def test_same_currency_converter_records_only_after_opt_in(self):
        self.client.force_login(self.user)
        params = {
            "convert": "1",
            "amount": "10",
            "source_country": "FI",
            "source_currency": "EUR",
            "destination_country": "FI",
            "destination_currency": "EUR",
            "rate_mode": "latest",
        }

        response = self.client.get(reverse("converter"), params)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(RecentConversion.objects.filter(user=self.user).count(), 0)
        self.assertContains(response, 'data-account-recent-recorded="false"')

        AccountPreferences.objects.create(user=self.user, sync_recent_history=True)
        response = self.client.get(reverse("converter"), params)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(RecentConversion.objects.filter(user=self.user).count(), 1)
        self.assertContains(response, 'data-account-recent-recorded="true"')

    def test_history_write_failure_does_not_break_conversion(self):
        AccountPreferences.objects.create(user=self.user, sync_recent_history=True)
        self.client.force_login(self.user)
        params = {
            "convert": "1",
            "amount": "10",
            "source_country": "FI",
            "source_currency": "EUR",
            "destination_country": "FI",
            "destination_currency": "EUR",
            "rate_mode": "latest",
        }

        with patch(
            "apps.exchange.views.record_recent_conversion",
            side_effect=DatabaseError("history unavailable"),
        ):
            response = self.client.get(reverse("converter"), params)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-account-recent-recorded="false"')


class RecentHistoryConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        create_reference_data()
        self.user = User.objects.create_user(username="parallel-history", password=PASSWORD)
        AccountPreferences.objects.create(user=self.user, sync_recent_history=True)

    @skipUnlessDBFeature("has_select_for_update")
    def test_concurrent_duplicate_record_creates_one_row(self):
        barrier = Barrier(2)

        def worker():
            close_old_connections()
            try:
                user = User.objects.get(pk=self.user.pk)
                barrier.wait()
                record_recent_conversion(user, **record_kwargs())
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(worker) for _ in range(2)]
            for future in futures:
                future.result(timeout=10)

        self.assertEqual(RecentConversion.objects.filter(user=self.user).count(), 1)
