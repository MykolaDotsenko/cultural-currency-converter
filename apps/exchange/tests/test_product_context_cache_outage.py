"""Optional product lookups must not bypass the shared cache/throttle on failure."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from django.core.cache import cache

from apps.exchange.product_context import lookup_product_identity_cached
from integrations.product_data import ProductDataSourceError, ProductIdentity, ProductNotFound


class ProductClient:
    def __init__(self, *, missing: bool = False):
        self.missing = missing
        self.calls: list[str] = []

    def fetch_product(self, barcode: str) -> ProductIdentity:
        self.calls.append(barcode)
        if self.missing:
            raise ProductNotFound("not found")
        return ProductIdentity(
            barcode=barcode,
            product_name="Example",
            brands=(),
            quantity="100 g",
            categories=(),
            source_name="Open Food Facts",
            source_url=f"https://world.openfoodfacts.org/product/{barcode}",
            retrieved_at=datetime(2026, 10, 8, 12, tzinfo=UTC),
        )


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


def test_cache_read_failure_blocks_provider_call():
    client = ProductClient()
    with patch("apps.exchange.product_context.cache.get", side_effect=RuntimeError("down")):
        with pytest.raises(ProductDataSourceError, match="cache is temporarily unavailable"):
            lookup_product_identity_cached("3017624010701", client=client)
    assert client.calls == []


def test_provider_quota_initialization_failure_blocks_provider_call():
    client = ProductClient()
    with patch("apps.exchange.product_context.cache.add", side_effect=RuntimeError("down")):
        with pytest.raises(ProductDataSourceError, match="cache is temporarily unavailable"):
            lookup_product_identity_cached("3017624010701", client=client)
    assert client.calls == []


@pytest.mark.parametrize("failure", [RuntimeError("offline"), ValueError("evicted")])
def test_provider_quota_increment_failure_does_not_reset_bucket(failure):
    client = ProductClient()
    with (
        patch("apps.exchange.product_context.cache.add", return_value=False),
        patch("apps.exchange.product_context.cache.incr", side_effect=failure),
        patch("apps.exchange.product_context.cache.set") as reset,
    ):
        with pytest.raises(ProductDataSourceError, match="cache is temporarily unavailable"):
            lookup_product_identity_cached("3017624010701", client=client)
    reset.assert_not_called()
    assert client.calls == []


def test_corrupt_cache_record_failed_delete_does_not_contact_provider():
    cache.set(
        "product-context:v1:3017624010701",
        {"found": True, "product": {"invalid": True}},
        timeout=60,
    )
    client = ProductClient()
    with patch("apps.exchange.product_context.cache.delete", side_effect=RuntimeError("down")):
        with pytest.raises(ProductDataSourceError, match="cache is temporarily unavailable"):
            lookup_product_identity_cached("3017624010701", client=client)
    assert client.calls == []


@pytest.mark.parametrize("missing", [False, True])
def test_positive_or_negative_cache_write_failure_is_safe(missing):
    client = ProductClient(missing=missing)
    with patch("apps.exchange.product_context.cache.set", side_effect=RuntimeError("secret")):
        with pytest.raises(ProductDataSourceError, match="cache is temporarily unavailable") as exc:
            lookup_product_identity_cached("3017624010701", client=client)
    assert "secret" not in str(exc.value)
    assert client.calls == ["3017624010701"]
