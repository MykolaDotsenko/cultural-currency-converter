from datetime import UTC, date
from decimal import Decimal

import pytest

from apps.exchange.domain import (
    FxSourcePolicy,
    ProviderPolicyMode,
    RateSeriesGrouping,
)
from apps.exchange.providers.base import FxProviderUnsupportedPair
from apps.exchange.providers.deterministic_test import DeterministicTestFxProvider


def test_deterministic_test_provider_returns_stable_cross_rate():
    provider = DeterministicTestFxProvider()

    quote = provider.latest_quote("EUR", "JPY", FxSourcePolicy())

    assert quote.rate == Decimal("174.5")
    assert quote.base_currency == "EUR"
    assert quote.quote_currency == "JPY"
    assert quote.requested_date is None
    assert quote.historical is False
    assert quote.provider_keys == ("browser-quality-fixture",)
    assert quote.fetched_at.tzinfo is UTC


def test_deterministic_test_provider_preserves_pinned_attribution():
    provider = DeterministicTestFxProvider()
    policy = FxSourcePolicy(
        mode=ProviderPolicyMode.PINNED,
        provider_key="ecb",
        include_attribution=True,
    )

    quote = provider.latest_quote("USD", "JPY", policy)

    assert quote.provider_policy == policy
    assert quote.provider_keys == ("ecb",)


def test_deterministic_test_provider_preserves_historical_date():
    provider = DeterministicTestFxProvider()
    requested_date = date(2020, 5, 4)

    quote = provider.historical_quote("EUR", "USD", requested_date, FxSourcePolicy())

    assert quote.requested_date == requested_date
    assert quote.effective_date == requested_date
    assert quote.historical is True


def test_deterministic_test_provider_builds_bounded_series():
    provider = DeterministicTestFxProvider()

    series = provider.rate_series(
        "EUR",
        "JPY",
        date(2026, 1, 1),
        date(2026, 2, 1),
        RateSeriesGrouping.WEEK,
        FxSourcePolicy(),
    )

    assert series.start_date == date(2026, 1, 1)
    assert series.end_date == date(2026, 2, 1)
    assert series.points[0].observation_date == date(2026, 1, 1)
    assert series.points[-1].observation_date == date(2026, 2, 1)
    assert 2 <= len(series.points) <= 7
    assert all(point.rate > 0 for point in series.points)


def test_deterministic_test_provider_rejects_unknown_currency():
    provider = DeterministicTestFxProvider()

    with pytest.raises(FxProviderUnsupportedPair):
        provider.latest_quote("EUR", "CAD", FxSourcePolicy())
