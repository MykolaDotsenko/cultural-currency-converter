import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from django.core.cache import cache

from apps.exchange.cache import (
    HistoricalQuoteGateway,
    HistoricalSeriesGateway,
    LatestQuoteGateway,
    historical_cache_key,
    historical_resolution_cache_key,
    latest_cache_key,
    rate_series_cache_key,
    serialize_quote,
    serialize_series,
)
from apps.exchange.domain import (
    DEFAULT_SOURCE_POLICY,
    FxSourcePolicy,
    HistoricalObservationUnavailable,
    ObservationGranularity,
    ProviderPolicyMode,
    RateQuote,
    RateSeries,
    RateSeriesGrouping,
    RateSeriesPoint,
)
from apps.exchange.providers.base import FxProviderInvalidPayload, FxProviderUnavailable

NOW = datetime(2026, 9, 20, 12, tzinfo=UTC)


def make_quote(
    *,
    fetched_at=NOW,
    effective_date=date(2026, 9, 18),
    policy=DEFAULT_SOURCE_POLICY,
    granularity=ObservationGranularity.DAILY,
):
    return RateQuote(
        base_currency="EUR",
        quote_currency="JPY",
        rate=Decimal("174.5"),
        requested_date=None,
        effective_date=effective_date,
        fetched_at=fetched_at,
        provider_policy=policy,
        provider_keys=((policy.provider_key,) if policy.provider_key else ("ecb",)),
        historical=False,
        observation_granularity=granularity,
    )


class FakeProvider:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = 0

    def latest_quote(self, base, quote, policy):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result

    def historical_quote(self, base, quote, requested_date, policy):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result

    def rate_series(self, base, quote, start_date, end_date, grouping, policy):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


def test_fresh_cache_hit_skips_provider():
    cached = make_quote(fetched_at=NOW - timedelta(hours=1))
    cache.set(latest_cache_key("EUR", "JPY", DEFAULT_SOURCE_POLICY), serialize_quote(cached), 100)
    provider = FakeProvider(error=AssertionError("provider must not be called"))

    result, stale = LatestQuoteGateway(provider).get("EUR", "JPY", DEFAULT_SOURCE_POLICY, now=NOW)

    assert result == cached
    assert stale is False
    assert provider.calls == 0


def test_provider_failure_uses_only_bounded_semantically_matching_stale_quote(caplog):
    cached = make_quote(fetched_at=NOW - timedelta(days=2))
    cache.set(latest_cache_key("EUR", "JPY", DEFAULT_SOURCE_POLICY), serialize_quote(cached), 100)
    provider = FakeProvider(error=FxProviderUnavailable("down"))

    with caplog.at_level(logging.WARNING, logger="cultural_currency.exchange"):
        result, stale = LatestQuoteGateway(provider).get(
            "EUR",
            "JPY",
            DEFAULT_SOURCE_POLICY,
            now=NOW,
        )

    assert result == cached
    assert stale is True
    record = next(record for record in caplog.records if record.msg == "fx_stale_fallback")
    assert record.dependency == "cache"
    assert record.operation == "latest_quote"
    assert record.outcome == "degraded"
    assert record.cache_status == "stale_fallback"
    assert record.stale is True


def test_too_old_stale_quote_is_rejected():
    cached = make_quote(
        fetched_at=NOW - timedelta(days=8),
        effective_date=date(2026, 9, 12),
    )
    cache.set(latest_cache_key("EUR", "JPY", DEFAULT_SOURCE_POLICY), serialize_quote(cached), 100)
    gateway = LatestQuoteGateway(FakeProvider(error=FxProviderUnavailable("down")))

    with pytest.raises(FxProviderUnavailable):
        gateway.get("EUR", "JPY", DEFAULT_SOURCE_POLICY, now=NOW)


