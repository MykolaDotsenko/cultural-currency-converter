from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal, DecimalException
from enum import StrEnum
from typing import Protocol

from django.db import DatabaseError
from django.utils import timezone

from apps.culture.services import DestinationContext, PaymentContext, TypicalPriceContext
from apps.culture.services import build_destination_context as build_destination_context_default
from apps.exchange.domain import ConversionResult
from apps.exchange.payment_estimate import (
    PaymentEstimate,
    PaymentEstimateAssumptions,
    estimate_conversion_payment_value,
)

logger = logging.getLogger("cultural_currency.exchange")


def _normalize_country_code(value: str) -> str:
    country_code = value.upper().strip()
    if country_code and (
        len(country_code) != 2 or not country_code.isascii() or not country_code.isalpha()
    ):
        raise ValueError("Money context destination country code must be two ASCII letters.")
    return country_code


class MoneyContextState(StrEnum):
    """Availability of optional destination money context for one conversion."""

    NOT_APPLICABLE = "not_applicable"
    EMPTY = "empty"
    AVAILABLE = "available"
    DEGRADED = "degraded"


@dataclass(frozen=True, slots=True)
class MoneyContext:
    """Stable application contract for trusted money meaning.

    Conversion truth remains authoritative in the conversion field.
    Destination enrichment is optional and cannot invalidate the conversion.
    """

    conversion: ConversionResult
    destination_country_code: str
    as_of: date
    destination_context: DestinationContext | None
    destination_state: MoneyContextState
    payment_estimate: PaymentEstimate | None = None

    def __post_init__(self) -> None:
        country_code = _normalize_country_code(self.destination_country_code)
        object.__setattr__(self, "destination_country_code", country_code)

        if self.destination_context is not None:
            if self.destination_context.country_code != country_code:
                raise ValueError("Money context destination country does not match enrichment.")
            if self.destination_context.as_of != self.as_of:
                raise ValueError("Money context date does not match destination enrichment.")
            if any(
                item.currency_code != self.conversion.quote.quote_currency
                for item in self.destination_context.prices
            ):
                raise ValueError("Money context price currency does not match conversion quote.")

        if self.destination_state is MoneyContextState.AVAILABLE:
            if self.destination_context is None or not self.destination_context.has_content:
                raise ValueError("Available money context requires destination content.")
        elif self.destination_state is MoneyContextState.EMPTY:
            if self.destination_context is not None and self.destination_context.has_content:
                raise ValueError("Empty money context cannot contain destination content.")
        elif self.destination_context is not None:
            raise ValueError(
                "Not-applicable or degraded money context cannot carry destination content."
            )

        if self.payment_estimate is not None:
            if not self.can_estimate_payment:
                raise ValueError("Payment estimate is not valid for this money-context conversion.")
            if self.payment_estimate.source_budget != self.conversion.input_amount:
                raise ValueError("Payment estimate source budget must match the conversion input.")
            if self.payment_estimate.reference_destination_amount != self.conversion.output_amount:
                raise ValueError(
                    "Payment estimate reference amount must match the conversion output."
                )

    @property
    def converted_amount(self) -> Decimal:
        return self.conversion.output_amount

    @property
    def quote_currency(self) -> str:
        return self.conversion.quote.quote_currency

    @property
    def local_value(self) -> tuple[TypicalPriceContext, ...]:
        if self.destination_context is None:
            return ()
        return self.destination_context.prices

    @property
    def payment_guidance(self) -> PaymentContext | None:
        if self.destination_context is None:
            return None
        return self.destination_context.payment

    @property
    def has_local_value(self) -> bool:
        return bool(self.local_value)

    @property
    def has_payment_guidance(self) -> bool:
        return self.payment_guidance is not None

    @property
    def can_estimate_payment(self) -> bool:
        return (
            not self.conversion.quote.historical
            and self.conversion.quote.base_currency != self.conversion.quote.quote_currency
        )


class DestinationContextBuilder(Protocol):
    def __call__(
        self,
        *,
        country_code: str,
        converted_amount: Decimal,
        quote_currency: str,
        as_of: date,
        price_limit: int,
    ) -> DestinationContext | None: ...


def build_money_context(
    *,
    conversion: ConversionResult,
    destination_country_code: str,
    as_of: date | None = None,
    price_limit: int = 3,
    destination_context_builder: DestinationContextBuilder | None = None,
) -> MoneyContext:
    """Compose optional destination context around a trusted conversion.

    This is deliberately fail-open for known enrichment/data failures. The
    conversion result itself is never replaced or reinterpreted.
    """

    if not 1 <= price_limit <= 6:
        raise ValueError("Money context price limit must be between 1 and 6.")

    selected_date = as_of or timezone.localdate()
    country_code = _normalize_country_code(destination_country_code)

    if conversion.quote.historical or not country_code:
        return MoneyContext(
            conversion=conversion,
            destination_country_code=country_code,
            as_of=selected_date,
            destination_context=None,
            destination_state=MoneyContextState.NOT_APPLICABLE,
        )

    builder = destination_context_builder or build_destination_context_default

    try:
        destination_context = builder(
            country_code=country_code,
            converted_amount=conversion.output_amount,
            quote_currency=conversion.quote.quote_currency,
            as_of=selected_date,
            price_limit=price_limit,
        )
    except (DatabaseError, DecimalException, ValueError) as exc:
        logger.warning(
            "money_context_destination_enrichment_unavailable",
            extra={
                "destination_country": country_code,
                "quote_currency": conversion.quote.quote_currency,
                "error_code": exc.__class__.__name__,
            },
        )
        return MoneyContext(
            conversion=conversion,
            destination_country_code=country_code,
            as_of=selected_date,
            destination_context=None,
            destination_state=MoneyContextState.DEGRADED,
        )

    state = (
        MoneyContextState.AVAILABLE
        if destination_context is not None and destination_context.has_content
        else MoneyContextState.EMPTY
    )
    try:
        return MoneyContext(
            conversion=conversion,
            destination_country_code=country_code,
            as_of=selected_date,
            destination_context=destination_context,
            destination_state=state,
        )
    except ValueError as exc:
        logger.warning(
            "money_context_destination_contract_mismatch",
            extra={
                "destination_country": country_code,
                "quote_currency": conversion.quote.quote_currency,
                "error_code": exc.__class__.__name__,
            },
        )
        return MoneyContext(
            conversion=conversion,
            destination_country_code=country_code,
            as_of=selected_date,
            destination_context=None,
            destination_state=MoneyContextState.DEGRADED,
        )


def apply_payment_assumptions(
    context: MoneyContext,
    *,
    assumptions: PaymentEstimateAssumptions,
    destination_minor_units: int,
) -> MoneyContext:
    """Return a new MoneyContext with a deterministic payment scenario attached."""

    estimate = estimate_conversion_payment_value(
        conversion=context.conversion,
        assumptions=assumptions,
        destination_minor_units=destination_minor_units,
    )
    return replace(context, payment_estimate=estimate)
