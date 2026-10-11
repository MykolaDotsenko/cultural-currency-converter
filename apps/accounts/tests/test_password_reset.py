"""Account recovery trusts only verified ownership, never legacy or pending email."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import VerifiedRecoveryEmail
from apps.accounts.password_reset import verified_password_token_generator

_OLD = "Secure-Old-451!"
_NEW = "New-Valid-Password-684!"
_CONFIG = {
    "ACCOUNT_EMAIL_VERIFICATION_ENABLED": True,
    "ACCOUNT_EMAIL_PUBLIC_ORIGIN": "https://testserver",
    "DEFAULT_FROM_EMAIL": "accounts@example.test",
    "EMAIL_BACKEND": "django.core.mail.backends.locmem.EmailBackend",
    "PASSWORD_RESET_TIMEOUT": 1800,
    "VITE_DEV_SERVER_ENABLED": True,
}


@override_settings(**_CONFIG)
class VerifiedPasswordResetTests(TestCase):
    def setUp(self):
        cache.clear()
        self.owner = get_user_model().objects.create_user(
            username="reset-owner", email="legacy@example.test", password=_OLD
        )
        self.identity = VerifiedRecoveryEmail.objects.create(
            user=self.owner, email="verified@example.test", verified_at=timezone.now()
        )

    def tearDown(self):
        cache.clear()

    def _request(self, email="verified@example.test", *, remote="10.10.10.3"):
        return self.client.post(
            reverse("password_reset_request"),
            {"email": email},
            REMOTE_ADDR=remote,
        )

    def _link(self):
        self.assertEqual(len(mail.outbox), 1)
        match = re.search(
            r"https://testserver(/accounts/password/reset/[^/\\s]+/[^/\\s]+/)",
            mail.outbox[0].body,
        )
        self.assertIsNotNone(match)
        return match.group(1)

    def test_verified_email_can_reset_password_once_without_changing_saved_identity(self):
        page = self.client.get(reverse("login"))
        self.assertContains(page, reverse("password_reset_request"))
        self.assertRedirects(self._request("VERIFIED@EXAMPLE.TEST"), reverse("password_reset_sent"))
        self.assertNotIn("verified@example.test", self.client.get(reverse("password_reset_sent")).content.decode())
        link = self._link()
        viewed = self.client.get(link)
        self.assertEqual(viewed.status_code, 200)
        self.assertContains(viewed, "Set a new password")
        self.assertEqual(viewed["Cache-Control"], "no-store")
        self.assertEqual(viewed["Referrer-Policy"], "no-referrer")
        self.assertTrue(self.owner.check_password(_OLD))
        changed = self.client.post(
            link, {"new_password1": _NEW, "new_password2": _NEW}
        )
        self.assertRedirects(changed, reverse("password_reset_complete"))
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.check_password(_NEW))
        self.assertFalse(self.owner.check_password(_OLD))
        self.assertEqual(self.identity.user_id, self.owner.pk)
        self.assertContains(self.client.get(link), "invalid or expired")
        self.assertEqual(
            self.client.post(link, {"new_password1": "Again-Secure-543!", "new_password2": "Again-Secure-543!"}).status_code,
            200,
        )
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.check_password(_NEW))

    def test_unknown_pending_and_legacy_addresses_share_same_response(self):
        self.identity.verified_at = None
        self.identity.save(update_fields=["verified_at"])
        known = self._request("verified@example.test", remote="10.0.0.1")
        self.assertRedirects(known, reverse("password_reset_sent"))
        unknown = self._request("nobody@example.test", remote="10.0.0.2")
        legacy = self._request("legacy@example.test", remote="10.0.0.3")
        self.assertEqual(known.status_code, unknown.status_code)
        self.assertEqual(legacy["Location"], known["Location"])
        self.assertEqual(len(mail.outbox), 0)

    def test_verified_email_changes_invalidate_old_token(self):
        self._request()
        link = self._link()
        VerifiedRecoveryEmail.objects.filter(user=self.owner).update(
            email="different@example.test", verification_nonce=uuid4()
        )
        self.assertContains(self.client.get(link), "invalid or expired")
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.check_password(_OLD))

    def test_token_expires_after_thirty_minutes(self):
        self._request()
        link = self._link()
        with patch.object(
            verified_password_token_generator,
            "_now",
            return_value=datetime.now() + timedelta(minutes=31),
        ):
            self.assertContains(self.client.get(link), "invalid or expired")

    def test_invalid_and_weak_new_passwords_do_not_change_hash(self):
        self._request()
        link = self._link()
        for data in (
            {"new_password1": "password", "new_password2": "password"},
            {"new_password1": "Strong-First-123!", "new_password2": "Different-321!"},
        ):
            response = self.client.post(link, data)
            self.assertEqual(response.status_code, 200)
            self.owner.refresh_from_db()
            self.assertTrue(self.owner.check_password(_OLD))

    def test_existing_session_is_revoked_after_reset(self):
        other = Client()
        other.force_login(self.owner)
        self.assertEqual(other.get(reverse("profile")).status_code, 200)
        self._request()
        link = self._link()
        self.client.post(link, {"new_password1": _NEW, "new_password2": _NEW})
        response = other.get(reverse("profile"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_reset_requests_are_rate_limited_by_recipient(self):
        self._request()
        self._request(remote="10.10.10.4")
        self.assertEqual(len(mail.outbox), 1)

    def test_cache_failure_and_smtp_errors_never_disclose_secrets(self):
        with patch(
            "apps.accounts.password_reset.cache.add",
            side_effect=OSError("CACHE_PASS=PRIVATE"),
        ):
            response = self._request()
        self.assertRedirects(response, reverse("password_reset_sent"))
        self.assertEqual(len(mail.outbox), 0)
        cache.clear()
        with patch(
            "apps.accounts.password_reset.send_mail",
            side_effect=OSError("SMTP_SECRET=PRIVATE"),
        ):
            response = self._request(remote="10.10.10.4")
        self.assertRedirects(response, reverse("password_reset_sent"))
        self.assertEqual(len(mail.outbox), 0)
        self.assertNotIn("PRIVATE", response.content.decode())

    def test_reset_request_and_confirm_require_csrf(self):
        strict = Client(enforce_csrf_checks=True)
        self.assertEqual(
            strict.post(reverse("password_reset_request"), {"email": "verified@example.test"}).status_code,
            403,
        )
        self._request()
        link = self._link()
        self.assertEqual(
            strict.post(link, {"new_password1": _NEW, "new_password2": _NEW}).status_code,
            403,
        )
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.check_password(_OLD))

    def test_token_paths_are_redacted_in_request_access_logs(self):
        self._request()
        link = self._link()
        with self.assertLogs("cultural_currency.access", level="INFO") as logs:
            self.client.get(link)
        for record in logs.records:
            self.assertEqual(record.path, "/accounts/password/reset/[redacted]/")
            self.assertNotIn(link, record.path)

    def test_unusable_or_inactive_accounts_get_no_link(self):
        self.owner.is_active = False
        self.owner.save(update_fields=["is_active"])
        self._request()
        self.assertEqual(len(mail.outbox), 0)

    def test_malformed_token_never_changes_password(self):
        response = self.client.get(
            reverse(
                "password_reset_confirm",
                kwargs={"uidb64": "bad-value", "token": "invalid"},
            )
        )
        self.assertContains(response, "invalid or expired")


@override_settings(ACCOUNT_EMAIL_VERIFICATION_ENABLED=False, VITE_DEV_SERVER_ENABLED=True)
class ResetDisabledTests(TestCase):
    def test_reset_is_disabled_and_not_linked(self):
        self.assertNotContains(self.client.get(reverse("login")), "Forgot password?")
        response = self.client.get(reverse("password_reset_request"))
        self.assertContains(response, "unavailable")
        self.assertRedirects(
            self.client.post(reverse("password_reset_request"), {"email": "x@example.test"}),
            reverse("password_reset_sent"),
        )
