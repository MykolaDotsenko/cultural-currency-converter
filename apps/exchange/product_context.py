from __future__ import annotations

from datetime import datetime
from typing import Any

from django.core import signing
from django.core.cache import cache
from django.utils import timezone

from integrations.product_data import (
    OpenFoodFactsClient,
    ProductIdentity,
    ProductNotFound,
    ProductSourceRateLimited,
    canonical_open_food_facts_barcode,
    normalize_barcode,
)

_CACHE_VERSION = "v1"
_POSITIVE_TTL_SECONDS = 7 * 24 * 60 * 60
_NEGATIVE_TTL_SECONDS = 60 * 60
_LOCAL_LOOKUP_LIMIT_PER_MINUTE = 12
_TOKEN_SALT = "exchange.product-context:v1"
_TOKEN_MAX_AGE_SECONDS = 24 * 60 * 60
_MAX_TOKEN_LENGTH = 4096


class ProductContextTokenError(ValueError):
    pass


def _cache_key(barcode: str) -> str:
    return f"product-context:{_CACHE_VERSION}:{barcode}"


def _rate_limit_key() -> str:
    return f"product-context:off-limit:{timezone.now().strftime('%Y%m%d%H%M')}"


def _identity_payload(identity: ProductIdentity) -> dict[str, object]:
    return {
        "barcode": identity.barcode,
        "product_name": identity.product_name,
        "brands": list(identity.brands),
        "quantity": identity.quantity,
        "categories": list(identity.categories),
        "source_name": identity.source_name,
        "source_url": identity.source_url,
        "retrieved_at": identity.retrieved_at.isoformat(),
    }


def _identity_from_payload(payload: Any) -> ProductIdentity:
    if not isinstance(payload, dict):
        raise ProductContextTokenError("Product context payload is invalid.")
    expected = {
        "barcode",
        "product_name",
        "brands",
        "quantity",
        "categories",
        "source_name",
        "source_url",
        "retrieved_at",
    }
    if set(payload) != expected:
        raise ProductContextTokenError("Product context fields are invalid.")

    try:
        barcode = normalize_barcode(str(payload["barcode"]))
        retrieved_at = datetime.fromisoformat(str(payload["retrieved_at"]))
    except (TypeError, ValueError) as exc:
        raise ProductContextTokenError("Product context identity is invalid.") from exc

    if not timezone.is_aware(retrieved_at):
        raise ProductContextTokenError("Product context retrieval time must be timezone-aware.")

    def short_text(key: str, limit: int) -> str:
        raw = payload[key]
        if not isinstance(raw, str):
            raise ProductContextTokenError(f"Product context {key} is invalid.")
        value = " ".join(raw.split())
        if len(value) > limit:
            raise ProductContextTokenError(f"Product context {key} is too long.")
        return value

    def text_list(key: str, *, max_items: int, item_limit: int) -> tuple[str, ...]:
        raw = payload[key]
        if not isinstance(raw, list) or len(raw) > max_items:
            raise ProductContextTokenError(f"Product context {key} is invalid.")
        result: list[str] = []
        for item in raw:
            if not isinstance(item, str):
                raise ProductContextTokenError(f"Product context {key} is invalid.")
            value = " ".join(item.split())
            if not value or len(value) > item_limit:
                raise ProductContextTokenError(f"Product context {key} is invalid.")
            result.append(value)
        return tuple(result)

    product_name = short_text("product_name", 240)
    if not product_name:
        raise ProductContextTokenError("Product context name is missing.")

    source_name = short_text("source_name", 120)
    source_url = short_text("source_url", 700)
    if (
        source_name != "Open Food Facts"
        or source_url != f"https://world.openfoodfacts.org/product/{barcode}"
    ):
        raise ProductContextTokenError("Product context provenance is invalid.")

    return ProductIdentity(
        barcode=barcode,
        product_name=product_name,
        brands=text_list("brands", max_items=6, item_limit=120),
        quantity=short_text("quantity", 120),
        categories=text_list("categories", max_items=6, item_limit=160),
        source_name=source_name,
        source_url=source_url,
        retrieved_at=retrieved_at,
    )


def _consume_lookup_budget() -> None:
    key = _rate_limit_key()
    cache.add(key, 0, timeout=90)
    try:
        count = cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout=90)
        count = 1
    if count > _LOCAL_LOOKUP_LIMIT_PER_MINUTE:
        raise ProductSourceRateLimited(
            "Product lookup is temporarily busy. Please retry in a moment."
        )


def lookup_product_identity(
    barcode: str,
    *,
    client: OpenFoodFactsClient | None = None,
) -> ProductIdentity:
    # One product identity for UPC/EAN aliases across web Shopping and API v1.
    # Reject all-zero identifiers before cache, throttle or provider access.
    normalized = canonical_open_food_facts_barcode(barcode)
    cached = cache.get(_cache_key(normalized))
    if isinstance(cached, dict):
        if cached.get("found") is False:
            raise ProductNotFound("Product is not available in Open Food Facts.")
        payload = cached.get("product")
        try:
            return _identity_from_payload(payload)
        except ProductContextTokenError:
            cache.delete(_cache_key(normalized))

    _consume_lookup_budget()
    product = (client or OpenFoodFactsClient()).fetch_product(normalized)
    cache.set(
        _cache_key(normalized),
        {"found": True, "product": _identity_payload(product)},
        timeout=_POSITIVE_TTL_SECONDS,
    )
    return product


def remember_product_not_found(barcode: str) -> None:
    normalized = canonical_open_food_facts_barcode(barcode)
    cache.set(
        _cache_key(normalized),
        {"found": False},
        timeout=_NEGATIVE_TTL_SECONDS,
    )


def lookup_product_identity_cached(
    barcode: str,
    *,
    client: OpenFoodFactsClient | None = None,
) -> ProductIdentity:
    try:
        return lookup_product_identity(barcode, client=client)
    except ProductNotFound:
        remember_product_not_found(barcode)
        raise


def build_product_context_token(identity: ProductIdentity) -> str:
    return signing.dumps(
        {"v": 1, "product": _identity_payload(identity)},
        salt=_TOKEN_SALT,
        compress=True,
    )


def load_product_context_token(
    token: str,
    *,
    max_age: int = _TOKEN_MAX_AGE_SECONDS,
) -> ProductIdentity:
    if not isinstance(token, str) or not token or len(token) > _MAX_TOKEN_LENGTH:
        raise ProductContextTokenError("Product context token is invalid.")
    try:
        payload = signing.loads(token, salt=_TOKEN_SALT, max_age=max_age)
    except signing.BadSignature as exc:
        raise ProductContextTokenError("Product context token is invalid or expired.") from exc
    if not isinstance(payload, dict) or payload.get("v") != 1 or set(payload) != {"v", "product"}:
        raise ProductContextTokenError("Product context token envelope is invalid.")
    return _identity_from_payload(payload["product"])
