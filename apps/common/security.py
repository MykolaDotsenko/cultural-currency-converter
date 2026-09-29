from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlsplit

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

logger = logging.getLogger("cultural_currency.security")

_CSP_REPORT_PATH = "/security/csp-report/"
_MAX_CSP_REPORT_BYTES = 32 * 1024
_ACCEPTED_REPORT_CONTENT_TYPES = frozenset(
    {
        "application/csp-report",
        "application/json",
        "application/reports+json",
    }
)

_PUBLIC_DIRECTIVES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("default-src", ("'self'",)),
    ("base-uri", ("'none'",)),
    ("object-src", ("'none'",)),
    ("frame-ancestors", ("'none'",)),
    ("frame-src", ("'none'",)),
    ("form-action", ("'self'",)),
    ("script-src", ("'self'",)),
    ("script-src-attr", ("'none'",)),
    ("style-src", ("'self'",)),
    ("style-src-attr", ("'unsafe-inline'",)),
    ("img-src", ("'self'",)),
    ("font-src", ("'self'",)),
    ("connect-src", ("'self'",)),
    ("media-src", ("'self'",)),
    ("worker-src", ("'self'",)),
    ("manifest-src", ("'self'",)),
    ("report-uri", (_CSP_REPORT_PATH,)),
)

_ADMIN_DIRECTIVES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("default-src", ("'self'",)),
    ("base-uri", ("'self'",)),
    ("object-src", ("'none'",)),
    ("frame-ancestors", ("'none'",)),
    ("frame-src", ("'none'",)),
    ("form-action", ("'self'",)),
    ("script-src", ("'self'", "'unsafe-inline'")),
    ("script-src-attr", ("'unsafe-inline'",)),
    ("style-src", ("'self'", "'unsafe-inline'")),
    ("style-src-attr", ("'unsafe-inline'",)),
    ("img-src", ("'self'", "data:")),
    ("font-src", ("'self'",)),
    ("connect-src", ("'self'",)),
    ("media-src", ("'self'",)),
    ("worker-src", ("'self'",)),
    ("manifest-src", ("'self'",)),
    ("report-uri", (_CSP_REPORT_PATH,)),
)


def _serialize_policy(directives: Sequence[tuple[str, Sequence[str]]]) -> str:
    return "; ".join(
        " ".join((directive, *values)) if values else directive for directive, values in directives
    )


PUBLIC_CONTENT_SECURITY_POLICY = _serialize_policy(_PUBLIC_DIRECTIVES)
ADMIN_CONTENT_SECURITY_POLICY = _serialize_policy(_ADMIN_DIRECTIVES)


def _with_media_image_source(
    directives: Sequence[tuple[str, Sequence[str]]],
    media_origin: str | None,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    if not media_origin:
        return tuple((directive, tuple(values)) for directive, values in directives)

    expanded: list[tuple[str, tuple[str, ...]]] = []
    for directive, values in directives:
        normalized = tuple(values)
        if directive == "img-src" and media_origin not in normalized:
            normalized = (*normalized, media_origin)
        expanded.append((directive, normalized))
    return tuple(expanded)


def _policy_for_request(request: HttpRequest) -> str:
    directives = _ADMIN_DIRECTIVES if _is_admin_request(request) else _PUBLIC_DIRECTIVES
    return _serialize_policy(
        _with_media_image_source(
            directives,
            getattr(settings, "MEDIA_STORAGE_PUBLIC_ORIGIN", None),
        )
    )


def _is_admin_request(request: HttpRequest) -> bool:
    resolver_match = getattr(request, "resolver_match", None)
    return bool(resolver_match and resolver_match.namespace == "admin")


class ContentSecurityPolicyMiddleware:
    """Attach the configured CSP without weakening the public application surface."""

    def __init__(self, get_response) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        header_name = settings.CONTENT_SECURITY_POLICY_HEADER
        if not header_name:
            return response

        policy = _policy_for_request(request)
        response.headers.pop("Content-Security-Policy", None)
        response.headers.pop("Content-Security-Policy-Report-Only", None)
        response[header_name] = policy
        return response


def _content_length(request: HttpRequest) -> int | None:
    raw = request.META.get("CONTENT_LENGTH")
    if not raw:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def _report_body(payload: Any) -> Mapping[str, Any] | None:
    if isinstance(payload, dict):
        legacy = payload.get("csp-report")
        if isinstance(legacy, dict):
            return legacy

        body = payload.get("body")
        if isinstance(body, dict):
            return body

        return payload

    if isinstance(payload, list) and payload:
        first = payload[0]
        if isinstance(first, dict):
            body = first.get("body")
            if isinstance(body, dict):
                return body

    return None


def _reported_resource(value: Any) -> str:
    if not isinstance(value, str) or not value:
        return "unknown"

    normalized = value.strip()
    if normalized in {"inline", "eval", "self", "none"}:
        return normalized
    if normalized.startswith("data:"):
        return "data:"
    if normalized.startswith("blob:"):
        return "blob:"

    try:
        parsed = urlsplit(normalized)
        port = parsed.port
    except ValueError:
        return "redacted"

    if parsed.scheme in {"http", "https"} and parsed.hostname:
        default_port = 443 if parsed.scheme == "https" else 80
        suffix = f":{port}" if port and port != default_port else ""
        return f"{parsed.scheme}://{parsed.hostname}{suffix}"
    if parsed.scheme:
        return f"{parsed.scheme}:"
    return "relative-or-redacted"


@csrf_exempt
@require_POST
def csp_report(request: HttpRequest) -> HttpResponse:
    """Accept bounded browser CSP reports without persisting browsing/query details."""

    declared_length = _content_length(request)
    if declared_length is not None and declared_length > _MAX_CSP_REPORT_BYTES:
        return HttpResponse(status=413)

    content_type = (request.content_type or "").lower()
    if content_type not in _ACCEPTED_REPORT_CONTENT_TYPES:
        return HttpResponse(status=415)

    body = request.body
    if len(body) > _MAX_CSP_REPORT_BYTES:
        return HttpResponse(status=413)

    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return HttpResponse(status=400)

    report = _report_body(payload)
    if report is not None:
        directive = report.get("effective-directive") or report.get("effectiveDirective")
        if not isinstance(directive, str) or not directive:
            directive = report.get("violated-directive") or "unknown"
        disposition = report.get("disposition")
        if disposition not in {"enforce", "report"}:
            disposition = "unknown"
        blocked = report.get("blocked-uri")
        if blocked is None:
            blocked = report.get("blockedURL")

        logger.warning(
            "content_security_policy_violation",
            extra={
                "csp_directive": str(directive)[:80],
                "csp_disposition": disposition,
                "csp_blocked_resource": _reported_resource(blocked),
            },
        )

    return HttpResponse(status=204)
