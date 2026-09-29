from __future__ import annotations

import json
import logging

import pytest
from django.http import HttpResponse
from django.test import Client, RequestFactory, override_settings

from apps.common.security import (
    ADMIN_CONTENT_SECURITY_POLICY,
    PUBLIC_CONTENT_SECURITY_POLICY,
    ContentSecurityPolicyMiddleware,
    _reported_resource,
)


@pytest.mark.django_db
def test_public_response_enforces_strict_script_and_embedding_policy(client: Client) -> None:
    response = client.get("/health/live/")

    policy = response["Content-Security-Policy"]
    assert policy == PUBLIC_CONTENT_SECURITY_POLICY
    assert "script-src 'self'" in policy
    assert "script-src-attr 'none'" in policy
    assert "'unsafe-eval'" not in policy
    assert "object-src 'none'" in policy
    assert "frame-ancestors 'none'" in policy
    assert "form-action 'self'" in policy
    assert "style-src-attr 'unsafe-inline'" in policy
    assert "report-uri /security/csp-report/" in policy


@pytest.mark.django_db
def test_admin_uses_compatibility_policy_without_weakening_public_policy(client: Client) -> None:
    response = client.get("/admin/login/")

    assert response["Content-Security-Policy"] == ADMIN_CONTENT_SECURITY_POLICY
    assert "script-src 'self' 'unsafe-inline'" in response["Content-Security-Policy"]
    assert "'unsafe-inline'" not in PUBLIC_CONTENT_SECURITY_POLICY.split("script-src-attr", 1)[0]


def test_validated_media_origin_is_added_only_to_image_policy() -> None:
    request = RequestFactory().get("/health/live/")
    request.resolver_match = None

    with override_settings(
        CONTENT_SECURITY_POLICY_HEADER="Content-Security-Policy",
        MEDIA_STORAGE_PUBLIC_ORIGIN="https://media.example.test",
    ):
        response = ContentSecurityPolicyMiddleware(lambda _request: HttpResponse("ok"))(request)

    policy = response["Content-Security-Policy"]
    assert "img-src 'self' https://media.example.test" in policy
    assert "script-src 'self' https://media.example.test" not in policy
    assert "connect-src 'self' https://media.example.test" not in policy


def test_report_only_mode_uses_report_only_header() -> None:
    request = RequestFactory().get("/health/live/")
    request.resolver_match = None

    @override_settings(
        CONTENT_SECURITY_POLICY_HEADER="Content-Security-Policy-Report-Only",
    )
    def run():
        middleware = ContentSecurityPolicyMiddleware(lambda _request: HttpResponse("ok"))
        return middleware(request)

    response = run()

    assert "Content-Security-Policy" not in response
    assert response["Content-Security-Policy-Report-Only"] == PUBLIC_CONTENT_SECURITY_POLICY


def test_enabled_middleware_replaces_weaker_view_policy() -> None:
    request = RequestFactory().get("/health/live/")
    request.resolver_match = None

    def weak_response(_request):
        response = HttpResponse("ok")
        response["Content-Security-Policy"] = "default-src * 'unsafe-inline' 'unsafe-eval'"
        response["Content-Security-Policy-Report-Only"] = "default-src *"
        return response

    with override_settings(CONTENT_SECURITY_POLICY_HEADER="Content-Security-Policy"):
        response = ContentSecurityPolicyMiddleware(weak_response)(request)

    assert response["Content-Security-Policy"] == PUBLIC_CONTENT_SECURITY_POLICY
    assert "Content-Security-Policy-Report-Only" not in response


def test_disabled_mode_adds_no_csp_header() -> None:
    request = RequestFactory().get("/health/live/")
    request.resolver_match = None

    @override_settings(CONTENT_SECURITY_POLICY_HEADER=None)
    def run():
        middleware = ContentSecurityPolicyMiddleware(lambda _request: HttpResponse("ok"))
        return middleware(request)

    response = run()

    assert "Content-Security-Policy" not in response
    assert "Content-Security-Policy-Report-Only" not in response


@pytest.mark.django_db
def test_csp_report_endpoint_accepts_legacy_report_without_query_logging(
    client: Client,
    caplog: pytest.LogCaptureFixture,
) -> None:
    payload = {
        "csp-report": {
            "document-uri": "https://app.example.test/?amount=100&secret=do-not-log",
            "effective-directive": "script-src-elem",
            "blocked-uri": "https://evil.example/path?token=secret",
            "disposition": "enforce",
        }
    }

    with caplog.at_level(logging.WARNING, logger="cultural_currency.security"):
        response = client.post(
            "/security/csp-report/",
            data=json.dumps(payload),
            content_type="application/csp-report",
        )

    assert response.status_code == 204
    record = next(
        record
        for record in caplog.records
        if record.getMessage() == "content_security_policy_violation"
    )
    assert record.csp_directive == "script-src-elem"
    assert record.csp_disposition == "enforce"
    assert record.csp_blocked_resource == "https://evil.example"
    assert "secret" not in str(record.__dict__)


@pytest.mark.django_db
def test_csp_report_endpoint_rejects_malformed_or_unbounded_payloads(client: Client) -> None:
    malformed = client.post(
        "/security/csp-report/",
        data="{",
        content_type="application/csp-report",
    )
    unsupported = client.post(
        "/security/csp-report/",
        data="report",
        content_type="text/plain",
    )
    oversized = client.post(
        "/security/csp-report/",
        data=json.dumps({"csp-report": {"sample": "x" * (33 * 1024)}}),
        content_type="application/csp-report",
    )

    assert malformed.status_code == 400
    assert unsupported.status_code == 415
    assert oversized.status_code == 413


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("inline", "inline"),
        ("data:text/plain,secret", "data:"),
        ("blob:https://app.example.test/id", "blob:"),
        ("https://user:secret@evil.example:8443/path?token=secret", "https://evil.example:8443"),
        ("/local/path?secret=1", "relative-or-redacted"),
        ("not a url", "relative-or-redacted"),
    ],
)
def test_reported_resource_is_privacy_bounded(raw: str, expected: str) -> None:
    assert _reported_resource(raw) == expected
