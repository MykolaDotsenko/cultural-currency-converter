"""Cache/throttle boundary for optional, explicitly requested Open Prices context."""

from __future__ import annotations

from django.core.cache import cache
from django.utils import timezone

from integrations.price_data import (
    OpenPricesClient,
    OpenPricesRateLimited,
    OpenPricesSourceError,
    PublicPriceObservation,
)
from integrations.product_data import canonical_open_food_facts_barcode

_CACHE_VERSION = "v1"
_POSITIVE_TTL_SECONDS = 12 * 60 * 60
_EMPTY_TTL_SECONDS = 60 * 60
_MAX_UPSTREAM_LOOKUPS_PER_MINUTE = 6


def _cache_key(barcode: str) -> str:
    return f"shopping:open-prices:{_CACHE_VERSION}:{barcode}"


def _limit_key() -> str:
    return f"shopping:open-prices:limit:{timezone.now().strftime('%Y%m%d%H%M')}"


def lookup_public_price_observations(
    barcode: str,
    *,
    client: OpenPricesClient | None = None,
) -> tuple[PublicPriceObservation, ...]:
    normalized = canonical_open_food_facts_barcode(barcode)
    key = _cache_key(normalized)
    try:
        cached = cache.get(key)
    except Exception as exc:
        raise OpenPricesSourceError("Open Prices cache is unavailable.") from exc
    if isinstance(cached, tuple) and all(
        isinstance(item, PublicPriceObservation) and item.product_code == normalized
        for item in cached
    ):
        return cached

    try:
        limit_key = _limit_key()
        count = 1 if cache.add(limit_key, 1, timeout=90) else cache.incr(limit_key)
        if count > _MAX_UPSTREAM_LOOKUPS_PER_MINUTE:
            raise OpenPricesRateLimited("Open Prices request budget is temporarily exhausted.")
        result = (client or OpenPricesClient()).fetch_prices(normalized)
        cache.set(
            key,
            result,
            timeout=_POSITIVE_TTL_SECONDS if result else _EMPTY_TTL_SECONDS,
        )
    except OpenPricesRateLimited:
        raise
    except OpenPricesSourceError:
        raise
    except Exception as exc:
        raise OpenPricesSourceError("Open Prices cache or source is unavailable.") from exc
    return result
