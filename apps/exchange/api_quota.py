"""Per-origin abuse budget for public API conversions.

The quota protects provider-backed work only. It uses the server-provided peer
address, never an untrusted X-Forwarded-For header, and stores only an HMAC
identifier in the shared cache.
"""

from __future__ import annotations

import hmac
import ipaddress
import logging
from dataclasses import dataclass
from hashlib import sha256

from django.conf import settings
from django.core.cache import cache
from django.http import HttpRequest
from django.utils import timezone

logger = logging.getLogger("cultural_currency.security")

_MAX_CONVERSIONS_PER_MINUTE = 60
_BUCKET_TTL_SECONDS = 90


class ConversionQuotaUnavailable(Exception):
    """The shared abuse guard is unavailable; do not call the FX provider."""


@dataclass(frozen=True, slots=True)
class ConversionQuota:
    allowed: bool
    retry_after: int


def _origin_token(request: HttpRequest) -> str:
    # REMOTE_ADDR is supplied by the application server. Never trust a
    # caller-controlled forwarding header without a configured proxy chain.
    remote_addr = request.META.get("REMOTE_ADDR")
    try:
        origin = ipaddress.ip_address(str(remote_addr)).compressed
    except ValueError:
        origin = "unknown"

    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        origin.encode("ascii"),
        sha256,
    ).hexdigest()[:32]


def consume_conversion_quota(request: HttpRequest) -> ConversionQuota:
    """Atomically count provider-backed conversions in a fixed UTC minute.

    Redis is mandatory in deployed environments. If the cache cannot enforce
    the quota (including an evicted key between add/incr), fail closed rather
    than sending unlimited requests upstream.
    """

    timestamp = int(timezone.now().timestamp())
    window = timestamp // 60
    key = f"api:v1:conversion-quota:{window}:{_origin_token(request)}"

    try:
        if cache.add(key, 1, timeout=_BUCKET_TTL_SECONDS):
            count = 1
        else:
            count = cache.incr(key)
    except Exception as exc:
        logger.warning("api_conversion_quota_unavailable", exc_info=True)
        raise ConversionQuotaUnavailable("Shared conversion quota is unavailable.") from exc

    return ConversionQuota(
        allowed=count <= _MAX_CONVERSIONS_PER_MINUTE,
        retry_after=60 - (timestamp % 60),
    )
