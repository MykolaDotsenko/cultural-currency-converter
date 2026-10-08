from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from django.core.cache import cache

from apps.exchange.product_context import (
    ProductContextTokenError,
    build_product_context_token,
    load_product_context_token,
    lookup_product_identity_cached,
)
from integrations.product_data.base import (
    ProductIdentity,
    ProductNotFound,
    ProductSourceRateLimited,
)


class StubProductClient:
    def __init__(self, *, not_found: bool = False):
        self.not_found = not_found
        self.calls: list[str] = []

    def fetch_product(self, barcode: str) -> ProductIdentity:
        self.calls.append(barcode)
        if self.not_found:
            raise ProductNotFound("missing")
        return ProductIdentity(
            barcode=barcode,
            product_name=f"Product {barcode}",
            brands=("Example Brand",),
            quantity="200 g",
            categories=("Snacks",),
            source_name="Open Food Facts",
            source_url=f"https://world.openfoodfacts.org/product/{barcode}",
            retrieved_at=datetime(2026, 10, 8, 10, tzinfo=UTC),
        )


@pytest.fixture(autouse=True)
def clear_product_cache():
    cache.clear()
    yield
    cache.clear()


def test_product_lookup_reuses_positive_cache_without_second_provider_call():
    client = StubProductClient()

    first = lookup_product_identity_cached("3017624010701", client=client)
    second = lookup_product_identity_cached("3017624010701", client=client)

    assert first == second
    assert client.calls == ["3017624010701"]


def test_product_lookup_negative_cache_avoids_repeated_missing_product_calls():
    client = StubProductClient(not_found=True)

    with pytest.raises(ProductNotFound):
        lookup_product_identity_cached("12345678", client=client)
    with pytest.raises(ProductNotFound):
        lookup_product_identity_cached("12345678", client=client)

    assert client.calls == ["12345678"]


def test_local_product_lookup_budget_stays_below_upstream_limit():
    client = StubProductClient()
    for index in range(12):
        lookup_product_identity_cached(f"1000000{index:02d}", client=client)

    with pytest.raises(ProductSourceRateLimited):
        lookup_product_identity_cached("200000000", client=client)

    assert len(client.calls) == 12


def test_upc_ean_aliases_share_one_positive_cache_and_upstream_lookup():
    client = StubProductClient()
    first = lookup_product_identity_cached("034000470693", client=client)
    second = lookup_product_identity_cached("0034000470693", client=client)

    assert first == second
    assert first.barcode == "0034000470693"
    assert client.calls == ["0034000470693"]


def test_upc_ean_aliases_share_one_negative_cache():
    client = StubProductClient(not_found=True)
    for barcode in ("034000470693", "0034000470693"):
        with pytest.raises(ProductNotFound):
            lookup_product_identity_cached(barcode, client=client)

    assert client.calls == ["0034000470693"]


def test_all_zero_product_identity_rejected_before_cache_or_upstream():
    client = StubProductClient()
    with patch("apps.exchange.product_context._consume_lookup_budget") as throttle:
        with pytest.raises(ValueError, match="all zeroes"):
            lookup_product_identity_cached("00000000", client=client)

    throttle.assert_not_called()
    assert client.calls == []


def test_product_context_token_round_trips_identity_and_rejects_tampering():
    identity = StubProductClient().fetch_product("3017624010701")
    token = build_product_context_token(identity)

    loaded = load_product_context_token(token)

    assert loaded == identity
    with pytest.raises(ProductContextTokenError):
        load_product_context_token(token + "tampered")


def test_product_context_token_rejects_untrusted_provenance():
    identity = ProductIdentity(
        barcode="3017624010701",
        product_name="Product",
        brands=(),
        quantity="",
        categories=(),
        source_name="Somewhere Else",
        source_url="https://example.test/product/3017624010701",
        retrieved_at=datetime(2026, 10, 8, 10, tzinfo=UTC),
    )

    token = build_product_context_token(identity)

    with pytest.raises(ProductContextTokenError, match="provenance"):
        load_product_context_token(token)


def test_signed_product_identity_rejects_mismatched_provenance_url():
    identity = ProductIdentity(
        barcode="3017624010701",
        product_name="Product",
        brands=(),
        quantity="",
        categories=(),
        source_name="Open Food Facts",
        source_url="https://world.openfoodfacts.org/product/3017624010702",
        retrieved_at=datetime(2026, 10, 8, 10, tzinfo=UTC),
    )

    with pytest.raises(ProductContextTokenError, match="provenance"):
        load_product_context_token(build_product_context_token(identity))
