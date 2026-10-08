from __future__ import annotations

import json
from io import BytesIO

from django.test import SimpleTestCase

from scripts.check_deployment_revision import (
    RejectRedirects,
    RevisionCheckError,
    check_revision,
    validate_url,
)

SHA = "371681ccfc5d0fea4a00fbfd59455242cddb1919"
OTHER_SHA = "a" * 40
URL = "https://example.test/health/revision/"


class _Response(BytesIO):
    status = 200

    def __init__(self, payload: bytes, content_type: str = "application/json"):
        super().__init__(payload)
        self.headers = {"Content-Type": content_type}


class _Opener:
    def __init__(self, payload: bytes, content_type: str = "application/json"):
        self.payload = payload
        self.content_type = content_type
        self.requested_url = None

    def open(self, request, *, timeout):
        assert timeout == 5
        assert request.get_header("Accept") == "application/json"
        self.requested_url = request.full_url
        return _Response(self.payload, self.content_type)


def _json_response(*, status: str = "known", revision: str | None = SHA) -> bytes:
    return json.dumps({"status": status, "revision": revision}).encode("utf-8")


class DeploymentRevisionCliTests(SimpleTestCase):
    def test_exact_revision_succeeds(self) -> None:
        opener = _Opener(_json_response())
        self.assertEqual(check_revision(URL, SHA, opener=opener), SHA)
        self.assertEqual(opener.requested_url, URL)

    def test_uppercase_hex_sha_is_equivalent_to_lowercase(self) -> None:
        self.assertEqual(check_revision(URL, SHA.upper(), opener=_Opener(_json_response())), SHA)
        self.assertEqual(
            check_revision(URL, SHA, opener=_Opener(_json_response(revision=SHA.upper()))),
            SHA,
        )

    def test_missing_revision_is_not_a_passing_release(self) -> None:
        for payload in (
            _json_response(status="unknown", revision=None),
            _json_response(revision="x"),
        ):
            with self.subTest(payload=payload):
                with self.assertRaisesRegex(RevisionCheckError, "revision_unknown"):
                    check_revision(URL, SHA, opener=_Opener(payload))

    def test_revision_mismatch_fails_closed(self) -> None:
        with self.assertRaisesRegex(RevisionCheckError, "revision_mismatch"):
            check_revision(URL, SHA, opener=_Opener(_json_response(revision=OTHER_SHA)))

    def test_malformed_or_oversized_response_is_rejected(self) -> None:
        for body, content_type in (
            (b"<html>not a revision</html>", "text/html"),
            (b"{invalid", "application/json"),
            (b" " * 4097, "application/json"),
            (b"[]", "application/json"),
        ):
            with self.subTest(body=body[:20]):
                with self.assertRaisesRegex(RevisionCheckError, "invalid_response"):
                    check_revision(URL, SHA, opener=_Opener(body, content_type))

    def test_unknown_expected_sha_is_rejected_before_network(self) -> None:
        with self.assertRaisesRegex(RevisionCheckError, "invalid_expected_sha"):
            check_revision(URL, "abc", opener=_Opener(_json_response()))

    def test_only_exact_https_endpoint_or_loopback_http_is_allowed(self) -> None:
        validate_url("http://127.0.0.1:8000/health/revision/")
        validate_url("http://[::1]:8000/health/revision/")
        for url in (
            "http://example.test/health/revision/",
            "https://u:p@example.test/health/revision/",
            "https://example.test/health/revision/?secret=1",
            "https://example.test/health/revision/#something",
            "https://example.test/health/ready/",
            "file:///etc/passwd",
            "https://example.test:invalid/health/revision/",
        ):
            with self.subTest(url=url):
                with self.assertRaisesRegex(RevisionCheckError, "invalid_endpoint_url"):
                    validate_url(url)

    def test_transport_refuses_redirects(self) -> None:
        handler = RejectRedirects()
        self.assertIsNone(
            handler.redirect_request(None, None, 302, "found", {}, "https://elsewhere.test/")
        )