def test_fresh_cache_with_too_old_daily_observation_is_refetched():
    cached = make_quote(
        fetched_at=NOW - timedelta(hours=1),
        effective_date=date(2026, 9, 10),
    )
    key = latest_cache_key("EUR", "JPY", DEFAULT_SOURCE_POLICY)
    cache.set(key, serialize_quote(cached), 100)
    provider_quote = make_quote()
    provider = FakeProvider(result=provider_quote)

    result, stale = LatestQuoteGateway(provider).get(
        "EUR",
        "JPY",
        DEFAULT_SOURCE_POLICY,
        now=NOW,
    )

    assert result == provider_quote
    assert stale is False
    assert provider.calls == 1


def test_provider_latest_quote_outside_daily_observation_window_is_rejected():
    provider_quote = make_quote(effective_date=date(2026, 9, 10))
    gateway = LatestQuoteGateway(FakeProvider(result=provider_quote))

    with pytest.raises(FxProviderInvalidPayload, match="daily observation window"):
        gateway.get("EUR", "JPY", DEFAULT_SOURCE_POLICY, now=NOW)

    assert cache.get(latest_cache_key("EUR", "JPY", DEFAULT_SOURCE_POLICY)) is None


def test_monthly_latest_quote_uses_monthly_observation_window():
    policy = FxSourcePolicy(mode=ProviderPolicyMode.PINNED, provider_key="hmrc")
    provider_quote = make_quote(
        effective_date=date(2026, 9, 1),
        policy=policy,
        granularity=ObservationGranularity.MONTHLY,
    )
    provider = FakeProvider(result=provider_quote)

    result, stale = LatestQuoteGateway(provider).get("EUR", "JPY", policy, now=NOW)

    assert result == provider_quote
    assert stale is False
    assert provider.calls == 1


def test_future_dated_latest_cache_is_ignored_and_refetched():
    cached = make_quote(fetched_at=NOW + timedelta(minutes=6))
    key = latest_cache_key("EUR", "JPY", DEFAULT_SOURCE_POLICY)
    cache.set(key, serialize_quote(cached), 100)
    provider_quote = make_quote(fetched_at=NOW)
    provider = FakeProvider(result=provider_quote)

    result, stale = LatestQuoteGateway(provider).get(
        "EUR",
        "JPY",
        DEFAULT_SOURCE_POLICY,
        now=NOW,
    )

    assert result == provider_quote
    assert stale is False
    assert provider.calls == 1


def test_provider_latest_quote_beyond_future_clock_skew_is_rejected():
    provider_quote = make_quote(fetched_at=NOW + timedelta(minutes=6))
    gateway = LatestQuoteGateway(FakeProvider(result=provider_quote))

    with pytest.raises(FxProviderInvalidPayload, match="future clock skew"):
        gateway.get("EUR", "JPY", DEFAULT_SOURCE_POLICY, now=NOW)

    assert cache.get(latest_cache_key("EUR", "JPY", DEFAULT_SOURCE_POLICY)) is None


def test_provider_latest_quote_within_future_clock_skew_is_allowed():
    provider_quote = make_quote(fetched_at=NOW + timedelta(minutes=2))
    provider = FakeProvider(result=provider_quote)

    result, stale = LatestQuoteGateway(provider).get(
        "EUR",
        "JPY",
        DEFAULT_SOURCE_POLICY,
        now=NOW,
    )

    assert result == provider_quote
    assert stale is False
    assert provider.calls == 1


def test_latest_gateway_rejects_negative_future_clock_skew():
    with pytest.raises(ValueError, match="future clock skew"):
        LatestQuoteGateway(FakeProvider(), max_future_skew=timedelta(seconds=-1))


def test_provider_policy_changes_cache_identity():
    pinned = FxSourcePolicy(mode=ProviderPolicyMode.PINNED, provider_key="ecb")
    assert latest_cache_key("EUR", "JPY", DEFAULT_SOURCE_POLICY) != latest_cache_key(
        "EUR", "JPY", pinned
    )


def test_malformed_provider_response_can_fall_back_to_matching_stale_quote():
    cached = make_quote(fetched_at=NOW - timedelta(days=2))
    cache.set(latest_cache_key("EUR", "JPY", DEFAULT_SOURCE_POLICY), serialize_quote(cached), 100)
    gateway = LatestQuoteGateway(FakeProvider(error=FxProviderInvalidPayload("bad payload")))

    result, stale = gateway.get("EUR", "JPY", DEFAULT_SOURCE_POLICY, now=NOW)

    assert result == cached
    assert stale is True


