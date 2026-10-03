from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from apps.common.presentation.media_view_models import ImageViewModel
from apps.exchange.domain import (
    DEFAULT_SOURCE_POLICY,
    ConversionRepresentationError,
    ConversionResult,
    FxDomainError,
    FxSourcePolicy,
    ProviderPolicyMode,
    RateQuote,
    RateSeries,
    RateSeriesGrouping,
    RateSeriesPoint,
    RateSeriesRangeError,
    RateSeriesResult,
    ThenNowComparison,
    convert_amount,
)
from apps.exchange.series_presentation import (
    build_rate_series_component,
    build_then_now_component,
)
from apps.exchange.services import compare_historical_to_latest, select_rate_series_grouping

NOW = datetime(2026, 9, 20, 8, tzinfo=UTC)


def conversion(
    *,
    rate: str,
    historical: bool,
    amount: str = "2.00",
    base: str = "EUR",
    quote: str = "JPY",
) -> ConversionResult:
    effective = date(2020, 1, 2) if historical else date(2026, 9, 18)
    fx_quote = RateQuote(
        base_currency=base,
        quote_currency=quote,
        rate=Decimal(rate),
        requested_date=effective if historical else None,
        effective_date=effective,
        fetched_at=NOW,
        provider_policy=DEFAULT_SOURCE_POLICY,
        provider_keys=("ecb",),
        historical=historical,
    )
    input_amount = Decimal(amount)
    return ConversionResult(
        input_amount=input_amount,
        output_amount=convert_amount(input_amount, fx_quote, minor_units=2),
        quote=fx_quote,
        stale=False,
    )


@pytest.mark.parametrize(
    ("latest_rate", "expected_percent", "copy"),
    [
        ("110", Decimal("10.0"), "higher"),
        ("90", Decimal("-10.0"), "lower"),
        ("100", Decimal("0.0"), "same"),
    ],
)
def test_then_now_component_covers_directional_copy(latest_rate, expected_percent, copy):
    comparison = compare_historical_to_latest(
        conversion(rate="100", historical=True),
        conversion(rate=latest_rate, historical=False),
    )

    component = build_then_now_component(
        comparison,
        base_minor_units=2,
        quote_minor_units=2,
    )

    assert comparison.rate_difference_percent == expected_percent
    assert copy in component["difference_text"]
    assert component["then"]["providers"] == "ECB"
    assert component["latest"]["providers"] == "ECB"


def test_then_now_comparison_normalizes_unrepresentable_rate_difference():
    historical = ConversionResult(
        input_amount=Decimal("1"),
        output_amount=Decimal("1"),
        quote=RateQuote(
            base_currency="EUR",
            quote_currency="JPY",
            rate=Decimal("1"),
            requested_date=date(2020, 1, 2),
            effective_date=date(2020, 1, 2),
            fetched_at=NOW,
            provider_policy=DEFAULT_SOURCE_POLICY,
            provider_keys=("ecb",),
            historical=True,
        ),
        stale=False,
    )
    latest = ConversionResult(
        input_amount=Decimal("1"),
        output_amount=Decimal("1"),
        quote=RateQuote(
            base_currency="EUR",
            quote_currency="JPY",
            rate=Decimal("1E+50"),
            requested_date=None,
            effective_date=date(2026, 9, 18),
            fetched_at=NOW,
            provider_policy=DEFAULT_SOURCE_POLICY,
            provider_keys=("ecb",),
            historical=False,
        ),
        stale=False,
    )

    with pytest.raises(ConversionRepresentationError, match="display precision"):
        compare_historical_to_latest(historical, latest)


