from __future__ import annotations

from datetime import UTC, date, datetime

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import (
    AccountPreferences,
    BudgetPreset,
    BudgetPresetItem,
    PaymentFeeProfile,
)
from apps.countries.models import Country, CountryCurrency, Currency
from apps.travel.models import (
    FavouritePair,
    RecentConversion,
    SavedComparison,
    SavedComparisonBudgetItem,
    SavedPlace,
)

User = get_user_model()
PASSWORD = "StrongPass-482!"


@override_settings(VITE_DEV_SERVER_ENABLED=True)
class AccountWebTests(TestCase):
    def test_signup_authenticates_and_redirects_to_saved_state(self):
        response = self.client.post(
            reverse("signup"),
            {
                "username": "new-user",
                "password1": PASSWORD,
                "password2": PASSWORD,
            },
        )

        self.assertRedirects(response, reverse("saved_state"))
        self.assertTrue(User.objects.filter(username="new-user").exists())
        profile = self.client.get(reverse("profile"))
        self.assertEqual(profile.status_code, 200)

    def test_signup_preserves_safe_same_host_next(self):
        next_url = "/?load=1&source_currency=EUR&destination_currency=JPY"

        response = self.client.post(
            reverse("signup"),
            {
                "username": "returning",
                "password1": PASSWORD,
                "password2": PASSWORD,
                "next": next_url,
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], next_url)

    def test_signup_rejects_external_next(self):
        response = self.client.post(
            reverse("signup"),
            {
                "username": "safe-user",
                "password1": PASSWORD,
                "password2": PASSWORD,
                "next": "https://attacker.example/phish",
            },
        )

        self.assertRedirects(response, reverse("saved_state"))

    def test_home_currency_preference_is_explicit_and_clearable(self):
        user = User.objects.create_user(username="home-currency-member", password=PASSWORD)
        eur = Currency.objects.create(code="EUR", name="Euro")
        self.client.force_login(user)

        response = self.client.get(reverse("profile"))
        self.assertContains(response, "No account default is saved.")
        self.assertFalse(AccountPreferences.objects.filter(user=user).exists())

        response = self.client.post(
            reverse("update_home_currency_preference"),
            {"home_currency": "EUR"},
        )
        self.assertRedirects(response, reverse("profile"))
        preferences = AccountPreferences.objects.get(user=user)
        self.assertEqual(preferences.home_currency, eur)

        response = self.client.post(
            reverse("update_home_currency_preference"),
            {"home_currency": ""},
        )
        self.assertRedirects(response, reverse("profile"))
        preferences.refresh_from_db()
        self.assertIsNone(preferences.home_currency)

    def test_home_currency_preference_rejects_inactive_currency(self):
        user = User.objects.create_user(username="inactive-home-currency", password=PASSWORD)
        Currency.objects.create(code="USD", name="US dollar", is_active=False)
        self.client.force_login(user)

        response = self.client.post(
            reverse("update_home_currency_preference"),
            {"home_currency": "USD"},
        )

        self.assertEqual(response.status_code, 422)
        self.assertContains(response, "Select a valid choice", status_code=422)
        self.assertFalse(AccountPreferences.objects.filter(user=user).exists())

    def test_home_currency_preference_is_post_only(self):
        user = User.objects.create_user(username="home-currency-post-only", password=PASSWORD)
        self.client.force_login(user)

        response = self.client.get(reverse("update_home_currency_preference"))

        self.assertEqual(response.status_code, 405)
        self.assertFalse(AccountPreferences.objects.filter(user=user).exists())

    def test_profile_lists_only_owner_fee_profiles_and_delete_is_owner_scoped(self):
        user = User.objects.create_user(username="fee-profile-owner", password=PASSWORD)
        other = User.objects.create_user(username="fee-profile-other", password=PASSWORD)
        eur = Currency.objects.create(code="EUR", name="Euro")
        jpy = Currency.objects.create(code="JPY", name="Japanese yen")
        own = PaymentFeeProfile.objects.create(
            user=user,
            name="Travel card",
            source_currency=eur,
            destination_currency=jpy,
            fx_markup_percent="1.50",
            source_fixed_fee="0.50",
            destination_fixed_fee="100",
        )
        foreign = PaymentFeeProfile.objects.create(
            user=other,
            name="Other card",
            source_currency=eur,
            destination_currency=jpy,
            fx_markup_percent="2.00",
            source_fixed_fee="1.00",
            destination_fixed_fee="200",
        )
        self.client.force_login(user)

        response = self.client.get(reverse("profile"))

        self.assertContains(response, "Travel card")
        self.assertNotContains(response, "Other card")

        response = self.client.post(reverse("delete_fee_profile", args=(foreign.pk,)))
        self.assertRedirects(response, reverse("profile"))
        self.assertTrue(PaymentFeeProfile.objects.filter(pk=foreign.pk).exists())

        response = self.client.post(reverse("delete_fee_profile", args=(own.pk,)))
        self.assertRedirects(response, reverse("profile"))
        self.assertFalse(PaymentFeeProfile.objects.filter(pk=own.pk).exists())

    def test_profile_lists_only_owner_budget_presets_and_delete_is_owner_scoped(self):
        user = User.objects.create_user(username="budget-preset-owner", password=PASSWORD)
        other = User.objects.create_user(username="budget-preset-other", password=PASSWORD)
        own = BudgetPreset.objects.create(
            user=user,
            name="Weekend city",
            duration_days=3,
            travelers=2,
        )
        BudgetPresetItem.objects.create(
            preset=own,
            category="coffee",
            units_per_person_per_day="1.50",
        )
        foreign = BudgetPreset.objects.create(
            user=other,
            name="Other plan",
            duration_days=5,
            travelers=1,
        )
        BudgetPresetItem.objects.create(
            preset=foreign,
            category="casual_meal",
            units_per_person_per_day="2.00",
        )
        self.client.force_login(user)

        response = self.client.get(reverse("profile"))

        self.assertContains(response, "Weekend city")
        self.assertContains(response, "Coffee 1.5")
        self.assertNotContains(response, "Other plan")

        response = self.client.post(reverse("delete_budget_preset", args=(foreign.pk,)))
        self.assertRedirects(response, reverse("profile"))
        self.assertTrue(BudgetPreset.objects.filter(pk=foreign.pk).exists())

        response = self.client.post(reverse("delete_budget_preset", args=(own.pk,)))
        self.assertRedirects(response, reverse("profile"))
        self.assertFalse(BudgetPreset.objects.filter(pk=own.pk).exists())

    def test_recent_history_preference_defaults_off_and_toggles_explicitly(self):
        user = User.objects.create_user(username="privacy-member", password=PASSWORD)
        self.client.force_login(user)

        response = self.client.get(reverse("profile"))
        self.assertContains(response, "Off by default.")
        self.assertFalse(AccountPreferences.objects.filter(user=user).exists())

        response = self.client.post(
            reverse("update_recent_history_preference"),
            {"action": "enable"},
        )
        self.assertRedirects(response, reverse("profile"))
        preferences = AccountPreferences.objects.get(user=user)
        self.assertTrue(preferences.sync_recent_history)

        response = self.client.post(
            reverse("update_recent_history_preference"),
            {"action": "disable"},
        )
        self.assertRedirects(response, reverse("profile"))
        preferences.refresh_from_db()
        self.assertFalse(preferences.sync_recent_history)

    def test_recent_history_preference_is_post_only(self):
        user = User.objects.create_user(username="privacy-post-only", password=PASSWORD)
        self.client.force_login(user)

        response = self.client.get(reverse("update_recent_history_preference"))

        self.assertEqual(response.status_code, 405)
        self.assertFalse(AccountPreferences.objects.filter(user=user).exists())

    def test_recent_history_preference_rejects_unknown_action(self):
        user = User.objects.create_user(username="privacy-safe", password=PASSWORD)
        self.client.force_login(user)

        response = self.client.post(
            reverse("update_recent_history_preference"),
            {"action": "unexpected"},
        )

        self.assertRedirects(response, reverse("profile"))
        self.assertFalse(AccountPreferences.objects.filter(user=user).exists())

    def test_profile_requires_authentication(self):
        response = self.client.get(reverse("profile"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_logout_is_post_only(self):
        user = User.objects.create_user(username="member", password=PASSWORD)
        self.client.force_login(user)

        response = self.client.get(reverse("logout"))

        self.assertEqual(response.status_code, 405)

    def test_account_deletion_requires_current_password(self):
        user = User.objects.create_user(username="member", password=PASSWORD)
        self.client.force_login(user)

        response = self.client.post(reverse("delete_account"), {"password": "wrong-password"})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(User.objects.filter(pk=user.pk).exists())
        self.assertContains(response, "The password is incorrect.")

    def test_account_deletion_cascades_all_account_owned_personalization(self):
        user = User.objects.create_user(username="member", password=PASSWORD)
        eur = Currency.objects.create(code="EUR", name="Euro")
        jpy = Currency.objects.create(code="JPY", name="Japanese yen")
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
        FavouritePair.objects.create(
            user=user,
            source_currency=eur,
            destination_currency=jpy,
            source_country=fi,
            destination_country=jp,
        )
        AccountPreferences.objects.create(user=user, sync_recent_history=True)
        PaymentFeeProfile.objects.create(
            user=user,
            name="Travel card",
            source_currency=eur,
            destination_currency=jpy,
            fx_markup_percent="1.50",
            source_fixed_fee="0.50",
            destination_fixed_fee="100",
        )
        preset = BudgetPreset.objects.create(
            user=user,
            name="Weekend city",
            duration_days=3,
            travelers=2,
        )
        BudgetPresetItem.objects.create(
            preset=preset,
            category="coffee",
            units_per_person_per_day="1.00",
        )
        RecentConversion.objects.create(
            user=user,
            fingerprint="a" * 64,
            source_currency=eur,
            destination_currency=jpy,
            source_country=fi,
            destination_country=jp,
            input_amount="10",
            output_amount="1745",
            rate_mode=RecentConversion.RateMode.LATEST,
            requested_date=None,
            effective_date=date(2026, 9, 22),
            converted_at=datetime(2026, 9, 22, 12, tzinfo=UTC),
        )
        SavedPlace.objects.create(
            user=user,
            country=jp,
        )
        comparison = SavedComparison.objects.create(
            user=user,
            fingerprint="b" * 64,
            source_currency=eur,
            source_amount="500",
            left_country=fi,
            right_country=jp,
            duration_days=5,
            travelers=2,
        )
        SavedComparisonBudgetItem.objects.create(
            comparison=comparison,
            category="coffee",
            units_per_person_per_day="1",
        )
        self.client.force_login(user)

        response = self.client.post(reverse("delete_account"), {"password": PASSWORD})

        self.assertRedirects(response, reverse("converter"))
        self.assertFalse(User.objects.filter(pk=user.pk).exists())
        self.assertEqual(FavouritePair.objects.count(), 0)
        self.assertEqual(RecentConversion.objects.count(), 0)
        self.assertEqual(SavedPlace.objects.count(), 0)
        self.assertEqual(SavedComparison.objects.count(), 0)
        self.assertEqual(SavedComparisonBudgetItem.objects.count(), 0)
        self.assertEqual(AccountPreferences.objects.count(), 0)
        self.assertEqual(PaymentFeeProfile.objects.count(), 0)
        self.assertEqual(BudgetPreset.objects.count(), 0)
        self.assertEqual(BudgetPresetItem.objects.count(), 0)
        self.assertNotIn("_auth_user_id", self.client.session)
