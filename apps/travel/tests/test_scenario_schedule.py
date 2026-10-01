from datetime import date

import pytest

from apps.travel.scenario_schedule import TripScheduleState, evaluate_trip_schedule


def test_unscheduled_trip_has_no_inferred_timing():
    schedule = evaluate_trip_schedule(
        start_date=None,
        end_date=None,
        as_of=date(2026, 10, 1),
    )

    assert schedule.state is TripScheduleState.UNSCHEDULED
    assert schedule.days_until_start is None
    assert schedule.days_since_end is None


def test_upcoming_trip_reports_exact_days_until_start():
    schedule = evaluate_trip_schedule(
        start_date=date(2026, 10, 8),
        end_date=date(2026, 10, 12),
        as_of=date(2026, 10, 1),
    )

    assert schedule.state is TripScheduleState.UPCOMING
    assert schedule.days_until_start == 7
    assert schedule.days_since_end is None


def test_active_trip_uses_saved_date_window_only():
    schedule = evaluate_trip_schedule(
        start_date=date(2026, 9, 30),
        end_date=date(2026, 10, 3),
        as_of=date(2026, 10, 1),
    )

    assert schedule.state is TripScheduleState.ACTIVE
    assert schedule.days_until_start is None


def test_start_only_trip_does_not_assume_an_end_date():
    schedule = evaluate_trip_schedule(
        start_date=date(2026, 9, 30),
        end_date=None,
        as_of=date(2026, 10, 1),
    )

    assert schedule.state is TripScheduleState.STARTED
    assert schedule.end_date is None


def test_ended_trip_reports_days_since_saved_end_date():
    schedule = evaluate_trip_schedule(
        start_date=date(2026, 9, 20),
        end_date=date(2026, 9, 25),
        as_of=date(2026, 10, 1),
    )

    assert schedule.state is TripScheduleState.ENDED
    assert schedule.days_since_end == 6


@pytest.mark.parametrize(
    ("start_date", "end_date", "message"),
    [
        (None, date(2026, 10, 3), "requires a start date"),
        (date(2026, 10, 4), date(2026, 10, 3), "cannot precede"),
    ],
)
def test_invalid_schedule_metadata_is_rejected(start_date, end_date, message):
    with pytest.raises(ValueError, match=message):
        evaluate_trip_schedule(
            start_date=start_date,
            end_date=end_date,
            as_of=date(2026, 10, 1),
        )