def test_rate_series_component_exposes_chart_state_and_optional_query_context():
    selected = date(2025, 1, 1)
    series = RateSeries(
        base_currency="EUR",
        quote_currency="JPY",
        start_date=date(2024, 1, 1),
        end_date=date(2026, 1, 1),
        grouping=RateSeriesGrouping.WEEK,
        points=(
            RateSeriesPoint(date(2024, 1, 1), Decimal("150.0"), ("ecb",)),
            RateSeriesPoint(selected, Decimal("170.5"), ("ecb", "fed")),
            RateSeriesPoint(date(2026, 1, 1), Decimal("160.0"), ("ecb",)),
        ),
        fetched_at=NOW,
        provider_policy=DEFAULT_SOURCE_POLICY,
    )

    then_image = ImageViewModel(
        src="/media/then.webp",
        ratio="3 / 2",
        alt="Then image",
        decorative=False,
        kind="archival_photo",
        label="Then",
        width=1200,
        height=800,
    )
    now_image = ImageViewModel(
        src="/media/now.webp",
        ratio="3 / 2",
        alt="Now image",
        decorative=False,
        kind="contemporary_photo",
        label="Now",
        width=1200,
        height=800,
    )
    timeline_image = ImageViewModel(
        src="/media/timeline.webp",
        ratio="3 / 2",
        alt="Timeline image",
        decorative=False,
        kind="archival_photo",
        label="Timeline",
        width=1200,
        height=800,
    )

    component = build_rate_series_component(
        RateSeriesResult(series=series, stale=True),
        selected_date=selected,
        requested_date=date(2025, 1, 2),
        period="5y",
        amount=Decimal("12.50"),
        then_now={"difference_percent": "2.0"},
        then_media=then_image,
        now_media=now_image,
        timeline_media=timeline_image,
        comparison_notice="Reference comparison note.",
    )

    assert component["point_count"] == 3
    assert [item["label"] for item in component["timeline_landmarks"]] == [
        "Range start",
        "Selected observation",
        "Range end",
    ]
    assert [item["rate"] for item in component["timeline_landmarks"]] == [
        "150",
        "170.5",
        "160",
    ]
    assert component["timeline_landmarks"][1]["selected"] is True
    assert component["chart_payload"]["selectedIndex"] == 1
    assert component["selected_point"]["rate"] == "170.5"
    assert component["minimum"]["rate"] == "150"
    assert component["maximum"]["rate"] == "170.5"
    assert component["last_point"]["rate"] == "160"
    assert component["providers"] == "ECB, FED"
    assert component["stale"] is True
    assert component["then_media"] is then_image
    assert component["now_media"] is now_image
    assert component["timeline_media"] is timeline_image
    assert next(item for item in component["period_links"] if item["key"] == "5y")["active"]
    assert "requested_date=2025-01-02" in component["custom_url"]
    assert "amount=12.50" in component["custom_url"]
    assert "start_date=2024-01-01" in component["custom_url"]
    assert "end_date=2026-01-01" in component["custom_url"]


def test_rate_series_component_handles_empty_series_without_inventing_values():
    selected = date(2026, 1, 1)
    series = RateSeries(
        base_currency="EUR",
        quote_currency="JPY",
        start_date=date(2025, 1, 1),
        end_date=selected,
        grouping=RateSeriesGrouping.DAILY,
        points=(),
        fetched_at=NOW,
        provider_policy=DEFAULT_SOURCE_POLICY,
    )

    component = build_rate_series_component(
        RateSeriesResult(series=series, stale=False),
        selected_date=selected,
        period="1y",
    )

    assert component["point_count"] == 0
    assert component["timeline_landmarks"] == []
    assert component["selected_point"] is None
    assert component["last_point"] is None
    assert component["minimum"] is None
    assert component["maximum"] is None
    assert component["providers"] == "Provider attribution unavailable"
    assert component["chart_payload"]["selectedIndex"] is None
    assert component["summary"] == "No published observations are available in this range."


@pytest.mark.parametrize(
    "constructor",
    [
        lambda: RateSeriesPoint(date(2025, 1, 1), "1.2"),
        lambda: RateSeriesPoint(date(2025, 1, 1), Decimal("0")),
    ],
)
def test_rate_series_point_rejects_invalid_rates(constructor):
    with pytest.raises(FxDomainError):
        constructor()


