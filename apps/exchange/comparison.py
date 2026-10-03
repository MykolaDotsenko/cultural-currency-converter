from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from apps.culture.services import PaymentContext
from apps.exchange.budget import (
    BudgetAssumptions,
    BudgetBasis,
    BudgetInterpretation,
    BudgetInterpretationState,
    interpret_budget,
)
from apps.exchange.domain import ConversionResult
from apps.exchange.money_context import MoneyContext, MoneyContextState


class DestinationComparisonError(ValueError):
    """Raised when two MoneyContext values cannot be compared safely."""


class DestinationComparisonState(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"


@dataclass(frozen=True, slots=True)
class DestinationComparisonSide:
    destination_country_code: str
    destination_city_slug: str
    context_as_of: date
    conversion: ConversionResult
    destination_state: MoneyContextState
    budget: BudgetInterpretation
    payment_guidance: PaymentContext | None

    @property
    def scope_key(self) -> tuple[str, str]:
        return self.destination_country_code, self.destination_city_slug

    @property
    def currency_code(self) -> str:
        return self.conversion.quote.quote_currency

    @property
    def converted_amount(self) -> Decimal:
        return self.conversion.output_amount


@dataclass(frozen=True, slots=True)
class DestinationComparison:
    source_currency_code: str
    source_amount: Decimal
    assumptions: BudgetAssumptions
    left: DestinationComparisonSide
    right: DestinationComparisonSide
    state: DestinationComparisonState
    shared_categories: tuple[str, ...]

    @property
    def coverage_complete(self) -> bool:
        return self.state is DestinationComparisonState.COMPLETE


def compare_destinations(
    left_context: MoneyContext,
    right_context: MoneyContext,
    *,
    assumptions: BudgetAssumptions,
    left_minor_units: int,
    right_minor_units: int,
) -> DestinationComparison:
    """Compare the same trusted source amount across two destination scopes.

    The comparison is deliberately descriptive. It preserves each destination's
    own currency, scope, local-price provenance and budget interpretation. It
    does not produce a winner, cost-of-living index or purchasing-power claim.
    """

    _validate_comparison_inputs(
        left_context,
        right_context,
        assumptions=assumptions,
    )

    left_budget = interpret_budget(
        left_context,
        assumptions=assumptions,
        destination_minor_units=left_minor_units,
    )
    right_budget = interpret_budget(
        right_context,
        assumptions=assumptions,
        destination_minor_units=right_minor_units,
    )

    left_categories = {line.category for line in left_budget.lines}
    right_categories = {line.category for line in right_budget.lines}
    shared_categories = tuple(
        category.category
        for category in assumptions.categories
        if category.category in left_categories and category.category in right_categories
    )

    state = (
        DestinationComparisonState.COMPLETE
        if left_budget.state is BudgetInterpretationState.COMPLETE
        and right_budget.state is BudgetInterpretationState.COMPLETE
        else DestinationComparisonState.PARTIAL
    )

    return DestinationComparison(
        source_currency_code=left_context.conversion.quote.base_currency,
        source_amount=left_context.conversion.input_amount,
        assumptions=assumptions,
        left=_build_side(left_context, left_budget),
        right=_build_side(right_context, right_budget),
        state=state,
        shared_categories=shared_categories,
    )


def _validate_comparison_inputs(
    left_context: MoneyContext,
    right_context: MoneyContext,
    *,
    assumptions: BudgetAssumptions,
) -> None:
    if assumptions.basis is not BudgetBasis.REFERENCE_CONVERSION:
        raise DestinationComparisonError(
            "Destination comparison currently requires the reference-conversion budget basis."
        )

    left_conversion = left_context.conversion
    right_conversion = right_context.conversion

    if left_conversion.quote.historical or right_conversion.quote.historical:
        raise DestinationComparisonError(
            "Current destination comparison is not defined for historical conversions."
        )

    if left_conversion.quote.base_currency != right_conversion.quote.base_currency:
        raise DestinationComparisonError(
            "Destination comparison requires the same source currency on both sides."
        )

    if left_conversion.input_amount != right_conversion.input_amount:
        raise DestinationComparisonError(
            "Destination comparison requires the same source amount on both sides."
        )

    if not left_context.destination_country_code or not right_context.destination_country_code:
        raise DestinationComparisonError(
            "Destination comparison requires country context on both sides."
        )

    left_identity = (
        left_context.destination_country_code,
        left_context.destination_city_slug,
    )
    right_identity = (
        right_context.destination_country_code,
        right_context.destination_city_slug,
    )
    if left_identity == right_identity:
        raise DestinationComparisonError("Choose two different destination scopes to compare.")


def _build_side(
    context: MoneyContext,
    budget: BudgetInterpretation,
) -> DestinationComparisonSide:
    return DestinationComparisonSide(
        destination_country_code=context.destination_country_code,
        destination_city_slug=context.destination_city_slug,
        context_as_of=context.as_of,
        conversion=context.conversion,
        destination_state=context.destination_state,
        budget=budget,
        payment_guidance=context.payment_guidance,
    )
