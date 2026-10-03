from datetime import date
from decimal import Decimal

import pytest

from apps.travel.trip_budget import (
    TripBudgetDayBasis,
    calculate_trip_budget_summary,
    resolve_trip_budget_reference,
)


def test_payment_adjusted_reference_uses_saved_planning_amount_without_moving_raw_fx():
    reference = resolve_trip_budget_reference(
        budget_basis="payment_estimate",
        initial_destination_amount=Decimal("104700"),
        planning_destination_amount=Decimal("101292"),
    )

    assert reference == Decimal("101292")


def test_reference_conversion_rejects_parallel_planning_amount():
    with pytest.raises(ValueError, match="cannot carry"):
        resolve_trip_budget_reference(
            budget_basis="reference_conversion",
            initial_destination_amount=Decimal("104700"),
            planning_destination_amount=Decimal("101292"),
        )


def test_unscheduled_budget_uses_explicit_planning_duration():
    summary = calculate_trip_budget_summary(
        reference_budget=Decimal("104700"),
        confirmed_spend=Decimal("15000"),
        duration_days=5,
        travel_start_date=None,
        travel_end_date=None,
        as_of=date(2026, 10, 1),
    )

    assert summary.reference_budget == Decimal("104700")
    assert summary.confirmed_spend == Decimal("15000")
    assert summary.remaining == Decimal("89700")
    assert summary.over_reference == Decimal("0")
    assert summary.day_basis is TripBudgetDayBasis.PLAN
    assert summary.days == 5
    assert summary.remaining_per_day == Decimal("17940")
    assert summary.is_over_reference is False


def test_active_scheduled_trip_uses_inclusive_remaining_days():
    summary = calculate_trip_budget_summary(
        reference_budget=Decimal("100000"),
        confirmed_spend=Decimal("40000"),
        duration_days=10,
        travel_start_date=date(2026, 10, 1),
        travel_end_date=date(2026, 10, 5),
        as_of=date(2026, 10, 3),
    )

    assert summary.day_basis is TripBudgetDayBasis.SCHEDULE
    assert summary.days == 3
    assert summary.remaining_per_day == Decimal("20000")


def test_upcoming_schedule_uses_saved_date_window_not_mismatched_duration_assumption():
    summary = calculate_trip_budget_summary(
        reference_budget=Decimal("70000"),
        confirmed_spend=Decimal("0"),
        duration_days=3,
        travel_start_date=date(2026, 10, 10),
        travel_end_date=date(2026, 10, 16),
        as_of=date(2026, 10, 1),
    )

    assert summary.day_basis is TripBudgetDayBasis.SCHEDULE
    assert summary.days == 7
    assert summary.remaining_per_day == Decimal("10000")


def test_started_trip_without_end_does_not_infer_remaining_days_from_duration():
    summary = calculate_trip_budget_summary(
        reference_budget=Decimal("60000"),
        confirmed_spend=Decimal("10000"),
        duration_days=5,
        travel_start_date=date(2026, 10, 1),
        travel_end_date=None,
        as_of=date(2026, 10, 2),
    )

    assert summary.remaining == Decimal("50000")
    assert summary.day_basis is None
    assert summary.days is None
    assert summary.remaining_per_day is None


def test_ended_trip_keeps_remaining_amount_but_stops_per_day_projection():
    summary = calculate_trip_budget_summary(
        reference_budget=Decimal("60000"),
        confirmed_spend=Decimal("45000"),
        duration_days=5,
        travel_start_date=date(2026, 9, 20),
        travel_end_date=date(2026, 9, 24),
        as_of=date(2026, 10, 1),
    )

    assert summary.remaining == Decimal("15000")
    assert summary.day_basis is None
    assert summary.days is None
    assert summary.remaining_per_day is None


def test_spend_above_reference_is_reported_without_negative_remaining():
    summary = calculate_trip_budget_summary(
        reference_budget=Decimal("100"),
        confirmed_spend=Decimal("125"),
        duration_days=2,
        travel_start_date=None,
        travel_end_date=None,
        as_of=date(2026, 10, 1),
    )

    assert summary.remaining == Decimal("0")
    assert summary.over_reference == Decimal("25")
    assert summary.remaining_per_day == Decimal("0")
    assert summary.is_over_reference is True


@pytest.mark.parametrize(
    "kwargs",
    [
        {"reference_budget": Decimal("-1")},
        {"confirmed_spend": Decimal("-1")},
        {"duration_days": 0},
        {"duration_days": 366},
        {"travel_start_date": None, "travel_end_date": date(2026, 10, 2)},
        {
            "travel_start_date": date(2026, 10, 3),
            "travel_end_date": date(2026, 10, 2),
        },
    ],
)
def test_invalid_trip_budget_inputs_fail_closed(kwargs):
    values = {
        "reference_budget": Decimal("100"),
        "confirmed_spend": Decimal("0"),
        "duration_days": 5,
        "travel_start_date": None,
        "travel_end_date": None,
        "as_of": date(2026, 10, 1),
    }
    values.update(kwargs)

    with pytest.raises(ValueError):
        calculate_trip_budget_summary(**values)
