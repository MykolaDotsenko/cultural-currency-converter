from __future__ import annotations

import logging
from contextlib import suppress
from uuid import uuid4

from django.conf import settings
from django.core.cache import cache
from django.db import DatabaseError, connection
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_safe

from apps.common.release_identity import get_deployed_revision

logger = logging.getLogger("cultural_currency.health")


@require_safe
def health_live(request: HttpRequest) -> JsonResponse:
    """Report process liveness without touching database or external services."""

    return JsonResponse({"status": "ok"})


@require_safe
def health_revision(request: HttpRequest) -> JsonResponse:
    """Expose only the full deployed Git SHA, never runtime configuration."""

    revision = get_deployed_revision()
    response = JsonResponse({"status": "known" if revision else "unknown", "revision": revision})
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


def _shared_cache_available() -> bool:
    marker = uuid4().hex
    key = f"health:readiness:{marker}"
    try:
        cache.set(key, marker, timeout=5)
        return cache.get(key) == marker
    except Exception:
        return False
    finally:
        with suppress(Exception):
            cache.delete(key)


@require_safe
def health_ready(request: HttpRequest) -> JsonResponse:
    """Report hard readiness separately from optional degraded dependencies."""

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except DatabaseError:
        logger.warning(
            "readiness_failed",
            extra={
                "dependency": "database",
                "outcome": "unavailable",
                "error_code": "database_unavailable",
            },
        )
        return JsonResponse(
            {
                "status": "unavailable",
                "checks": {"database": "unavailable"},
            },
            status=503,
        )

    checks = {"database": "ok"}
    if settings.CACHE_CONFIG.shared:
        if _shared_cache_available():
            checks["cache"] = "ok"
        else:
            checks["cache"] = "unavailable"
            logger.warning(
                "readiness_degraded",
                extra={
                    "dependency": "cache",
                    "outcome": "degraded",
                    "error_code": "cache_unavailable",
                },
            )
            return JsonResponse(
                {
                    "status": "degraded",
                    "checks": checks,
                }
            )

    return JsonResponse(
        {
            "status": "ok",
            "checks": checks,
        }
    )
