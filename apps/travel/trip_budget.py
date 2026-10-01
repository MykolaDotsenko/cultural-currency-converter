from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, localcontext
from enum import StrEnum


class TripBudgetDayBasis(StrEnum):
    """Meaning of the day count used for a remaining-per-day reference."""

    PLAN = "plan"
    SCHEDULE = "schedule"


@dataclass(frozen=True, slots=True)
class TripBudgetSummary:
    reference_budget: Decimal
    confirmed_spend: Decimal
    remaining: Decimal
    over_reference: Decimal
    day_basis: TripBudgetDayBasis | None
    days: int | None
    remaining_per_day: Decimal | None

    @property
    def is_over_reference(self) -> bool:
        return self.over_reference > 0


def calculate_trip_budget_summary(
    *,
    reference_budget: Decimal,
    confirmed_spend: Decimal,
    duration_days: int | None,
    travel_start_date: date | None,
    travel_end_date: date | None,
    as_of: date,
) -> TripBudgetSummary:
    """Calculate lightweight remaining-budget meaning from explicit saved state.

    The immutable initial destination-currency observation is the reference
    budget. Later FX re-checks never move this baseline. Confirmed spend is
    subtracted in the same destination currency.
    """

    _validate_non_negative_decimal(reference_budget, label="Reference budget")
    _validate_non_negative_decimal(confirmed_spend, label="Confirmed spend")

    if duration_days is not None and not 1 <= duration_days <= 365:
        raise ValueError("Duration days must be between 1 and 365.")
    if travel_end_date is not None and travel_start_date is None:
        raise ValueError("Trip end date requires a start date.")
    if (
        travel_start_date is not None
        and travel_end_date is not None
        and travel_end_date < travel_start_date
    ):
        raise ValueError("Trip end date cannot precede the start date.")

    with localcontext() as context:
        context.prec = max(
            64,
            len(reference_budget.as_tuple().digits) + 16,
            len(confirmed_spend.as_tuple().digits) + 16,
        )
        remaining = max(reference_budget - confirmed_spend, Decimal("0"))
        over_reference = max(confirmed_spend - reference_budget, Decimal("0"))

        day_basis: TripBudgetDayBasis | None = None
        days: int | None = None

        if travel_start_date is not None and travel_end_date is not None:
            if as_of <= travel_end_date:
                period_start = max(as_of, travel_start_date)
                days = (travel_end_date - period_start).days + 1
                day_basis = TripBudgetDayBasis.SCHEDULE
        elif duration_days is not None and (
            travel_start_date is None or as_of < travel_start_date
        ):
            days = duration_days
            day_basis = TripBudgetDayBasis.PLAN

        remaining_per_day = None
        if days is not None and days > 0:
            remaining_per_day = remaining / Decimal(days)

    return TripBudgetSummary(
        reference_budget=reference_budget,
        confirmed_spend=confirmed_spend,
        remaining=remaining,
        over_reference=over_reference,
        day_basis=day_basis,
        days=days,
        remaining_per_day=remaining_per_day,
    )


def _validate_non_negative_decimal(value: Decimal, *, label: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
        raise ValueError(f"{label} must be a finite non-negative Decimal.")
