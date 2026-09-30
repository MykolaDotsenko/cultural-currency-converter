from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from enum import StrEnum

from apps.culture.services import TypicalPriceContext
from apps.exchange.money_context import MoneyContext


class BudgetInterpretationError(ValueError):
    """Raised when explicit budget assumptions are internally invalid."""


class BudgetBasis(StrEnum):
    REFERENCE_CONVERSION = "reference_conversion"
    PAYMENT_ESTIMATE = "payment_estimate"


class BudgetInterpretationState(StrEnum):
    COMPLETE = "complete"
    INSUFFICIENT_DATA = "insufficient_data"


class BudgetBand(StrEnum):
    BELOW_REFERENCE = "below_reference"
    WITHIN_REFERENCE = "within_reference"
    ABOVE_REFERENCE = "above_reference"


class BudgetScope(StrEnum):
    CITY = "city"
    NATIONAL = "national"


@dataclass(frozen=True, slots=True)
class BudgetCategoryAssumption:
    category: str
    units_per_person_per_day: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.category, str):
            raise BudgetInterpretationError("Budget category must be a string.")
        category = self.category.strip().lower()
        if not category:
            raise BudgetInterpretationError("Budget category cannot be empty.")
        if not isinstance(self.units_per_person_per_day, Decimal):
            raise BudgetInterpretationError("Budget category units must be a Decimal.")
        if not self.units_per_person_per_day.is_finite() or self.units_per_person_per_day <= 0:
            raise BudgetInterpretationError(
                "Budget category units must be a finite positive Decimal."
            )
        if self.units_per_person_per_day > Decimal("100"):
            raise BudgetInterpretationError(
                "Budget category units per person per day cannot exceed 100."
            )
        object.__setattr__(self, "category", category)


@dataclass(frozen=True, slots=True)
class BudgetAssumptions:
    duration_days: int
    travelers: int
    categories: tuple[BudgetCategoryAssumption, ...]
    basis: BudgetBasis = BudgetBasis.REFERENCE_CONVERSION

    def __post_init__(self) -> None:
        if isinstance(self.duration_days, bool) or not isinstance(self.duration_days, int):
            raise BudgetInterpretationError("Budget duration must be an integer number of days.")
        if not 1 <= self.duration_days <= 365:
            raise BudgetInterpretationError("Budget duration must be between 1 and 365 days.")
        if isinstance(self.travelers, bool) or not isinstance(self.travelers, int):
            raise BudgetInterpretationError("Budget traveler count must be an integer.")
        if not 1 <= self.travelers <= 20:
            raise BudgetInterpretationError("Budget traveler count must be between 1 and 20.")
        if not isinstance(self.basis, BudgetBasis):
            raise BudgetInterpretationError("Budget basis must be a BudgetBasis value.")
        if not isinstance(self.categories, tuple):
            raise BudgetInterpretationError(
                "Budget category assumptions must be an immutable tuple."
            )
        if not 1 <= len(self.categories) <= 8:
            raise BudgetInterpretationError(
                "Budget interpretation requires between 1 and 8 category assumptions."
            )

        if any(not isinstance(item, BudgetCategoryAssumption) for item in self.categories):
            raise BudgetInterpretationError(
                "Budget categories must be BudgetCategoryAssumption values."
            )

        category_names = [item.category for item in self.categories]
        if len(category_names) != len(set(category_names)):
            raise BudgetInterpretationError("Budget category assumptions must be unique.")


@dataclass(frozen=True, slots=True)
class BudgetLineEstimate:
    category: str
    label: str
    scope: BudgetScope
    scope_label: str
    city_slug: str
    currency_code: str
    units_per_person_per_day: Decimal
    per_person_daily_low: Decimal
    per_person_daily_high: Decimal
    total_low: Decimal
    total_high: Decimal
    observed_at: date
    confidence: str
    source_class: str
    source_name: str
    source_url: str


@dataclass(frozen=True, slots=True)
class BudgetInterpretation:
    basis: BudgetBasis
    state: BudgetInterpretationState
    band: BudgetBand | None
    destination_country_code: str
    destination_city_slug: str
    currency_code: str
    available_destination_budget: Decimal
    daily_budget_per_person: Decimal
    duration_days: int
    travelers: int
    known_reference_total_low: Decimal
    known_reference_total_high: Decimal
    lines: tuple[BudgetLineEstimate, ...]
    missing_categories: tuple[str, ...]

    @property
    def coverage_complete(self) -> bool:
        return self.state is BudgetInterpretationState.COMPLETE


