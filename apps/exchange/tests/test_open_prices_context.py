from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.core.cache import cache

from apps.exchange.open_prices_context import lookup_public_price_observations
from integrations.price_data import (
    OpenPricesRateLimited,
    OpenPricesSourceError,
    PublicPriceObservation,
)


@pytest.fixture(autouse=True)
def reset_price_cache():
    cache.clear()
    yield
    cache.clear()


class StubClient:
    def __init__(self, result=()):
        self.result = result
        self.calls = []

    def fetch_prices(self, barcode):
        self.calls.append(barcode)
        return self.result


def _observation():
    return PublicPriceObservation(
        product_code="0034000470693",
        amount=Decimal("4.29"),
        currency="EUR",
        observed_at=date(2026, 10, 1),
        country_code="FI",
        location_label="Market Helsinki",
        discounted=False,
        proof_id=3,
        source_url="https://prices.openfoodfacts.org/api/v1/prices/2",
        retrieved_at=datetime(2026, 10, 8, tzinfo=UTC),
    )


def test_barcode_aliases_share_cached_result_and_avoid_extra_provider_call():
    client = StubClient((_observation(),))
    assert lookup_public_price_observations("034000470693", client=client) == (_observation(),)
    assert lookup_public_price_observations("0034000470693", client=client) == (_observation(),)
    assert client.calls == ["0034000470693"]


def test_empty_result_is_cached_without_retrying_missing_data():
    client = StubClient()
    assert lookup_public_price_observations("034000470693", client=client) == ()
    assert lookup_public_price_observations("034000470693", client=client) == ()
    assert client.calls == ["0034000470693"]


def test_shared_upstream_quota_blocks_seventh_distinct_lookup():
    client = StubClient()
    # The real limiter must reset at a minute rollover. Keep this capacity
    # assertion on one fixed bucket even if CI executes across :59 -> :00.
    with (
        patch("apps.exchange.open_prices_context._MAX_UPSTREAM_LOOKUPS_PER_MINUTE", 1),
        patch(
            "apps.exchange.open_prices_context._limit_key",
            return_value="shopping:open-prices:limit:fixed-test-minute",
        ),
    ):
        assert lookup_public_price_observations("12345678", client=client) == ()
        with pytest.raises(OpenPricesRateLimited):
            lookup_public_price_observations("12345679", client=client)
    assert client.calls == ["12345678"]


def test_cache_outage_cannot_send_unbounded_provider_traffic():
    client = StubClient()
    with patch("apps.exchange.open_prices_context.cache.add", side_effect=OSError("down")):
        with pytest.raises(OpenPricesSourceError):
            lookup_public_price_observations("12345678", client=client)
    assert client.calls == []


def test_corrupted_cached_value_is_refetched_instead_of_displayed():
    client = StubClient((_observation(),))
    cache.set("shopping:open-prices:v1:0034000470693", ("untrusted",), 60)
    assert lookup_public_price_observations("034000470693", client=client) == (_observation(),)
    assert client.calls == ["0034000470693"]


def test_cache_read_outage_is_optional_source_error_before_provider_call():
    client = StubClient((_observation(),))
    with patch("apps.exchange.open_prices_context.cache.get", side_effect=OSError("redis down")):
        with pytest.raises(OpenPricesSourceError, match="cache"):
            lookup_public_price_observations("034000470693", client=client)
    assert client.calls == []
