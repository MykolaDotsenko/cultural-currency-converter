"""API product identity must be bounded before optional Open Food Facts work."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from django.urls import reverse

from apps.exchange.api_quota import ConversionQuota, ConversionQuotaUnavailable
from integrations.product_data import ProductIdentity

UPCA = "034000470693"
EAN13 = "0034000470693"


def _url(barcode: str = UPCA) -> str:
    return reverse("api_v1_product_identity", kwargs={"barcode": barcode})


def _identity() -> ProductIdentity:
    return ProductIdentity(
        barcode=EAN13,
        product_name="Sample product",
        brands=("Example",),
        quantity="100 g",
        categories=("Food",),
        source_name="Open Food Facts",
        source_url=f"https://world.openfoodfacts.org/product/{EAN13}",
        retrieved_at=datetime(2026, 10, 8, 12, tzinfo=UTC),
    )


def test_product_api_canonicalizes_equivalent_codes_and_metered_cache_hits(client):
    with (
        patch("apps.exchange.api_v1.consume_conversion_quota",
              return_value=ConversionQuota(allowed=True, retry_after=30)) as quota,
        patch("apps.exchange.api_v1.lookup_product_identity_cached",
              return_value=_identity()) as lookup,
    ):
        responses = [client.get(_url(UPCA)), client.get(_url(EAN13))]

    assert all(response.status_code == 200 for response in responses)
    assert all(response.json()["data"]["barcode"] == EAN13 for response in responses)
    assert all(response.json()["data"]["price"] is None for response in responses)
    assert all(response["Cache-Control"] == "private, max-age=3600" for response in responses)
    assert quota.call_count == 2
    assert lookup.call_count == 2
    lookup.assert_any_call(EAN13)


@pytest.mark.parametrize("barcode", ["00000000", "bad-code", "123", "123456789012345"])
def test_invalid_product_barcode_is_rejected_before_quota_or_upstream(client, barcode):
    with (
        patch("apps.exchange.api_v1.consume_conversion_quota") as quota,
        patch("apps.exchange.api_v1.lookup_product_identity_cached") as lookup,
    ):
        response = client.get(_url(barcode))

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_barcode"
    assert response["Cache-Control"] == "private, no-store"
    quota.assert_not_called()
    lookup.assert_not_called()


def test_exhausted_shared_quota_blocks_product_lookup_with_retry_after(client):
    with (
        patch("apps.exchange.api_v1.consume_conversion_quota",
              return_value=ConversionQuota(allowed=False, retry_after=21)) as quota,
        patch("apps.exchange.api_v1.lookup_product_identity_cached") as lookup,
    ):
        response = client.get(_url())

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "rate_limited"
    assert response["Retry-After"] == "21"
    assert response["Cache-Control"] == "private, no-store"
    quota.assert_called_once()
    lookup.assert_not_called()


def test_shared_quota_outage_fails_closed_without_product_fetch(client):
    with (
        patch("apps.exchange.api_v1.consume_conversion_quota",
              side_effect=ConversionQuotaUnavailable("private cache detail")),
        patch("apps.exchange.api_v1.lookup_product_identity_cached") as lookup,
    ):
        response = client.get(_url())

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "quota_unavailable"
    assert "private cache detail" not in response.content.decode()
    lookup.assert_not_called()


def test_product_api_remains_read_only(client):
    with (
        patch("apps.exchange.api_v1.consume_conversion_quota") as quota,
        patch("apps.exchange.api_v1.lookup_product_identity_cached") as lookup,
    ):
        response = client.post(_url(), data={})

    assert response.status_code == 405
    quota.assert_not_called()
    lookup.assert_not_called()