def test_wrong_pair_cache_key_is_never_reused_on_failure():
    cached = make_quote(fetched_at=NOW - timedelta(days=2))
    cache.set(latest_cache_key("EUR", "USD", DEFAULT_SOURCE_POLICY), serialize_quote(cached), 100)
    gateway = LatestQuoteGateway(FakeProvider(error=FxProviderUnavailable("down")))

    with pytest.raises(FxProviderUnavailable):
        gateway.get("EUR", "JPY", DEFAULT_SOURCE_POLICY, now=NOW)


def test_attribution_mode_changes_cache_identity():
    without_attribution = FxSourcePolicy(include_attribution=False)
    assert latest_cache_key("EUR", "JPY", DEFAULT_SOURCE_POLICY) != latest_cache_key(
        "EUR", "JPY", without_attribution
    )


def test_corrupted_cached_provider_keys_are_ignored():
    key = latest_cache_key("EUR", "JPY", DEFAULT_SOURCE_POLICY)
    payload = serialize_quote(make_quote())
    payload["provider_keys"] = "ecb"
    cache.set(key, payload, 100)
    provider_quote = make_quote(fetched_at=NOW)
    provider = FakeProvider(result=provider_quote)

    result, stale = LatestQuoteGateway(provider).get("EUR", "JPY", DEFAULT_SOURCE_POLICY, now=NOW)

    assert result == provider_quote
    assert stale is False
    assert provider.calls == 1


def test_fresh_semantically_wrong_latest_cache_is_ignored_and_refetched():
    wrong_pair = RateQuote(
        base_currency="EUR",
        quote_currency="USD",
        rate=Decimal("1.1"),
        requested_date=None,
        effective_date=date(2026, 9, 18),
        fetched_at=NOW - timedelta(hours=1),
        provider_policy=DEFAULT_SOURCE_POLICY,
        provider_keys=("ecb",),
        historical=False,
    )
    key = latest_cache_key("EUR", "JPY", DEFAULT_SOURCE_POLICY)
    cache.set(key, serialize_quote(wrong_pair), 100)
    provider_quote = make_quote(fetched_at=NOW)
    provider = FakeProvider(result=provider_quote)

    result, stale = LatestQuoteGateway(provider).get(
        "EUR",
        "JPY",
        DEFAULT_SOURCE_POLICY,
        now=NOW,
    )

    assert result == provider_quote
    assert stale is False
    assert provider.calls == 1


def test_wrong_identity_stale_cache_is_never_used_as_failure_fallback():
    wrong_pair = RateQuote(
        base_currency="EUR",
        quote_currency="USD",
        rate=Decimal("1.1"),
        requested_date=None,
        effective_date=date(2026, 9, 18),
        fetched_at=NOW - timedelta(days=2),
        provider_policy=DEFAULT_SOURCE_POLICY,
        provider_keys=("ecb",),
        historical=False,
    )
    key = latest_cache_key("EUR", "JPY", DEFAULT_SOURCE_POLICY)
    cache.set(key, serialize_quote(wrong_pair), 100)
    provider = FakeProvider(error=FxProviderUnavailable("down"))

    with pytest.raises(FxProviderUnavailable):
        LatestQuoteGateway(provider).get(
            "EUR",
            "JPY",
            DEFAULT_SOURCE_POLICY,
            now=NOW,
        )

    assert provider.calls == 1


def test_provider_quote_identity_is_rechecked_before_caching():
    wrong_pair = RateQuote(
        base_currency="EUR",
        quote_currency="USD",
        rate=Decimal("1.1"),
        requested_date=None,
        effective_date=date(2026, 9, 18),
        fetched_at=NOW,
        provider_policy=DEFAULT_SOURCE_POLICY,
        provider_keys=("ecb",),
        historical=False,
    )
    gateway = LatestQuoteGateway(FakeProvider(result=wrong_pair))

    with pytest.raises(FxProviderInvalidPayload, match="different pair"):
        gateway.get("EUR", "JPY", DEFAULT_SOURCE_POLICY, now=NOW)

    assert cache.get(latest_cache_key("EUR", "JPY", DEFAULT_SOURCE_POLICY)) is None


