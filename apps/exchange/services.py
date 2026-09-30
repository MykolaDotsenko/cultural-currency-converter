from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_EVEN, Decimal

from apps.exchange.cache import HistoricalQuoteGateway, HistoricalSeriesGateway, LatestQuoteGateway
from apps.exchange.domain import (
    DEFAULT_SOURCE_POLICY,
    ConversionResult,
    FxDomainError,
    FxSourcePolicy,
    HistoricalCurrencyMetadata,
    HistoricalDateError,
    RateSeriesGrouping,
    RateSeriesRangeError,
    RateSeriesResult,
    ThenNowComparison,
    convert_amount,
    normalize_currency_code,
    same_currency_quote,
    validate_historical_currency_metadata,
)


def quote_conversion(
    *,
    amount: Decimal,
    base_currency: str,
    quote_currency: str,
    quote_minor_units: int,
    gateway: LatestQuoteGateway,
    policy: FxSourcePolicy = DEFAULT_SOURCE_POLICY,
    now: datetime | None = None,
) -> ConversionResult:
    current_time = now or datetime.now(UTC)
    base_code = normalize_currency_code(base_currency)
    quote_code = normalize_currency_code(quote_currency)
    if base_code == quote_code:
        quote = same_currency_quote(base_code, fetched_at=current_time)
        return ConversionResult(
            input_amount=amount,
            output_amount=convert_amount(amount, quote, minor_units=quote_minor_units),
            quote=quote,
            stale=False,
        )

    quote, stale = gateway.get(base_code, quote_code, policy, now=current_time)
    return ConversionResult(
        input_amount=amount,
        output_amount=convert_amount(amount, quote, minor_units=quote_minor_units),
        quote=quote,
        stale=stale,
    )


def quote_historical_conversion(
    *,
    amount: Decimal,
    base_currency: str,
    quote_currency: str,
    quote_minor_units: int,
    requested_date: date,
    gateway: HistoricalQuoteGateway | Callable[[], HistoricalQuoteGateway],
    base_metadata: HistoricalCurrencyMetadata | None = None,
    quote_metadata: HistoricalCurrencyMetadata | None = None,
    policy: FxSourcePolicy = DEFAULT_SOURCE_POLICY,
    now: datetime | None = None,
    current_date: date | None = None,
) -> ConversionResult:
    current_time = now or datetime.now(UTC)
    validation_date = current_date or current_time.date()
    if requested_date > validation_date:
        raise HistoricalDateError("Historical date cannot be in the future.")

    if base_metadata is not None:
        validate_historical_currency_metadata(base_metadata, requested_date)
    if quote_metadata is not None:
        validate_historical_currency_metadata(quote_metadata, requested_date)

    base_code = normalize_currency_code(base_currency)
    quote_code = normalize_currency_code(quote_currency)
    if base_code == quote_code:
        quote = same_currency_quote(
            base_code,
            fetched_at=current_time,
            requested_date=requested_date,
        )
        return ConversionResult(
            input_amount=amount,
            output_amount=convert_amount(amount, quote, minor_units=quote_minor_units),
            quote=quote,
            stale=False,
        )

    resolved_gateway = gateway() if callable(gateway) else gateway
    quote = resolved_gateway.get(base_code, quote_code, requested_date, policy)
    return ConversionResult(
        input_amount=amount,
        output_amount=convert_amount(amount, quote, minor_units=quote_minor_units),
        quote=quote,
        stale=False,
    )


MAX_RATE_SERIES_DAYS = 10 * 366
DAILY_SERIES_MAX_DAYS = 366
WEEKLY_SERIES_MAX_DAYS = 5 * 366


def select_rate_series_grouping(start_date: date, end_date: date) -> RateSeriesGrouping:
    if end_date < start_date:
        raise RateSeriesRangeError("FX series end date cannot precede start date.")
    span_days = (end_date - start_date).days
    if span_days <= DAILY_SERIES_MAX_DAYS:
        return RateSeriesGrouping.DAILY
    if span_days <= WEEKLY_SERIES_MAX_DAYS:
        return RateSeriesGrouping.WEEK
    return RateSeriesGrouping.MONTH


def get_rate_series(
    *,
    base_currency: str,
    quote_currency: str,
    start_date: date,
    end_date: date,
    gateway: HistoricalSeriesGateway | Callable[[], HistoricalSeriesGateway],
    grouping: RateSeriesGrouping | None = None,
    policy: FxSourcePolicy = DEFAULT_SOURCE_POLICY,
    now: datetime | None = None,
    current_date: date | None = None,
) -> RateSeriesResult:
    current_time = now or datetime.now(UTC)
    validation_date = current_date or current_time.date()
    if end_date < start_date:
        raise RateSeriesRangeError("FX series end date cannot precede start date.")
    if end_date > validation_date:
        raise RateSeriesRangeError("FX series end date cannot be in the future.")
    if (end_date - start_date).days > MAX_RATE_SERIES_DAYS:
        raise RateSeriesRangeError(
            f"FX series range cannot exceed {MAX_RATE_SERIES_DAYS} calendar days."
        )

    base_code = normalize_currency_code(base_currency)
    quote_code = normalize_currency_code(quote_currency)
    resolved_grouping = grouping or select_rate_series_grouping(start_date, end_date)
    resolved_gateway = gateway() if callable(gateway) else gateway
    series, stale = resolved_gateway.get(
        base_code,
        quote_code,
        start_date,
        end_date,
        resolved_grouping,
        policy,
        now=current_time,
    )
    return RateSeriesResult(series=series, stale=stale)


def compare_historical_to_latest(
    historical: ConversionResult,
    latest: ConversionResult,
) -> ThenNowComparison:
    if historical.quote.rate <= 0:
        raise FxDomainError("Historical comparison rate must be positive.")
    percent = (
        (latest.quote.rate - historical.quote.rate) / historical.quote.rate * Decimal("100")
    ).quantize(Decimal("0.1"), rounding=ROUND_HALF_EVEN)
    return ThenNowComparison(
        historical=historical,
        latest=latest,
        rate_difference_percent=percent,
    )