def interpret_budget(
    context: MoneyContext,
    *,
    assumptions: BudgetAssumptions,
    destination_minor_units: int,
) -> BudgetInterpretation:
    """Interpret a trusted destination budget against explicit daily assumptions.

    The function does not infer a universal cost of living. It compares the
    available destination amount with a basket assembled only from current,
    sourced TypicalPrice context already attached to the MoneyContext.
    """

    _validate_minor_units(destination_minor_units)

    available_budget = _available_budget(context, basis=assumptions.basis)
    quantum = Decimal(1).scaleb(-destination_minor_units)
    daily_budget_per_person = (
        available_budget / Decimal(assumptions.duration_days) / Decimal(assumptions.travelers)
    ).quantize(quantum, rounding=ROUND_HALF_EVEN)

    selected_by_category = {
        price.category: price for price in available_budget_categories(context)
    }

    lines: list[BudgetLineEstimate] = []
    missing_categories: list[str] = []

    for category_assumption in assumptions.categories:
        selected_price = selected_by_category.get(category_assumption.category)
        if selected_price is None:
            missing_categories.append(category_assumption.category)
            continue
        lines.append(
            _estimate_line(
                selected_price,
                category_assumption=category_assumption,
                duration_days=assumptions.duration_days,
                travelers=assumptions.travelers,
                destination_minor_units=destination_minor_units,
                quantum=quantum,
            )
        )

    known_total_low = sum(
        (line.total_low for line in lines),
        start=Decimal("0"),
    ).quantize(quantum, rounding=ROUND_HALF_EVEN)
    known_total_high = sum(
        (line.total_high for line in lines),
        start=Decimal("0"),
    ).quantize(quantum, rounding=ROUND_HALF_EVEN)

    if missing_categories:
        state = BudgetInterpretationState.INSUFFICIENT_DATA
        band = None
    else:
        state = BudgetInterpretationState.COMPLETE
        band = _budget_band(
            available_budget=available_budget,
            reference_low=known_total_low,
            reference_high=known_total_high,
        )

    return BudgetInterpretation(
        basis=assumptions.basis,
        state=state,
        band=band,
        destination_country_code=context.destination_country_code,
        destination_city_slug=context.destination_city_slug,
        currency_code=context.quote_currency,
        available_destination_budget=available_budget.quantize(
            quantum,
            rounding=ROUND_HALF_EVEN,
        ),
        daily_budget_per_person=daily_budget_per_person,
        duration_days=assumptions.duration_days,
        travelers=assumptions.travelers,
        known_reference_total_low=known_total_low,
        known_reference_total_high=known_total_high,
        lines=tuple(lines),
        missing_categories=tuple(missing_categories),
    )


def _validate_minor_units(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise BudgetInterpretationError("Destination minor units must be an integer.")
    if not 0 <= value <= 6:
        raise BudgetInterpretationError("Destination minor units must be between 0 and 6.")


def _available_budget(context: MoneyContext, *, basis: BudgetBasis) -> Decimal:
    if context.conversion.quote.historical:
        raise BudgetInterpretationError(
            "Current budget interpretation is not defined for historical conversions."
        )

    if basis is BudgetBasis.REFERENCE_CONVERSION:
        return context.conversion.output_amount

    if context.payment_estimate is None:
        raise BudgetInterpretationError(
            "Payment-estimate budget basis requires a payment estimate on the MoneyContext."
        )
    return context.payment_estimate.estimated_destination_amount


def available_budget_categories(
    context: MoneyContext,
) -> tuple[TypicalPriceContext, ...]:
    """Return the first eligible sourced price anchor for each budget category."""

    selected: dict[str, TypicalPriceContext] = {}
    for price in _eligible_price_candidates(context):
        selected.setdefault(price.category, price)
    return tuple(selected.values())


def _eligible_price_candidates(context: MoneyContext) -> tuple[TypicalPriceContext, ...]:
    if not context.local_value:
        return ()

    if context.destination_city_slug:
        return tuple(
            price
            for price in context.local_value
            if price.city_slug == context.destination_city_slug
            or (not price.city_slug and not price.city)
        )

    # Country-level budgeting must not silently treat one city's observation as
    # representative of the whole country.
    return tuple(price for price in context.local_value if not price.city_slug and not price.city)


def _estimate_line(
    price: TypicalPriceContext,
    *,
    category_assumption: BudgetCategoryAssumption,
    duration_days: int,
    travelers: int,
    destination_minor_units: int,
    quantum: Decimal,
) -> BudgetLineEstimate:
    if price.currency_minor_units != destination_minor_units:
        raise BudgetInterpretationError(
            "Typical-price minor units do not match destination currency metadata."
        )

    high_price = price.amount_high or price.amount_low
    units = category_assumption.units_per_person_per_day

    per_person_daily_low = (price.amount_low * units).quantize(
        quantum,
        rounding=ROUND_HALF_EVEN,
    )
    per_person_daily_high = (high_price * units).quantize(
        quantum,
        rounding=ROUND_HALF_EVEN,
    )
    multiplier = Decimal(duration_days * travelers)
    total_low = (price.amount_low * units * multiplier).quantize(
        quantum,
        rounding=ROUND_HALF_EVEN,
    )
    total_high = (high_price * units * multiplier).quantize(
        quantum,
        rounding=ROUND_HALF_EVEN,
    )

    return BudgetLineEstimate(
        category=category_assumption.category,
        label=price.label,
        scope=BudgetScope.CITY if price.city_slug else BudgetScope.NATIONAL,
        scope_label=price.scope_label,
        city_slug=price.city_slug,
        currency_code=price.currency_code,
        units_per_person_per_day=units,
        per_person_daily_low=per_person_daily_low,
        per_person_daily_high=per_person_daily_high,
        total_low=total_low,
        total_high=total_high,
        observed_at=price.observed_at,
        confidence=price.confidence,
        source_class=price.source_class,
        source_name=price.source_name,
        source_url=price.source_url,
    )


def _budget_band(
    *,
    available_budget: Decimal,
    reference_low: Decimal,
    reference_high: Decimal,
) -> BudgetBand:
    if available_budget < reference_low:
        return BudgetBand.BELOW_REFERENCE
    if available_budget > reference_high:
        return BudgetBand.ABOVE_REFERENCE
    return BudgetBand.WITHIN_REFERENCE
