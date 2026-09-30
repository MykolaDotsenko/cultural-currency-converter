from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from apps.exchange.domain import (
    DEFAULT_SOURCE_POLICY,
    FxDomainError,
    RateSeries,
    RateSeriesGrouping,
    RateSeriesPoint,
    RateSeriesRangeError,
)
from apps.exchange.services import (
    get_rate_series,
    select_rate_series_grouping,
)

NOW = datetime(2026, 9, 20, 12, tzinfo=UTC)


def make_series(
    *,
    start_date=date(2025, 9, 20),
    end_date=date(2026, 9, 20),
    grouping=RateSeriesGrouping.DAILY,
):
    return RateSeries(
        base_currency="EUR",
        quote_currency="JPY",
        start_date=start_date,
        end_date=end_date,
        grouping=grouping,
        points=(
            RateSeriesPoint(date(2025, 9, 22), Decimal("173.1"), ("ecb",)),
            RateSeriesPoint(date(2026, 3, 20), Decimal("177.4"), ("ecb",)),
            RateSeriesPoint(date(2026, 9, 18), Decimal("174.5"), ("ecb",)),
        ),
        fetched_at=NOW,
        provider_policy=DEFAULT_SOURCE_POLICY,
    )


class SeriesGateway:
    def __init__(self, series, *, stale=False):
        self.series = series
        self.stale = stale
        self.calls = []

    def get(self, base, quote, start_date, end_date, grouping, policy, *, now):
        self.calls.append((base, quote, start_date, end_date, grouping, policy, now))
        return self.series, self.stale


def exploding_gateway():
    raise AssertionError("invalid series request must not construct the gateway")


def test_rate_series_preserves_sparse_observations_and_summary_points():
    series = make_series()

    assert [point.observation_date for point in series.points] == [
        date(2025, 9, 22),
        date(2026, 3, 20),
        date(2026, 9, 18),
    ]
    assert series.minimum_point.rate == Decimal("173.1")
    assert series.maximum_point.rate == Decimal("177.4")


def test_rate_series_rejects_reversed_range():
    with pytest.raises(RateSeriesRangeError):
        RateSeries(
            base_currency="EUR",
            quote_currency="JPY",
            start_date=date(2026, 2, 1),
            end_date=date(2026, 1, 1),
            grouping=RateSeriesGrouping.DAILY,
            points=(),
            fetched_at=NOW,
            provider_policy=DEFAULT_SOURCE_POLICY,
        )


def test_rate_series_rejects_observation_outside_range():
    with pytest.raises(FxDomainError, match="outside requested range"):
        RateSeries(
            base_currency="EUR",
            quote_currency="JPY",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
            grouping=RateSeriesGrouping.DAILY,
            points=(RateSeriesPoint(date(2025, 12, 31), Decimal("174.5"), ("ecb",)),),
            fetched_at=NOW,
            provider_policy=DEFAULT_SOURCE_POLICY,
        )


def test_rate_series_rejects_non_increasing_dates():
    with pytest.raises(FxDomainError, match="strictly date-ordered"):
        RateSeries(
            base_currency="EUR",
            quote_currency="JPY",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
            grouping=RateSeriesGrouping.DAILY,
            points=(
                RateSeriesPoint(date(2026, 1, 5), Decimal("174.5"), ("ecb",)),
                RateSeriesPoint(date(2026, 1, 2), Decimal("173.5"), ("ecb",)),
            ),
            fetched_at=NOW,
            provider_policy=DEFAULT_SOURCE_POLICY,
        )


@pytest.mark.parametrize(
    ("start_date", "end_date", "expected"),
    [
        (date(2025, 9, 20), date(2026, 9, 20), RateSeriesGrouping.DAILY),
        (date(2023, 9, 20), date(2026, 9, 20), RateSeriesGrouping.WEEK),
        (date(2018, 9, 20), date(2026, 9, 20), RateSeriesGrouping.MONTH),
    ],
)
def test_series_grouping_scales_with_range(start_date, end_date, expected):
    assert select_rate_series_grouping(start_date, end_date) is expected


def test_valid_one_year_series_uses_daily_grouping():
    series = make_series()
    gateway = SeriesGateway(series)

    result = get_rate_series(
        base_currency="eur",
        quote_currency="jpy",
        start_date=series.start_date,
        end_date=series.end_date,
        gateway=gateway,
        now=NOW,
    )

    assert result.series == series
    assert result.stale is False
    assert gateway.calls[0][0:2] == ("EUR", "JPY")
    assert gateway.calls[0][4] is RateSeriesGrouping.DAILY


def test_series_local_today_can_be_ahead_of_utc_date():
    series = make_series(
        start_date=date(2025, 9, 21),
        end_date=date(2026, 9, 21),
    )
    gateway = SeriesGateway(series)

    result = get_rate_series(
        base_currency="EUR",
        quote_currency="JPY",
        start_date=series.start_date,
        end_date=series.end_date,
        gateway=gateway,
        now=datetime(2026, 9, 20, 21, 30, tzinfo=UTC),
        current_date=date(2026, 9, 21),
    )

    assert result.series == series
    assert gateway.calls[0][3] == date(2026, 9, 21)


def test_explicit_series_grouping_is_preserved():
    series = make_series(grouping=RateSeriesGrouping.MONTH)
    gateway = SeriesGateway(series)

    result = get_rate_series(
        base_currency="EUR",
        quote_currency="JPY",
        start_date=series.start_date,
        end_date=series.end_date,
        gateway=gateway,
        grouping=RateSeriesGrouping.MONTH,
        now=NOW,
    )

    assert result.series.grouping is RateSeriesGrouping.MONTH
    assert gateway.calls[0][4] is RateSeriesGrouping.MONTH


@pytest.mark.parametrize(
    ("start_date", "end_date", "message"),
    [
        (date(2026, 9, 20), date(2026, 9, 19), "cannot precede"),
        (date(2026, 9, 20), date(2026, 9, 21), "future"),
        (date(2010, 1, 1), date(2026, 9, 20), "cannot exceed"),
    ],
)
def test_invalid_series_ranges_fail_before_gateway_construction(start_date, end_date, message):
    with pytest.raises(RateSeriesRangeError, match=message):
        get_rate_series(
            base_currency="EUR",
            quote_currency="JPY",
            start_date=start_date,
            end_date=end_date,
            gateway=exploding_gateway,
            now=NOW,
        )


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("grouping", "month"),
        ("observation_granularity", "monthly"),
    ],
)
def test_rate_series_rejects_raw_string_enums(field_name, value):
    kwargs = {
        "base_currency": "EUR",
        "quote_currency": "JPY",
        "start_date": date(2026, 1, 1),
        "end_date": date(2026, 1, 31),
        "grouping": RateSeriesGrouping.DAILY,
        "points": (),
        "fetched_at": NOW,
        "provider_policy": DEFAULT_SOURCE_POLICY,
    }
    kwargs[field_name] = value

    with pytest.raises(FxDomainError):
        RateSeries(**kwargs)
