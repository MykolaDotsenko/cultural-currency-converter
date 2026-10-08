from __future__ import annotations

import os
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.common.release_identity import get_deployed_revision

SHA = "371681ccfc5d0fea4a00fbfd59455242cddb1919"
OTHER_SHA = "a" * 40


class DeployedRevisionIdentityTests(SimpleTestCase):
    def test_render_revision_is_normalized_without_database_access(self) -> None:
        self.assertEqual(
            get_deployed_revision({"RENDER_GIT_COMMIT": f" {SHA.upper()} "}),
            SHA,
        )

    def test_optional_explicit_release_sha_for_non_render_host(self) -> None:
        self.assertEqual(get_deployed_revision({"APP_RELEASE_SHA": SHA}), SHA)

    def test_duplicate_consistent_sources_are_accepted(self) -> None:
        self.assertEqual(
            get_deployed_revision({"RENDER_GIT_COMMIT": SHA, "APP_RELEASE_SHA": SHA.upper()}),
            SHA,
        )

    def test_missing_invalid_short_and_conflicting_sources_fail_closed(self) -> None:
        cases = (
            {},
            {"RENDER_GIT_COMMIT": "short"},
            {"APP_RELEASE_SHA": " "},
            {"APP_RELEASE_SHA": "x" * 40},
            {"RENDER_GIT_COMMIT": SHA, "APP_RELEASE_SHA": OTHER_SHA},
            {"RENDER_GIT_COMMIT": "bad", "APP_RELEASE_SHA": SHA},
        )
        for case in cases:
            with self.subTest(case=case):
                self.assertIsNone(get_deployed_revision(case))

    def test_revision_endpoint_returns_only_public_commit_identity(self) -> None:
        with patch.dict(os.environ, {"RENDER_GIT_COMMIT": SHA}, clear=True):
            response = self.client.get("/health/revision/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "known", "revision": SHA})
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertNotIn("RENDER", response.content.decode())

    def test_revision_endpoint_fails_closed_without_runtime_metadata(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            response = self.client.get("/health/revision/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "unknown", "revision": None})

    def test_revision_endpoint_supports_head_and_rejects_post(self) -> None:
        with patch.dict(os.environ, {"APP_RELEASE_SHA": SHA}, clear=True):
            response = self.client.head("/health/revision/")
            rejected = self.client.post("/health/revision/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"")
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(rejected.status_code, 405)
