"""Read-only live release smoke contract with fake HTTP responses."""

from __future__ import annotations

import json
from io import BytesIO

from django.test import SimpleTestCase

from scripts.check_deployment_revision import RevisionCheckError
from scripts.check_release_smoke import check_release_smoke

SHA = "371681ccfc5d0fea4a00fbfd59455242cddb1919"
URL = "https://example.test/health/revision/"


class _Response(BytesIO):
    status = 200

    def __init__(self, data: bytes, *, content_type: str = "application/json") -> None:
        super().__init__(data)
        self.headers = {"Content-Type": content_type}


class _Opener:
    def __init__(self, responses: dict[str, object]) -> None:
        self.responses = responses
        self.paths: list[str] = []

    def open(self, request, *, timeout: int):
        assert timeout == 5
        assert request.get_header("Accept") == "application/json"
        path = request.full_url.rsplit("/", 3)[-2]
        self.paths.append(path)
        value = self.responses[path]
        if isinstance(value, Exception):
            raise value
        if isinstance(value, tuple):
            return _Response(value[0], content_type=value[1])
        return _Response(json.dumps(value).encode("utf-8"))


def _opener(*, cache: str | None = "ok") -> _Opener:
    checks = {"database": "ok"}
    if cache is not None:
        checks["cache"] = cache
    return _Opener(
        {
            "revision": {"status": "known", "revision": SHA},
            "live": {"status": "ok"},
            "ready": {"status": "ok", "checks": checks},
        }
    )


class LiveReleaseSmokeTests(SimpleTestCase):
    def test_exact_sha_liveness_and_database_ready(self) -> None:
        opener = _opener()
        self.assertEqual(
            check_release_smoke(URL, SHA, require_shared_cache=True, opener=opener),
            {
                "revision": SHA,
                "liveness": "ok",
                "readiness": "ok",
                "database": "ok",
                "cache": "ok",
            },
        )
        self.assertEqual(opener.paths, ["revision", "live", "ready"])

    def test_shared_cache_is_optional_but_unknown_when_not_checked(self) -> None:
        result = check_release_smoke(URL, SHA, opener=_opener(cache=None))
        self.assertEqual(result["cache"], "not_checked")
        with self.assertRaisesRegex(RevisionCheckError, "shared_cache_unverified"):
            check_release_smoke(
                URL, SHA, require_shared_cache=True, opener=_opener(cache=None)
            )

    def test_sha_mismatch_stops_before_health_calls(self) -> None:
        opener = _opener()
        with self.assertRaisesRegex(RevisionCheckError, "revision_mismatch"):
            check_release_smoke(URL, "a" * 40, opener=opener)
        self.assertEqual(opener.paths, ["revision"])

    def test_unready_database_does_not_pass_even_if_liveness_ok(self) -> None:
        opener = _opener()
        opener.responses["ready"] = {
            "status": "unavailable",
            "checks": {"database": "unavailable"},
        }
        with self.assertRaisesRegex(RevisionCheckError, "readiness_failed"):
            check_release_smoke(URL, SHA, opener=opener)

    def test_degraded_cache_does_not_pass_as_strict_readiness(self) -> None:
        opener = _opener(cache="unavailable")
        opener.responses["ready"] = {
            "status": "degraded",
            "checks": {"database": "ok", "cache": "unavailable"},
        }
        with self.assertRaisesRegex(RevisionCheckError, "readiness_failed"):
            check_release_smoke(URL, SHA, opener=opener)

    def test_missing_status_and_non_json_fail_closed(self) -> None:
        cases = [
            ("live", {"status": "unknown"}, "liveness_failed"),
            ("ready", {"status": "ok"}, "readiness_failed"),
            ("live", (b"<html>secret</html>", "text/html"), "health_invalid_response"),
            ("ready", (b" " * 4097, "application/json"), "health_invalid_response"),
            ("ready", (b"[]", "application/json"), "health_invalid_response"),
        ]
        for path, payload, error in cases:
            with self.subTest(path=path, error=error):
                opener = _opener()
                opener.responses[path] = payload
                with self.assertRaisesRegex(RevisionCheckError, error):
                    check_release_smoke(URL, SHA, opener=opener)

    def test_non_https_remote_url_rejected_before_network(self) -> None:
        opener = _opener()
        with self.assertRaisesRegex(RevisionCheckError, "invalid_endpoint_url"):
            check_release_smoke(
                "http://evil.example.test/health/revision/", SHA, opener=opener
            )
        self.assertEqual(opener.paths, [])