def test_rate_series_validates_structural_invariants():
    point = RateSeriesPoint(date(2025, 1, 2), Decimal("1.2"), ("ecb",))

    with pytest.raises(RateSeriesRangeError):
        RateSeries(
            "EUR",
            "JPY",
            date(2025, 1, 3),
            date(2025, 1, 2),
            RateSeriesGrouping.DAILY,
            (),
            NOW,
            DEFAULT_SOURCE_POLICY,
        )

    with pytest.raises(FxDomainError, match="grouping"):
        RateSeries(
            "EUR",
            "JPY",
            date(2025, 1, 1),
            date(2025, 1, 3),
            "daily",
            (point,),
            NOW,
            DEFAULT_SOURCE_POLICY,
        )

    with pytest.raises(FxDomainError, match="granularity"):
        RateSeries(
            "EUR",
            "JPY",
            date(2025, 1, 1),
            date(2025, 1, 3),
            RateSeriesGrouping.DAILY,
            (point,),
            NOW,
            DEFAULT_SOURCE_POLICY,
            observation_granularity="daily",
        )

    with pytest.raises(FxDomainError, match="timezone-aware"):
        RateSeries(
            "EUR",
            "JPY",
            date(2025, 1, 1),
            date(2025, 1, 3),
            RateSeriesGrouping.DAILY,
            (point,),
            datetime(2026, 9, 20, 8),
            DEFAULT_SOURCE_POLICY,
        )

    with pytest.raises(FxDomainError, match="outside requested range"):
        RateSeries(
            "EUR",
            "JPY",
            date(2025, 1, 3),
            date(2025, 1, 4),
            RateSeriesGrouping.DAILY,
            (point,),
            NOW,
            DEFAULT_SOURCE_POLICY,
        )

    duplicate = RateSeriesPoint(date(2025, 1, 2), Decimal("1.3"), ("ecb",))
    with pytest.raises(FxDomainError, match="strictly date-ordered"):
        RateSeries(
            "EUR",
            "JPY",
            date(2025, 1, 1),
            date(2025, 1, 3),
            RateSeriesGrouping.DAILY,
            (point, duplicate),
            NOW,
            DEFAULT_SOURCE_POLICY,
        )

    pinned = FxSourcePolicy(mode=ProviderPolicyMode.PINNED, provider_key="ecb")
    wrong_provider = RateSeriesPoint(date(2025, 1, 2), Decimal("1.2"), ("fed",))
    with pytest.raises(FxDomainError, match="pinned provider"):
        RateSeries(
            "EUR",
            "JPY",
            date(2025, 1, 1),
            date(2025, 1, 3),
            RateSeriesGrouping.DAILY,
            (wrong_provider,),
            NOW,
            pinned,
        )


def test_then_now_domain_validates_compatible_comparisons():
    historical = conversion(rate="100", historical=True)
    latest = conversion(rate="110", historical=False)

    with pytest.raises(FxDomainError, match="same input amount"):
        ThenNowComparison(
            historical,
            conversion(rate="110", historical=False, amount="3.00"),
            Decimal("10"),
        )

    with pytest.raises(FxDomainError, match="directional currency pair"):
        ThenNowComparison(
            historical,
            conversion(rate="110", historical=False, quote="USD"),
            Decimal("10"),
        )

    with pytest.raises(FxDomainError, match="historical side"):
        ThenNowComparison(latest, latest, Decimal("0"))

    with pytest.raises(FxDomainError, match="latest side"):
        ThenNowComparison(historical, historical, Decimal("0"))

    with pytest.raises(FxDomainError, match="finite"):
        ThenNowComparison(historical, latest, Decimal("NaN"))


def test_series_grouping_rejects_reversed_range():
    with pytest.raises(RateSeriesRangeError):
        select_rate_series_grouping(date(2026, 1, 2), date(2026, 1, 1))
