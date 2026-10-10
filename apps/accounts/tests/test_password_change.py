"""Logged-in password rotation uses Django's validators, CSRF and session preservation."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

OLD_PASSWORD = "SecureStart-482!"
NEW_PASSWORD = "StrongChanged-735!"


class PasswordChangeWebTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="password-change-owner",
            password=OLD_PASSWORD,
        )

    def test_logged_out_user_cannot_open_change_or_success_page(self):
        for name in ("password_change", "password_change_done"):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 302)
            self.assertIn(reverse("login"), response["Location"])

    def test_account_profile_links_to_authenticated_password_change(self):
        self.client.force_login(self.user)
        profile = self.client.get(reverse("profile"))
        self.assertContains(profile, reverse("password_change"))
        form_page = self.client.get(reverse("password_change"))
        self.assertContains(form_page, "Current password")
        self.assertContains(form_page, 'autocomplete="current-password"')
        self.assertContains(form_page, 'autocomplete="new-password"')

    def test_incorrect_old_password_never_changes_stored_hash(self):
        self.client.force_login(self.user)
        original_hash = self.user.password
        response = self.client.post(
            reverse("password_change"),
            {
                "old_password": "not-my-old-password",
                "new_password1": NEW_PASSWORD,
                "new_password2": NEW_PASSWORD,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.password, original_hash)
        self.assertTrue(self.user.check_password(OLD_PASSWORD))

    def test_new_password_validation_prevents_weak_password(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("password_change"),
            {
                "old_password": OLD_PASSWORD,
                "new_password1": "password",
                "new_password2": "password",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(OLD_PASSWORD))

    def test_success_rotates_password_and_preserves_current_session(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("password_change"),
            {
                "old_password": OLD_PASSWORD,
                "new_password1": NEW_PASSWORD,
                "new_password2": NEW_PASSWORD,
            },
        )
        self.assertRedirects(response, reverse("password_change_done"))
        self.user.refresh_from_db()
        self.assertFalse(self.user.check_password(OLD_PASSWORD))
        self.assertTrue(self.user.check_password(NEW_PASSWORD))
        self.assertEqual(self.client.get(reverse("profile")).status_code, 200)

    def test_password_change_invalidates_another_signed_in_session(self):
        second_browser = Client()
        self.client.force_login(self.user)
        second_browser.force_login(self.user)
        self.assertEqual(second_browser.get(reverse("profile")).status_code, 200)

        changed = self.client.post(
            reverse("password_change"),
            {
                "old_password": OLD_PASSWORD,
                "new_password1": NEW_PASSWORD,
                "new_password2": NEW_PASSWORD,
            },
        )
        self.assertRedirects(changed, reverse("password_change_done"))
        self.assertEqual(self.client.get(reverse("profile")).status_code, 200)

        other_session = second_browser.get(reverse("profile"))
        self.assertEqual(other_session.status_code, 302)
        self.assertIn(reverse("login"), other_session["Location"])

    def test_post_requires_csrf_token(self):
        secure_client = Client(enforce_csrf_checks=True)
        secure_client.force_login(self.user)
        response = secure_client.post(
            reverse("password_change"),
            {
                "old_password": OLD_PASSWORD,
                "new_password1": NEW_PASSWORD,
                "new_password2": NEW_PASSWORD,
            },
        )
        self.assertEqual(response.status_code, 403)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(OLD_PASSWORD))
