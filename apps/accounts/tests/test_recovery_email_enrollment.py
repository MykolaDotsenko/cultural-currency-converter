"""Verified recovery email requires current password, email ownership and explicit delivery."""

from __future__ import annotations

import re
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import VerifiedRecoveryEmail
from apps.accounts.recovery_email import RecoveryEmailError, confirm_recovery_token

_PASSWORD = "SecureRecovery-247!"
_SETTINGS = {
    "ACCOUNT_EMAIL_VERIFICATION_ENABLED": True,
    "ACCOUNT_EMAIL_PUBLIC_ORIGIN": "https://testserver",
    "DEFAULT_FROM_EMAIL": "accounts@example.test",
    "EMAIL_BACKEND": "django.core.mail.backends.locmem.EmailBackend",
    "VITE_DEV_SERVER_ENABLED": True,
}


@override_settings(**_SETTINGS)
class RecoveryEmailWebTests(TestCase):
    def setUp(self):
        cache.clear()
        self.owner = get_user_model().objects.create_user(
            username="recovery-owner", password=_PASSWORD, email="legacy@example.test"
        )
        self.other = get_user_model().objects.create_user(
            username="recovery-other", password=_PASSWORD
        )
        self.client.force_login(self.owner)

    def tearDown(self):
        cache.clear()

    def _propose(self, address="owner@example.test", password=_PASSWORD):
        return self.client.post(
            reverse("request_recovery_email"),
            {"email": address, "current_password": password},
        )

    def _link(self):
        self.assertEqual(len(mail.outbox), 1)
        match = re.search(
            r"https://testserver(/accounts/recovery-email/confirm/[^\s]+/)",
            mail.outbox[0].body,
        )
        self.assertIsNotNone(match)
        return match.group(1)

    def test_user_must_confirm_address_and_get_request_never_mutates_identity(self):
        response = self._propose("OWNER@EXAMPLE.TEST")
        self.assertRedirects(response, reverse("profile"))
        pending = VerifiedRecoveryEmail.objects.get(user=self.owner)
        self.assertEqual(pending.email, "owner@example.test")
        self.assertIsNone(pending.verified_at)
        link = self._link()
        page = self.client.get(link)
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page["Referrer-Policy"], "no-referrer")
        self.assertEqual(page["Cache-Control"], "no-store")
        pending.refresh_from_db()
        self.assertIsNone(pending.verified_at)
        self.assertRedirects(self.client.post(link), reverse("profile"))
        pending.refresh_from_db()
        self.assertTrue(pending.is_verified)

    def test_confirmation_is_one_time(self):
        self._propose()
        link = self._link()
        self.client.post(link)
        self.assertRedirects(self.client.post(link), reverse("profile"))
        self.assertTrue(VerifiedRecoveryEmail.objects.get(user=self.owner).is_verified)

    def test_another_signed_in_owner_cannot_claim_token(self):
        self._propose()
        link = self._link()
        stranger = Client()
        stranger.force_login(self.other)
        self.assertRedirects(stranger.get(link), reverse("profile"))
        self.assertRedirects(stranger.post(link), reverse("profile"))
        self.assertFalse(VerifiedRecoveryEmail.objects.get(user=self.owner).is_verified)

    def test_invalid_password_does_not_create_pending_or_send(self):
        response = self._propose(password="wrong")
        self.assertEqual(response.status_code, 422)
        self.assertFalse(VerifiedRecoveryEmail.objects.exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_mail_failure_rolls_back_unverified_identity_without_leaking_provider_error(self):
        with patch(
            "apps.accounts.recovery_email.send_mail",
            side_effect=OSError("SMTP_KEY=SECRET credential"),
        ):
            response = self._propose()
        self.assertRedirects(response, reverse("profile"))
        self.assertFalse(VerifiedRecoveryEmail.objects.exists())
        self.assertNotIn("SECRET", response.get("Location", ""))

    def test_throttle_prevents_repeat_verification_mail(self):
        self._propose()
        self._propose()
        self.assertEqual(len(mail.outbox), 1)

    def test_legacy_user_email_does_not_become_verified(self):
        response = self.client.get(reverse("profile"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(VerifiedRecoveryEmail.objects.exists())

    def test_same_verified_email_cannot_be_claimed_by_other_owner(self):
        self._propose()
        self.client.post(self._link())
        cache.clear()
        another = Client()
        another.force_login(self.other)
        response = another.post(
            reverse("request_recovery_email"),
            {"email": "OWNER@example.test", "current_password": _PASSWORD},
        )
        self.assertRedirects(response, reverse("profile"))
        self.assertFalse(VerifiedRecoveryEmail.objects.filter(user=self.other).exists())
        self.assertEqual(len(mail.outbox), 1)

    def test_expired_signature_does_not_activate_pending_address(self):
        self._propose()
        link = self._link()
        with patch(
            "apps.accounts.recovery_email._load_token",
            side_effect=RecoveryEmailError("Verification link invalid or expired."),
        ):
            self.assertRedirects(self.client.post(link), reverse("profile"))
        self.assertFalse(VerifiedRecoveryEmail.objects.get(user=self.owner).is_verified)

    def test_approval_requires_csrf_token(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.owner)
        response = csrf_client.post(
            reverse("request_recovery_email"),
            {"email": "owner@example.test", "current_password": _PASSWORD},
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(VerifiedRecoveryEmail.objects.exists())

    def test_access_logs_redact_signed_confirmation_tokens(self):
        self._propose()
        link = self._link()
        signed_token = link.split("/confirm/", 1)[1].rstrip("/")
        with self.assertLogs("cultural_currency.access", level="INFO") as captured:
            self.client.get(link)
        self.assertTrue(captured.records)
        for record in captured.records:
            self.assertNotIn(signed_token, record.path)
            self.assertEqual(
                record.path, "/accounts/recovery-email/confirm/[redacted]/"
            )

    def test_login_required_for_both_endpoints(self):
        self.client.logout()
        response = self.client.post(reverse("request_recovery_email"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])
        response = self.client.get(
            reverse("recovery_email_confirm", kwargs={"token": "not-a-token"})
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_pending_address_never_becomes_password_reset_identity(self):
        self._propose()
        identity = VerifiedRecoveryEmail.objects.get(user=self.owner)
        self.assertFalse(identity.is_verified)
        with self.assertRaises(RecoveryEmailError):
            confirm_recovery_token(user=self.owner, token="invalid")
        self.assertTrue(self.owner.check_password(_PASSWORD))


@override_settings(ACCOUNT_EMAIL_VERIFICATION_ENABLED=False, VITE_DEV_SERVER_ENABLED=True)
class DisabledRecoveryEmailTests(TestCase):
    def test_disabled_email_has_no_form_or_send(self):
        owner = get_user_model().objects.create_user(username="mail-disabled", password=_PASSWORD)
        self.client.force_login(owner)
        page = self.client.get(reverse("profile"))
        self.assertNotContains(page, 'name="current_password"')
        response = self.client.post(
            reverse("request_recovery_email"),
            {"email": "owner@example.test", "current_password": _PASSWORD},
        )
        self.assertRedirects(response, reverse("profile"))
        self.assertFalse(VerifiedRecoveryEmail.objects.exists())
