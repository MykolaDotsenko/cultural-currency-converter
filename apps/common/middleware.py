from __future__ import annotations

import logging
from time import perf_counter
from typing import Protocol

from django.http import HttpRequest, HttpResponse

from .observability import bind_request_id, normalize_request_id, reset_request_id

logger = logging.getLogger("cultural_currency.access")


def safe_access_path(path: str) -> str:
    """Never log signed verification tokens included in account-confirm URLs."""

    prefix = "/accounts/recovery-email/confirm/"
    if path.startswith(prefix):
        return prefix + "[redacted]/"
    reset_prefix = "/accounts/password/reset/"
    if path.startswith(reset_prefix):
        suffix = path[len(reset_prefix) :]
        if suffix and suffix not in {"sent/", "complete/"}:
            return reset_prefix + "[redacted]/"
    return path


class GetResponse(Protocol):
    def __call__(self, request: HttpRequest) -> HttpResponse: ...


class RequestContextMiddleware:
    """Correlate requests and emit one privacy-bounded structured access event."""

    def __init__(self, get_response: GetResponse) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        request_id = normalize_request_id(request.headers.get("X-Request-ID"))
        request.request_id = request_id
        token = bind_request_id(request_id)
        started_at = perf_counter()

        try:
            response = self.get_response(request)
            duration_ms = round((perf_counter() - started_at) * 1000, 3)
            response["X-Request-ID"] = request_id

            resolver_match = getattr(request, "resolver_match", None)
            logger.info(
                "http_request",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": safe_access_path(request.path),
                    "route": resolver_match.view_name if resolver_match else None,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                },
            )
            return response
        except Exception:
            duration_ms = round((perf_counter() - started_at) * 1000, 3)
            logger.exception(
                "http_request_failed",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": safe_access_path(request.path),
                    "route": None,
                    "duration_ms": duration_ms,
                    "error_code": "unhandled_exception",
                },
            )
            raise
        finally:
            reset_request_id(token)