def test_cache_read_failure_falls_through_to_provider(monkeypatch):
    provider_quote = make_quote()
    provider = FakeProvider(result=provider_quote)

    def fail_get(*args, **kwargs):
        raise RuntimeError("cache unavailable")

    monkeypatch.setattr(cache, "get", fail_get)

    result, stale = LatestQuoteGateway(provider).get("EUR", "JPY", DEFAULT_SOURCE_POLICY, now=NOW)

    assert result == provider_quote
    assert stale is False
    assert provider.calls == 1


def test_cache_write_failure_does_not_invalidate_provider_result(monkeypatch):
    provider_quote = make_quote()
    provider = FakeProvider(result=provider_quote)

    def fail_set(*args, **kwargs):
        raise RuntimeError("cache unavailable")

    monkeypatch.setattr(cache, "set", fail_set)

    result, stale = LatestQuoteGateway(provider).get("EUR", "JPY", DEFAULT_SOURCE_POLICY, now=NOW)

    assert result == provider_quote
    assert stale is False


def test_invalid_provider_quote_identity_can_use_matching_stale_cache():
    cached = make_quote(fetched_at=NOW - timedelta(days=2))
    cache.set(latest_cache_key("EUR", "JPY", DEFAULT_SOURCE_POLICY), serialize_quote(cached), 100)
    wrong_pair = RateQuote(
        base_currency="EUR",
        quote_currency="USD",
        rate=Decimal("1.1"),
        requested_date=None,
        effective_date=date(2026, 9, 18),
        fetched_at=NOW,
        provider_policy=DEFAULT_SOURCE_POLICY,
        provider_keys=("ecb",),
        historical=False,
    )

    result, stale = LatestQuoteGateway(FakeProvider(result=wrong_pair)).get(
        "EUR", "JPY", DEFAULT_SOURCE_POLICY, now=NOW
    )

    assert result == cached
    assert stale is True


def make_historical_quote(
    *,
    requested_date=date(2026, 9, 20),
    effective_date=date(2026, 9, 18),
    policy=DEFAULT_SOURCE_POLICY,
    granularity=ObservationGranularity.DAILY,
):
    return RateQuote(
        base_currency="EUR",
        quote_currency="JPY",
        rate=Decimal("174.5"),
        requested_date=requested_date,
        effective_date=effective_date,
        fetched_at=NOW,
        provider_policy=policy,
        provider_keys=((policy.provider_key,) if policy.provider_key else ("ecb",)),
        historical=True,
        observation_granularity=granularity,
    )


def test_historical_resolution_cache_hit_skips_provider():
    historical = make_historical_quote()
    key = historical_resolution_cache_key(
        "EUR",
        "JPY",
        historical.requested_date,
        DEFAULT_SOURCE_POLICY,
    )
    cache.set(key, serialize_quote(historical), 100)
    provider = FakeProvider(error=AssertionError("historical provider must not be called"))

    result = HistoricalQuoteGateway(provider).get(
        "EUR",
        "JPY",
        historical.requested_date,
        DEFAULT_SOURCE_POLICY,
    )

    assert result == historical
    assert provider.calls == 0


def test_historical_resolution_cache_with_wrong_requested_date_is_refetched():
    requested = date(2026, 9, 20)
    cached = make_historical_quote(
        requested_date=date(2026, 9, 19),
        effective_date=date(2026, 9, 18),
    )
    key = historical_resolution_cache_key(
        "EUR",
        "JPY",
        requested,
        DEFAULT_SOURCE_POLICY,
    )
    cache.set(key, serialize_quote(cached), 100)
    corrected = make_historical_quote(
        requested_date=requested,
        effective_date=date(2026, 9, 18),
    )
    provider = FakeProvider(result=corrected)

    result = HistoricalQuoteGateway(provider).get(
        "EUR",
        "JPY",
        requested,
        DEFAULT_SOURCE_POLICY,
    )

    assert result == corrected
    assert provider.calls == 1


