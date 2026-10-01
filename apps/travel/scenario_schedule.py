from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class TripScheduleState(StrEnum):
    UNSCHEDULED = "unscheduled"
    UPCOMING = "upcoming"
    ACTIVE = "active"
    STARTED = "started"
    ENDED = "ended"


@dataclass(frozen=True, slots=True)
class TripSchedule:
    state: TripScheduleState
    as_of: date
    start_date: date | None
    end_date: date | None
    days_until_start: int | None = None
    days_since_end: int | None = None


def evaluate_trip_schedule(
    *,
    start_date: date | None,
    end_date: date | None,
    as_of: date,
) -> TripSchedule:
    """Classify saved travel dates without inferring an itinerary."""

    if end_date is not None and start_date is None:
        raise ValueError("Trip end date requires a start date.")
    if start_date is not None and end_date is not None and end_date < start_date:
        raise ValueError("Trip end date cannot precede the start date.")

    if start_date is None:
        return TripSchedule(
            state=TripScheduleState.UNSCHEDULED,
            as_of=as_of,
            start_date=None,
            end_date=None,
        )

    if as_of < start_date:
        return TripSchedule(
            state=TripScheduleState.UPCOMING,
            as_of=as_of,
            start_date=start_date,
            end_date=end_date,
            days_until_start=(start_date - as_of).days,
        )

    if end_date is None:
        return TripSchedule(
            state=TripScheduleState.STARTED,
            as_of=as_of,
            start_date=start_date,
            end_date=None,
        )

    if as_of <= end_date:
        return TripSchedule(
            state=TripScheduleState.ACTIVE,
            as_of=as_of,
            start_date=start_date,
            end_date=end_date,
        )

    return TripSchedule(
        state=TripScheduleState.ENDED,
        as_of=as_of,
        start_date=start_date,
        end_date=end_date,
        days_since_end=(as_of - end_date).days,
    )
