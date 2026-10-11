"""Login and signup rate guards fail closed and do not expose identities."""

from __future__ import annotations

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.accounts.auth_throttle import login_allowed

_PASSWORD = "A-Verified-Password-742!"


@override_settings(VITE_DEV_SERVER_ENABLED=True)
class AuthThrottleTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="known-person", password=_PASSWORD
        )

    def tearDown(self):
        cache.clear()

    def _login(self, username="known-person", password="wrong-pass", *, client="10.10.0.1"):
        return self.client.post(
            reverse("login"),
            {"username": username, "password": password},
            REMOTE_ADDR=client,
        )

    def test_eight_failures_block_known_username_before_password_validation(self):
        for _ in range(8):
            self.assertEqual(self._login().status_code, 200)
        blocked = self._login(password=_PASSWORD, client="10.10.0.9")
        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(blocked["Retry-After"], "900")
        self.assertIn("no-store", blocked["Cache-Control"])
        self.assertFalse("_auth_user_id" in self.client.session)

    def test_nonexistent_username_has_same_block_status(self):
        for _ in range(8):
            self.assertEqual(self._login(username="does-not-exist").status_code, 200)
        blocked = self._login(username="does-not-exist")
        self.assertEqual(blocked.status_code, 429)
        self.assertNotContains(blocked, "does-not-exist", status_code=429)
        self.assertNotContains(blocked, _PASSWORD, status_code=429)

    def test_successful_login_clears_username_only(self):
        self.assertEqual(self._login().status_code, 200)
        self.assertEqual(self._login(password=_PASSWORD).status_code, 302)
        self.assertTrue(self.client.session.get("_auth_user_id"))
        self.assertTrue(login_allowed(username="known-person", remote_addr="10.10.0.7"))

    def test_client_limit_stops_username_spraying(self):
        for i in range(40):
            self.assertEqual(
                self._login(username=f"unknown-{i}", client="10.10.0.3").status_code,
                200,
            )
        self.assertEqual(
            self._login(username="another-unknown", client="10.10.0.3").status_code,
            429,
        )

    def test_throttle_cannot_be_bypassed_using_forwarded_for(self):
        for _ in range(8):
            self.client.post(
                reverse("login"),
                {"username": "known-person", "password": "invalid"},
                REMOTE_ADDR="10.10.0.5",
                HTTP_X_FORWARDED_FOR="1.1.1.1",
            )
        self.assertEqual(
            self.client.post(
                reverse("login"),
                {"username": "known-person", "password": _PASSWORD},
                REMOTE_ADDR="10.10.0.5",
                HTTP_X_FORWARDED_FOR="9.9.9.9",
            ).status_code,
            429,
        )

    def test_cache_failure_fails_closed_before_session_creation(self):
        with patch(
            "apps.accounts.auth_throttle.cache.get",
            side_effect=OSError("secret redis connection detail"),
        ):
            denied = self._login(password=_PASSWORD)
        self.assertEqual(denied.status_code, 503)
        self.assertNotContains(denied, "secret", status_code=503)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_cache_write_error_fails_closed_after_bad_credentials(self):
        with patch(
            "apps.accounts.auth_throttle.cache.add",
            side_effect=OSError("PRIVATE_REDIS_CREDENTIAL"),
        ):
            denied = self._login()
        self.assertEqual(denied.status_code, 503)
        self.assertNotContains(denied, "PRIVATE_REDIS_CREDENTIAL", status_code=503)

    def test_signup_is_limited_per_server_verified_client(self):
        for _ in range(12):
            response = self.client.post(
                reverse("signup"),
                {"username": "a", "password1": "weak", "password2": "weak"},
                REMOTE_ADDR="10.10.0.8",
            )
            self.assertEqual(response.status_code, 200)
        response = self.client.post(
            reverse("signup"),
            {"username": "fresh-signup", "password1": _PASSWORD, "password2": _PASSWORD},
            REMOTE_ADDR="10.10.0.8",
        )
        self.assertEqual(response.status_code, 429)
        self.assertFalse(get_user_model().objects.filter(username="fresh-signup").exists())
        self.assertEqual(response["Cache-Control"], "no-store")

    def test_signup_cache_failure_refuses_to_create_account(self):
        with patch(
            "apps.accounts.auth_throttle.cache.get",
            side_effect=OSError("redis private information"),
        ):
            response = self.client.post(
                reverse("signup"),
                {"username": "fresh-signup", "password1": _PASSWORD, "password2": _PASSWORD},
            )
        self.assertEqual(response.status_code, 503)
        self.assertFalse(get_user_model().objects.filter(username="fresh-signup").exists())
        self.assertNotContains(response, "redis private", status_code=503)

    def test_login_get_and_logout_remain_usable(self):
        self.assertEqual(self.client.get(reverse("login")).status_code, 200)
        self.assertEqual(self._login(password=_PASSWORD).status_code, 302)
        self.assertEqual(self.client.post(reverse("logout")).status_code, 302)

    def test_login_csrf_still_required(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(
            client.post(
                reverse("login"),
                {"username": "known-person", "password": _PASSWORD},
            ).status_code,
            403,
        )
