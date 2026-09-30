from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from typing import Protocol

from apps.culture.services import DestinationContext, build_destination_context
from apps.exchange.domain import ConversionResult
from apps.exchange.payment_estimate import (
    PaymentEstimate,
    PaymentEstimateAssumptions,
    estimate_conversion_payment_value,
)


class DestinationContextBuilder(Protocol):
    def __call__(
        self,
        *,
        country_code: str,
        converted_amount: Decimal,
        quote_currency: str,
        as_of: date,
    ) -> DestinationContext: ...


@dataclass(frozen=True, slots=True)
class MoneyContext:
    """Reusable application contract for money meaning around one conversion."""

    conversion: ConversionResult
    destination_country: str
    context_as_of: date
    destination: DestinationContext | None = None
    payment_estimate: PaymentEstimate | None = None

    def __post_init__(self) -> None:
        destination_country = self.destination_country.upper().strip()
        object.__setattr__(self, "destination_country", destination_country)

        if self.destination is not None:
            if self.conversion.quote.historical:
                raise ValueError(
                    "Current destination context cannot be attached to a historical conversion."
                )
            if not destination_country:
                raise ValueError(
                    "Destination context requires an explicit destination country."
                )
            if self.destination.country_code != destination_country:
                raise ValueError(
                    "Destination context country must match the money-context destination."
                )
            if self.destination.as_of != self.context_as_of:
                raise ValueError(
                    "Destination context date must match the money-context date."
                )

        if self.payment_estimate is not None:
            if self.conversion.quote.historical:
                raise ValueError(
                    "Payment estimates cannot be attached to historical money context."
                )
            if self.conversion.quote.base_currency == self.conversion.quote.quote_currency:
                raise ValueError(
                    "Payment estimates cannot be attached to same-currency money context."
                )
            if self.payment_estimate.source_budget != self.conversion.input_amount:
                raise ValueError(
                    "Payment estimate source budget must match the conversion input."
                )
            if (
                self.payment_estimate.reference_destination_amount
                != self.conversion.output_amount
            ):
                raise ValueError(
                    "Payment estimate reference amount must match the conversion output."
                )

    @property
    def has_destination_context(self) -> bool:
        return self.destination is not None and self.destination.has_content

    @property
    def prices(self):
        return self.destination.prices if self.destination is not None else ()

    @property
    def payment(self):
        return self.destination.payment if self.destination is not None else None


def compose_money_context(
    *,
    conversion: ConversionResult,
    destination_country: str,
    context_as_of: date,
    destination_context_builder: DestinationContextBuilder | None = None,
) -> MoneyContext:
    """Compose current destination meaning around a successful conversion.

    Historical and country-less conversions intentionally keep the financial
    conversion but do not attach current destination context.
    """

    country_code = destination_country.upper().strip()
    if conversion.quote.historical or not country_code:
        return MoneyContext(
            conversion=conversion,
            destination_country=country_code,
            context_as_of=context_as_of,
        )

    builder = destination_context_builder or build_destination_context
    destination = builder(
        country_code=country_code,
        converted_amount=conversion.output_amount,
        quote_currency=conversion.quote.quote_currency,
        as_of=context_as_of,
    )
    return MoneyContext(
        conversion=conversion,
        destination_country=country_code,
        context_as_of=context_as_of,
        destination=destination,
    )


def apply_payment_assumptions(
    context: MoneyContext,
    *,
    assumptions: PaymentEstimateAssumptions,
    destination_minor_units: int,
) -> MoneyContext:
    """Return a new money context with a deterministic real-payment scenario."""

    estimate = estimate_conversion_payment_value(
        conversion=context.conversion,
        assumptions=assumptions,
        destination_minor_units=destination_minor_units,
    )
    return replace(context, payment_estimate=estimate)