def test_historical_resolution_cache_outside_gap_policy_is_refetched():
    requested = date(2026, 9, 20)
    cached = make_historical_quote(
        requested_date=requested,
        effective_date=date(2026, 9, 12),
    )
    key = historical_resolution_cache_key(
        "EUR",
        "JPY",
        requested,
        DEFAULT_SOURCE_POLICY,
    )
    cache.set(key, serialize_quote(cached), 100)
    corrected = make_historical_quote(
        requested_date=requested,
        effective_date=date(2026, 9, 18),
    )
    provider = FakeProvider(result=corrected)

    result = HistoricalQuoteGateway(provider).get(
        "EUR",
        "JPY",
        requested,
        DEFAULT_SOURCE_POLICY,
    )

    assert result == corrected
    assert provider.calls == 1


def test_historical_provider_result_populates_resolution_and_observation_cache():
    historical = make_historical_quote()
    provider = FakeProvider(result=historical)

    result = HistoricalQuoteGateway(provider).get(
        "EUR",
        "JPY",
        historical.requested_date,
        DEFAULT_SOURCE_POLICY,
    )

    assert result == historical
    assert provider.calls == 1
    resolution = cache.get(
        historical_resolution_cache_key(
            "EUR",
            "JPY",
            historical.requested_date,
            DEFAULT_SOURCE_POLICY,
        )
    )
    observation = cache.get(
        historical_cache_key(
            "EUR",
            "JPY",
            historical.effective_date,
            DEFAULT_SOURCE_POLICY,
        )
    )
    assert resolution is not None
    assert observation is not None


def test_historical_previous_observation_within_seven_days_is_allowed():
    historical = make_historical_quote(
        requested_date=date(2026, 9, 20),
        effective_date=date(2026, 9, 14),
    )

    result = HistoricalQuoteGateway(FakeProvider(result=historical)).get(
        "EUR",
        "JPY",
        historical.requested_date,
        DEFAULT_SOURCE_POLICY,
    )

    assert result.used_previous_observation is True


def test_historical_previous_observation_beyond_policy_is_rejected():
    historical = make_historical_quote(
        requested_date=date(2026, 9, 20),
        effective_date=date(2026, 9, 12),
    )

    with pytest.raises(HistoricalObservationUnavailable):
        HistoricalQuoteGateway(FakeProvider(result=historical)).get(
            "EUR",
            "JPY",
            historical.requested_date,
            DEFAULT_SOURCE_POLICY,
        )


def test_historical_quote_must_preserve_requested_date():
    historical = make_historical_quote(requested_date=date(2026, 9, 19))

    with pytest.raises(FxProviderInvalidPayload, match="requested-date"):
        HistoricalQuoteGateway(FakeProvider(result=historical)).get(
            "EUR",
            "JPY",
            date(2026, 9, 20),
            DEFAULT_SOURCE_POLICY,
        )


def test_historical_cache_write_failure_does_not_invalidate_provider_result(monkeypatch):
    historical = make_historical_quote()
    provider = FakeProvider(result=historical)

    def fail_set(*args, **kwargs):
        raise RuntimeError("cache unavailable")

    monkeypatch.setattr(cache, "set", fail_set)

    result = HistoricalQuoteGateway(provider).get(
        "EUR",
        "JPY",
        historical.requested_date,
        DEFAULT_SOURCE_POLICY,
    )

    assert result == historical


def test_monthly_observation_can_precede_requested_date_by_more_than_daily_window():
    historical = make_historical_quote(
        requested_date=date(2026, 9, 30),
        effective_date=date(2026, 9, 1),
        granularity=ObservationGranularity.MONTHLY,
    )

    result = HistoricalQuoteGateway(FakeProvider(result=historical)).get(
        "EUR",
        "JPY",
        historical.requested_date,
        DEFAULT_SOURCE_POLICY,
    )

    assert result.observation_granularity is ObservationGranularity.MONTHLY


