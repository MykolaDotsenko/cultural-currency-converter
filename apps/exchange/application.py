from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from django.utils import timezone

from apps.countries.models import Currency
from apps.countries.services import HistoricalCurrencySuggestion, historical_currency_suggestion
from apps.exchange.cache import HistoricalQuoteGateway, LatestQuoteGateway
from apps.exchange.domain import (
    ConversionRepresentationError,
    ConversionResult,
    HistoricalCurrencyMetadata,
    HistoricalObservationUnavailable,
    HistoricalOutOfCoverage,
)
from apps.exchange.money_context import MoneyContext, build_money_context
from apps.exchange.providers.base import FxProviderError, FxProviderInvalidPayload
from apps.exchange.services import quote_conversion, quote_historical_conversion

ConverterSide = Literal["source", "destination"]


@dataclass(frozen=True, slots=True)
class ConverterSubmissionCommand:
    amount: Decimal
    source_country: str
    source_currency: str
    destination_country: str
    destination_currency: str
    historical: bool = False
    requested_date: date | None = None


@dataclass(frozen=True, slots=True)
class HistoricalSuggestion:
    side: ConverterSide
    suggestion: HistoricalCurrencySuggestion


ConverterSubmissionError = (
    FxProviderError | HistoricalObservationUnavailable | HistoricalOutOfCoverage
)


@dataclass(frozen=True, slots=True)
class ConverterSubmissionResult:
    conversion: ConversionResult | None
    error: ConverterSubmissionError | None
    historical_suggestions: tuple[HistoricalSuggestion, ...]
    money_context: MoneyContext | None

    @property
    def destination_context(self):
        """Compatibility view for existing presentation consumers."""

        if self.money_context is None:
            return None
        return self.money_context.destination_context


LatestGatewayFactory = Callable[[], LatestQuoteGateway]
HistoricalGatewayFactory = Callable[[], HistoricalQuoteGateway]


def _historical_currency_metadata(currency: Currency) -> HistoricalCurrencyMetadata:
    return HistoricalCurrencyMetadata(
        code=currency.code,
        active_from=currency.active_from,
        active_to=currency.active_to,
        coverage_from=currency.coverage_from,
        coverage_to=currency.coverage_to,
        coverage_to_is_terminal=currency.coverage_to_is_terminal,
    )


def _currency_pair(command: ConverterSubmissionCommand) -> tuple[Currency, Currency]:
    currencies = Currency.objects.in_bulk(
        {command.source_currency.upper(), command.destination_currency.upper()},
        field_name="code",
    )
    source = currencies.get(command.source_currency.upper())
    destination = currencies.get(command.destination_currency.upper())
    if source is None or destination is None:
        raise ValueError("Validated converter command references missing currency metadata.")
    return source, destination


def _historical_suggestions(
    command: ConverterSubmissionCommand,
) -> tuple[HistoricalSuggestion, ...]:
    if not command.historical or command.requested_date is None:
        return ()

    suggestions: list[HistoricalSuggestion] = []
    for side in ("source", "destination"):
        suggestion = historical_currency_suggestion(
            country_code=getattr(command, f"{side}_country"),
            selected_currency_code=getattr(command, f"{side}_currency"),
            selected_date=command.requested_date,
        )
        if suggestion is not None:
            suggestions.append(HistoricalSuggestion(side=side, suggestion=suggestion))
    return tuple(suggestions)


def run_converter_submission(
    command: ConverterSubmissionCommand,
    *,
    latest_gateway_factory: LatestGatewayFactory,
    historical_gateway_factory: HistoricalGatewayFactory,
    context_as_of: date | None = None,
) -> ConverterSubmissionResult:
    """Execute one validated converter use case without depending on HTTP or templates."""

    source_currency, destination_currency = _currency_pair(command)
    historical_suggestions = _historical_suggestions(command)
    request_local_date = timezone.localdate()

    try:
        if command.historical:
            if command.requested_date is None:
                raise ValueError("Historical conversion requires requested_date.")
            conversion = quote_historical_conversion(
                amount=command.amount,
                base_currency=source_currency.code,
                quote_currency=destination_currency.code,
                quote_minor_units=destination_currency.minor_units,
                requested_date=command.requested_date,
                gateway=historical_gateway_factory,
                base_metadata=_historical_currency_metadata(source_currency),
                quote_metadata=_historical_currency_metadata(destination_currency),
                current_date=request_local_date,
            )
        else:
            conversion = quote_conversion(
                amount=command.amount,
                base_currency=source_currency.code,
                quote_currency=destination_currency.code,
                quote_minor_units=destination_currency.minor_units,
                gateway=latest_gateway_factory(),
            )
    except ConversionRepresentationError as exc:
        return ConverterSubmissionResult(
            conversion=None,
            error=FxProviderInvalidPayload(str(exc)),
            historical_suggestions=historical_suggestions,
            money_context=None,
        )
    except (FxProviderError, HistoricalObservationUnavailable, HistoricalOutOfCoverage) as exc:
        return ConverterSubmissionResult(
            conversion=None,
            error=exc,
            historical_suggestions=historical_suggestions,
            money_context=None,
        )

    money_context = build_money_context(
        conversion=conversion,
        destination_country_code=command.destination_country,
        as_of=context_as_of or request_local_date,
    )

    return ConverterSubmissionResult(
        conversion=conversion,
        error=None,
        historical_suggestions=historical_suggestions,
        money_context=money_context,
    )
