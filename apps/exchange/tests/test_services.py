from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from apps.exchange.domain import (
    DEFAULT_SOURCE_POLICY,
    FxDomainError,
    HistoricalCoverageReason,
    HistoricalCurrencyMetadata,
    HistoricalDateError,
    HistoricalOutOfCoverage,
    RateQuote,
)
from apps.exchange.services import quote_conversion, quote_historical_conversion


class ExplodingGateway:
    def get(self, *args, **kwargs):
        raise AssertionError("same-currency conversion must not call the provider gateway")


def test_same_currency_fast_path_uses_exact_one_without_provider():
    result = quote_conversion(
        amount=Decimal("12.345"),
        base_currency="EUR",
        quote_currency="EUR",
        quote_minor_units=2,
        gateway=ExplodingGateway(),
        now=datetime(2026, 9, 20, tzinfo=UTC),
    )

    assert result.quote.rate == Decimal("1")
    assert result.output_amount == Decimal("12.34")
    assert result.stale is False


@pytest.mark.parametrize("base_currency", ["EU", "EUR/USD", "€UR", "ΕUR"])
def test_invalid_currency_syntax_is_rejected_before_gateway(base_currency):
    with pytest.raises(FxDomainError):
        quote_conversion(
            amount=Decimal("10"),
            base_currency=base_currency,
            quote_currency="JPY",
            quote_minor_units=0,
            gateway=ExplodingGateway(),
            now=datetime(2026, 9, 20, tzinfo=UTC),
        )


class HistoricalExplodingGateway:
    def get(self, *args, **kwargs):
        raise AssertionError(
            "historical same-currency conversion must not call the provider gateway"
        )


class HistoricalGateway:
    def __init__(self, quote):
        self.quote = quote
        self.calls = []

    def get(self, base, quote, requested_date, policy):
        self.calls.append((base, quote, requested_date, policy))
        return self.quote


def test_historical_same_currency_preserves_requested_and_effective_date_without_provider():
    requested = date(1998, 6, 15)
    result = quote_historical_conversion(
        amount=Decimal("12.345"),
        base_currency="FIM",
        quote_currency="FIM",
        quote_minor_units=2,
        requested_date=requested,
        gateway=HistoricalExplodingGateway(),
        now=datetime(2026, 9, 20, tzinfo=UTC),
    )

    assert result.quote.rate == Decimal("1")
    assert result.quote.historical is True
    assert result.quote.requested_date == requested
    assert result.quote.effective_date == requested
    assert result.output_amount == Decimal("12.34")


def test_historical_future_date_is_rejected_before_gateway():
    with pytest.raises(HistoricalDateError):
        quote_historical_conversion(
            amount=Decimal("10"),
            base_currency="EUR",
            quote_currency="JPY",
            quote_minor_units=0,
            requested_date=date(2026, 9, 21),
            gateway=HistoricalExplodingGateway(),
            now=datetime(2026, 9, 20, tzinfo=UTC),
        )


def test_historical_local_today_can_be_ahead_of_utc_date():
    requested = date(2026, 9, 21)
    result = quote_historical_conversion(
        amount=Decimal("10"),
        base_currency="EUR",
        quote_currency="EUR",
        quote_minor_units=2,
        requested_date=requested,
        gateway=HistoricalExplodingGateway(),
        now=datetime(2026, 9, 20, 21, 30, tzinfo=UTC),
        current_date=date(2026, 9, 21),
    )

    assert result.quote.requested_date == requested
    assert result.quote.effective_date == requested
    assert result.output_amount == Decimal("10.00")


def test_historical_date_after_explicit_local_today_is_rejected():
    with pytest.raises(HistoricalDateError):
        quote_historical_conversion(
            amount=Decimal("10"),
            base_currency="EUR",
            quote_currency="JPY",
            quote_minor_units=0,
            requested_date=date(2026, 9, 22),
            gateway=HistoricalExplodingGateway(),
            now=datetime(2026, 9, 20, 21, 30, tzinfo=UTC),
            current_date=date(2026, 9, 21),
        )


def test_historical_conversion_uses_gateway_quote():
    requested = date(2026, 9, 18)
    quote = RateQuote(
        base_currency="EUR",
        quote_currency="JPY",
        rate=Decimal("174.5"),
        requested_date=requested,
        effective_date=requested,
        fetched_at=datetime(2026, 9, 20, tzinfo=UTC),
        provider_policy=DEFAULT_SOURCE_POLICY,
        provider_keys=("ecb",),
        historical=True,
    )
    gateway = HistoricalGateway(quote)

    result = quote_historical_conversion(
        amount=Decimal("10"),
        base_currency="EUR",
        quote_currency="JPY",
        quote_minor_units=0,
        requested_date=requested,
        gateway=gateway,
        now=datetime(2026, 9, 20, tzinfo=UTC),
    )

    assert result.output_amount == Decimal("1745")
    assert gateway.calls == [("EUR", "JPY", requested, DEFAULT_SOURCE_POLICY)]


@pytest.mark.parametrize(
    ("metadata", "requested", "reason"),
    [
        (
            HistoricalCurrencyMetadata(code="FIM", active_from=date(1963, 1, 1)),
            date(1962, 12, 31),
            HistoricalCoverageReason.CURRENCY_NOT_YET_ACTIVE,
        ),
        (
            HistoricalCurrencyMetadata(code="FIM", active_to=date(2001, 12, 31)),
            date(2002, 1, 1),
            HistoricalCoverageReason.CURRENCY_RETIRED,
        ),
        (
            HistoricalCurrencyMetadata(code="FIM", coverage_from=date(1972, 1, 1)),
            date(1971, 12, 31),
            HistoricalCoverageReason.PROVIDER_COVERAGE_NOT_STARTED,
        ),
        (
            HistoricalCurrencyMetadata(
                code="FIM",
                coverage_to=date(2001, 12, 31),
                coverage_to_is_terminal=True,
            ),
            date(2002, 1, 1),
            HistoricalCoverageReason.PROVIDER_COVERAGE_ENDED,
        ),
    ],
)
def test_historical_known_bounds_fail_before_gateway(metadata, requested, reason):
    with pytest.raises(HistoricalOutOfCoverage) as captured:
        quote_historical_conversion(
            amount=Decimal("10"),
            base_currency="FIM",
            quote_currency="JPY",
            quote_minor_units=0,
            requested_date=requested,
            gateway=HistoricalExplodingGateway(),
            base_metadata=metadata,
            now=datetime(2026, 9, 20, tzinfo=UTC),
        )

    assert captured.value.reason is reason


def test_latest_observation_date_is_not_treated_as_terminal_coverage():
    requested = date(2026, 9, 20)
    quote = RateQuote(
        base_currency="EUR",
        quote_currency="JPY",
        rate=Decimal("174.5"),
        requested_date=requested,
        effective_date=date(2026, 9, 18),
        fetched_at=datetime(2026, 9, 20, tzinfo=UTC),
        provider_policy=DEFAULT_SOURCE_POLICY,
        provider_keys=("ecb",),
        historical=True,
    )
    gateway = HistoricalGateway(quote)

    result = quote_historical_conversion(
        amount=Decimal("10"),
        base_currency="EUR",
        quote_currency="JPY",
        quote_minor_units=0,
        requested_date=requested,
        gateway=gateway,
        base_metadata=HistoricalCurrencyMetadata(
            code="EUR",
            coverage_to=date(2026, 9, 18),
            coverage_to_is_terminal=False,
        ),
        now=datetime(2026, 9, 20, tzinfo=UTC),
    )

    assert result.quote.effective_date == date(2026, 9, 18)