def test_quarterly_observation_can_span_quarter_without_daily_fallback_failure():
    historical = make_historical_quote(
        requested_date=date(2026, 9, 30),
        effective_date=date(2026, 7, 1),
        granularity=ObservationGranularity.QUARTERLY,
    )

    result = HistoricalQuoteGateway(FakeProvider(result=historical)).get(
        "EUR",
        "JPY",
        historical.requested_date,
        DEFAULT_SOURCE_POLICY,
    )

    assert result.observation_granularity is ObservationGranularity.QUARTERLY


def test_historical_invalidation_refetches_corrected_observation():
    original = make_historical_quote(
        requested_date=date(1998, 6, 15),
        effective_date=date(1998, 6, 12),
    )
    corrected = RateQuote(
        base_currency="EUR",
        quote_currency="JPY",
        rate=Decimal("180.25"),
        requested_date=date(1998, 6, 15),
        effective_date=date(1998, 6, 15),
        fetched_at=NOW,
        provider_policy=DEFAULT_SOURCE_POLICY,
        provider_keys=("ecb",),
        historical=True,
        observation_granularity=ObservationGranularity.DAILY,
    )
    first_provider = FakeProvider(result=original)
    first_gateway = HistoricalQuoteGateway(first_provider)

    first = first_gateway.get(
        "EUR",
        "JPY",
        date(1998, 6, 15),
        DEFAULT_SOURCE_POLICY,
    )
    assert first == original
    assert first_provider.calls == 1

    first_gateway.invalidate(
        "EUR",
        "JPY",
        date(1998, 6, 15),
        DEFAULT_SOURCE_POLICY,
    )

    second_provider = FakeProvider(result=corrected)
    second = HistoricalQuoteGateway(second_provider).get(
        "EUR",
        "JPY",
        date(1998, 6, 15),
        DEFAULT_SOURCE_POLICY,
    )

    assert second == corrected
    assert second_provider.calls == 1


def test_historical_invalidation_removes_resolution_and_observation_keys():
    historical = make_historical_quote(
        requested_date=date(1998, 6, 15),
        effective_date=date(1998, 6, 12),
    )
    gateway = HistoricalQuoteGateway(FakeProvider(result=historical))
    gateway.get("EUR", "JPY", historical.requested_date, DEFAULT_SOURCE_POLICY)

    resolution_key = historical_resolution_cache_key(
        "EUR", "JPY", historical.requested_date, DEFAULT_SOURCE_POLICY
    )
    observation_key = historical_cache_key(
        "EUR", "JPY", historical.effective_date, DEFAULT_SOURCE_POLICY
    )
    assert cache.get(resolution_key) is not None
    assert cache.get(observation_key) is not None

    gateway.invalidate(
        "EUR",
        "JPY",
        historical.requested_date,
        DEFAULT_SOURCE_POLICY,
    )

    assert cache.get(resolution_key) is None
    assert cache.get(observation_key) is None


def make_rate_series(
    *,
    start_date=date(2026, 1, 1),
    end_date=date(2026, 1, 7),
    grouping=RateSeriesGrouping.DAILY,
    fetched_at=NOW,
    policy=DEFAULT_SOURCE_POLICY,
):
    providers = (policy.provider_key,) if policy.provider_key else ("ecb",)
    return RateSeries(
        base_currency="EUR",
        quote_currency="JPY",
        start_date=start_date,
        end_date=end_date,
        grouping=grouping,
        points=(
            RateSeriesPoint(date(2026, 1, 2), Decimal("179.8"), providers),
            RateSeriesPoint(date(2026, 1, 5), Decimal("181.2"), providers),
        ),
        fetched_at=fetched_at,
        provider_policy=policy,
    )


