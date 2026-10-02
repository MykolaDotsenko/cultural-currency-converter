from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from apps.exchange.money_context import MoneyContext


class SameAmountDestinationsError(ValueError):
    """Raised when multi-destination snapshots cannot be composed safely."""


@dataclass(frozen=True, slots=True)
class SameAmountDestinationSnapshot:
    token: str
    scope_label: str
    country_code: str
    city_slug: str
    currency_code: str
    minor_units: int
    context: MoneyContext

    @property
    def converted_amount(self) -> Decimal:
        return self.context.conversion.output_amount


@dataclass(frozen=True, slots=True)
class SameAmountAcrossDestinations:
    source_amount: Decimal
    source_currency_code: str
    destinations: tuple[SameAmountDestinationSnapshot, ...]

    def __post_init__(self) -> None:
        if not 1 <= len(self.destinations) <= 4:
            raise SameAmountDestinationsError(
                "Same-amount results require between one and four successful destinations."
            )

        seen_scopes: set[tuple[str, str]] = set()
        for item in self.destinations:
            conversion = item.context.conversion
            if conversion.quote.historical:
                raise SameAmountDestinationsError(
                    "Same-amount destination snapshots require current conversions."
                )
            if conversion.input_amount != self.source_amount:
                raise SameAmountDestinationsError(
                    "Every destination must use the same source amount."
                )
            if conversion.quote.base_currency != self.source_currency_code:
                raise SameAmountDestinationsError(
                    "Every destination must use the same source currency."
                )
            if conversion.quote.quote_currency != item.currency_code:
                raise SameAmountDestinationsError(
                    "Destination currency does not match its trusted conversion."
                )
            if item.context.destination_country_code != item.country_code:
                raise SameAmountDestinationsError(
                    "Destination country does not match its money context."
                )
            if item.context.destination_city_slug != item.city_slug:
                raise SameAmountDestinationsError(
                    "Destination city does not match its money context."
                )

            scope = (item.country_code, item.city_slug)
            if scope in seen_scopes:
                raise SameAmountDestinationsError(
                    "Same-amount results cannot contain duplicate destination scopes."
                )
            seen_scopes.add(scope)


def compose_same_amount_across_destinations(
    destinations: tuple[SameAmountDestinationSnapshot, ...],
) -> SameAmountAcrossDestinations:
    """Compose successful destination snapshots without ranking or reordering them."""

    if not destinations:
        raise SameAmountDestinationsError(
            "At least one successful destination snapshot is required."
        )

    first = destinations[0].context.conversion
    return SameAmountAcrossDestinations(
        source_amount=first.input_amount,
        source_currency_code=first.quote.base_currency,
        destinations=destinations,
    )
