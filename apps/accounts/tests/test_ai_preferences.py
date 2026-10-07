from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.ai_preferences import explanation_preferences
from apps.accounts.models import AccountPreferences, AnswerDetail, PreferredLanguage, TravelStyle

User = get_user_model()


@override_settings(VITE_DEV_SERVER_ENABLED=True)
class ExplanationPreferenceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="preference-owner",
            password="StrongPass-482!",
        )

    def test_defaults_are_safe_and_do_not_require_persisted_preferences(self):
        preferences = explanation_preferences(self.user)

        self.assertEqual(preferences.locale, PreferredLanguage.ENGLISH)
        self.assertEqual(preferences.answer_detail, AnswerDetail.BALANCED)
        self.assertEqual(preferences.travel_style, TravelStyle.BALANCED)
        self.assertEqual(preferences.focus_instruction_suffix, "")

    def test_profile_update_persists_only_explicit_presentation_preferences(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("update_explanation_preferences"),
            {
                "preferred_language": PreferredLanguage.UKRAINIAN,
                "answer_detail": AnswerDetail.DETAILED,
                "travel_style": TravelStyle.BUDGET,
            },
        )

        self.assertRedirects(response, reverse("profile"))
        stored = AccountPreferences.objects.get(user=self.user)
        self.assertEqual(stored.preferred_language, PreferredLanguage.UKRAINIAN)
        self.assertEqual(stored.answer_detail, AnswerDetail.DETAILED)
        self.assertEqual(stored.travel_style, TravelStyle.BUDGET)
        self.assertIsNone(stored.home_currency)
        self.assertFalse(stored.sync_recent_history)

        preferences = explanation_preferences(self.user)
        self.assertIn("detailed explanations", preferences.focus_instruction_suffix)
        self.assertIn("supplied price", preferences.focus_instruction_suffix)
        self.assertIn("Do not infer affordability", preferences.focus_instruction_suffix)

    def test_invalid_update_is_rejected_without_mutating_existing_preferences(self):
        AccountPreferences.objects.create(
            user=self.user,
            preferred_language=PreferredLanguage.FINNISH,
            answer_detail=AnswerDetail.CONCISE,
            travel_style=TravelStyle.COMFORT,
        )
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("update_explanation_preferences"),
            {
                "preferred_language": "de",
                "answer_detail": "verbose",
                "travel_style": "luxury",
            },
        )

        self.assertEqual(response.status_code, 422)
        stored = AccountPreferences.objects.get(user=self.user)
        self.assertEqual(stored.preferred_language, PreferredLanguage.FINNISH)
        self.assertEqual(stored.answer_detail, AnswerDetail.CONCISE)
        self.assertEqual(stored.travel_style, TravelStyle.COMFORT)

    def test_profile_explains_that_preferences_do_not_change_financial_truth(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("profile"))
        content = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn("Explanation preferences", content)
        self.assertIn("never change FX rates", content)
        self.assertIn("budget assumptions", content)
        self.assertIn("deterministic", content)