def test_rate_series_cache_key_includes_range_grouping_and_policy():
    pinned = FxSourcePolicy(mode=ProviderPolicyMode.PINNED, provider_key="ecb")
    daily = rate_series_cache_key(
        "EUR",
        "JPY",
        date(2026, 1, 1),
        date(2026, 1, 7),
        RateSeriesGrouping.DAILY,
        DEFAULT_SOURCE_POLICY,
    )
    monthly = rate_series_cache_key(
        "EUR",
        "JPY",
        date(2026, 1, 1),
        date(2026, 1, 7),
        RateSeriesGrouping.MONTH,
        DEFAULT_SOURCE_POLICY,
    )
    other_range = rate_series_cache_key(
        "EUR",
        "JPY",
        date(2026, 1, 1),
        date(2026, 1, 8),
        RateSeriesGrouping.DAILY,
        DEFAULT_SOURCE_POLICY,
    )
    other_policy = rate_series_cache_key(
        "EUR",
        "JPY",
        date(2026, 1, 1),
        date(2026, 1, 7),
        RateSeriesGrouping.DAILY,
        pinned,
    )

    assert len({daily, monthly, other_range, other_policy}) == 4


def test_rate_series_fresh_cache_hit_skips_provider():
    series = make_rate_series(fetched_at=NOW - timedelta(hours=1))
    key = rate_series_cache_key(
        "EUR",
        "JPY",
        series.start_date,
        series.end_date,
        series.grouping,
        DEFAULT_SOURCE_POLICY,
    )
    cache.set(key, serialize_series(series), 100)
    provider = FakeProvider(error=AssertionError("series provider must not be called"))

    result, stale = HistoricalSeriesGateway(provider).get(
        "EUR",
        "JPY",
        series.start_date,
        series.end_date,
        series.grouping,
        DEFAULT_SOURCE_POLICY,
        now=NOW,
    )

    assert result == series
    assert stale is False
    assert provider.calls == 0


def test_rate_series_provider_failure_uses_only_matching_stale_series(caplog):
    series = make_rate_series(fetched_at=NOW - timedelta(days=2))
    key = rate_series_cache_key(
        "EUR",
        "JPY",
        series.start_date,
        series.end_date,
        series.grouping,
        DEFAULT_SOURCE_POLICY,
    )
    cache.set(key, serialize_series(series), 100)
    provider = FakeProvider(error=FxProviderUnavailable("down"))

    with caplog.at_level(logging.WARNING, logger="cultural_currency.exchange"):
        result, stale = HistoricalSeriesGateway(provider).get(
            "EUR",
            "JPY",
            series.start_date,
            series.end_date,
            series.grouping,
            DEFAULT_SOURCE_POLICY,
            now=NOW,
        )

    assert result == series
    assert stale is True
    record = next(record for record in caplog.records if record.msg == "fx_stale_fallback")
    assert record.operation == "rate_series"
    assert record.outcome == "degraded"
    assert record.cache_status == "stale_fallback"
    assert record.stale is True


def test_rate_series_too_old_stale_data_is_rejected():
    series = make_rate_series(fetched_at=NOW - timedelta(days=31))
    key = rate_series_cache_key(
        "EUR",
        "JPY",
        series.start_date,
        series.end_date,
        series.grouping,
        DEFAULT_SOURCE_POLICY,
    )
    cache.set(key, serialize_series(series), 100)
    gateway = HistoricalSeriesGateway(FakeProvider(error=FxProviderUnavailable("down")))

    with pytest.raises(FxProviderUnavailable):
        gateway.get(
            "EUR",
            "JPY",
            series.start_date,
            series.end_date,
            series.grouping,
            DEFAULT_SOURCE_POLICY,
            now=NOW,
        )


def test_future_dated_rate_series_cache_is_ignored_and_refetched():
    cached = make_rate_series(fetched_at=NOW + timedelta(minutes=6))
    key = rate_series_cache_key(
        "EUR",
        "JPY",
        cached.start_date,
        cached.end_date,
        cached.grouping,
        DEFAULT_SOURCE_POLICY,
    )
    cache.set(key, serialize_series(cached), 100)
    provider_series = make_rate_series(fetched_at=NOW)
    provider = FakeProvider(result=provider_series)

    result, stale = HistoricalSeriesGateway(provider).get(
        "EUR",
        "JPY",
        cached.start_date,
        cached.end_date,
        cached.grouping,
        DEFAULT_SOURCE_POLICY,
        now=NOW,
    )

    assert result == provider_series
    assert stale is False
    assert provider.calls == 1


