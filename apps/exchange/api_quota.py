"""Per-origin abuse budget for public API conversions.

The quota protects provider-backed work only. It uses the socket peer unless
explicitly configured trusted proxy ranges verify the forwarded chain, and
stores only an HMAC identifier in the shared cache.
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

from config.api_security import ProxyNetwork

logger = logging.getLogger("cultural_currency.security")

_MAX_CONVERSIONS_PER_MINUTE = 60
_BUCKET_TTL_SECONDS = 90


class ConversionQuotaUnavailable(Exception):
    """The shared abuse guard is unavailable; do not call the FX provider."""


@dataclass(frozen=True, slots=True)
class ConversionQuota:
    allowed: bool
    retry_after: int


def _is_trusted(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
    networks: tuple[ProxyNetwork, ...],
) -> bool:
    return any(address in network for network in networks)


def _client_address(request: HttpRequest) -> str:
    """Identify the first untrusted hop from the *right* of a verified chain.

    A caller may prepend spoofed values. Only the immediately preceding hop
    supplied by an explicitly trusted reverse proxy can be consumed.
    Invalid/overlarge headers are ignored, preserving the server peer quota.
    """
    remote_addr = request.META.get("REMOTE_ADDR")
    try:
        peer = ipaddress.ip_address(str(remote_addr))
    except ValueError:
        return "unknown"

    networks: tuple[ProxyNetwork, ...] = getattr(
        settings, "API_TRUSTED_PROXY_NETWORKS", ()
    )
    if not networks or not _is_trusted(peer, networks):
        return peer.compressed

    header = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if not isinstance(header, str) or not header or len(header) > 1024:
        return peer.compressed
    hops = header.split(",")
    if len(hops) > 16 or any(not hop.strip() for hop in hops):
        return peer.compressed

    candidate = peer
    for raw_hop in reversed(hops):
        if not _is_trusted(candidate, networks):
            break
        try:
            candidate = ipaddress.ip_address(raw_hop.strip())
        except ValueError:
            return peer.compressed
    return candidate.compressed


def _origin_token(request: HttpRequest) -> str:
    origin = _client_address(request)

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
        count = 1 if cache.add(key, 1, timeout=_BUCKET_TTL_SECONDS) else cache.incr(key)
    except Exception as exc:
        logger.warning("api_conversion_quota_unavailable", exc_info=True)
        raise ConversionQuotaUnavailable("Shared conversion quota is unavailable.") from exc

    return ConversionQuota(
        allowed=count <= _MAX_CONVERSIONS_PER_MINUTE,
        retry_after=60 - (timestamp % 60),
    )