def test_provider_rate_series_beyond_future_clock_skew_is_rejected():
    provider_series = make_rate_series(fetched_at=NOW + timedelta(minutes=6))
    gateway = HistoricalSeriesGateway(FakeProvider(result=provider_series))

    with pytest.raises(FxProviderInvalidPayload, match="future clock skew"):
        gateway.get(
            "EUR",
            "JPY",
            provider_series.start_date,
            provider_series.end_date,
            provider_series.grouping,
            DEFAULT_SOURCE_POLICY,
            now=NOW,
        )

    key = rate_series_cache_key(
        "EUR",
        "JPY",
        provider_series.start_date,
        provider_series.end_date,
        provider_series.grouping,
        DEFAULT_SOURCE_POLICY,
    )
    assert cache.get(key) is None


def test_rate_series_gateway_rejects_negative_future_clock_skew():
    with pytest.raises(ValueError, match="future clock skew"):
        HistoricalSeriesGateway(FakeProvider(), max_future_skew=timedelta(seconds=-1))


def test_rate_series_wrong_grouping_cache_is_not_reused():
    series = make_rate_series(
        grouping=RateSeriesGrouping.MONTH,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 7),
    )
    key = rate_series_cache_key(
        "EUR",
        "JPY",
        series.start_date,
        series.end_date,
        series.grouping,
        DEFAULT_SOURCE_POLICY,
    )
    cache.set(key, serialize_series(series), 100)
    gateway = HistoricalSeriesGateway(FakeProvider(error=FxProviderUnavailable("down")))

    with pytest.raises(FxProviderUnavailable):
        gateway.get(
            "EUR",
            "JPY",
            series.start_date,
            series.end_date,
            RateSeriesGrouping.DAILY,
            DEFAULT_SOURCE_POLICY,
            now=NOW,
        )


def test_rate_series_provider_identity_is_verified_before_caching():
    wrong_pair = RateSeries(
        base_currency="EUR",
        quote_currency="USD",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 7),
        grouping=RateSeriesGrouping.DAILY,
        points=(RateSeriesPoint(date(2026, 1, 2), Decimal("1.1"), ("ecb",)),),
        fetched_at=NOW,
        provider_policy=DEFAULT_SOURCE_POLICY,
    )
    gateway = HistoricalSeriesGateway(FakeProvider(result=wrong_pair))

    with pytest.raises(FxProviderInvalidPayload, match="different pair"):
        gateway.get(
            "EUR",
            "JPY",
            date(2026, 1, 1),
            date(2026, 1, 7),
            RateSeriesGrouping.DAILY,
            DEFAULT_SOURCE_POLICY,
            now=NOW,
        )


def test_rate_series_semantically_wrong_fresh_cache_is_ignored():
    requested = make_rate_series(fetched_at=NOW - timedelta(hours=1))
    wrong = RateSeries(
        base_currency="EUR",
        quote_currency="USD",
        start_date=requested.start_date,
        end_date=requested.end_date,
        grouping=requested.grouping,
        points=(RateSeriesPoint(date(2026, 1, 2), Decimal("1.1"), ("ecb",)),),
        fetched_at=NOW - timedelta(hours=1),
        provider_policy=DEFAULT_SOURCE_POLICY,
    )
    key = rate_series_cache_key(
        "EUR",
        "JPY",
        requested.start_date,
        requested.end_date,
        requested.grouping,
        DEFAULT_SOURCE_POLICY,
    )
    cache.set(key, serialize_series(wrong), 100)
    provider = FakeProvider(result=requested)

    result, stale = HistoricalSeriesGateway(provider).get(
        "EUR",
        "JPY",
        requested.start_date,
        requested.end_date,
        requested.grouping,
        DEFAULT_SOURCE_POLICY,
        now=NOW,
    )

    assert result == requested
    assert stale is False
    assert provider.calls == 1
