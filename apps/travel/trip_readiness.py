"""Opt-in, provider-free presentation of reviewed saved-trip readiness evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from django.utils.formats import date_format

from apps.countries.models import Country
from apps.culture.calendar import CalendarContext, build_calendar_context
from apps.culture.services import DestinationContext


@dataclass(frozen=True, slots=True)
class TripCalendarReview:
    calendar: CalendarContext | None
    window_start: date
    window_end: date
    truncated: bool


def build_trip_calendar_review(
    *,
    country: Country,
    as_of: date,
    travel_start_date: date | None,
    travel_end_date: date | None,
) -> TripCalendarReview | None:
    """Inspect only published national holiday data for explicit future travel dates.

    This is a provider-free local database lookup on explicit guide refresh.
    One bounded 90-day window avoids unbounded old/future calendar claims.
    """
    if travel_start_date is None:
        return None
    start = max(as_of, travel_start_date)
    end = travel_end_date if travel_end_date is not None else travel_start_date
    if end < start:
        return None
    window_end = min(end, start + timedelta(days=90))
    window_days = max(1, (window_end - start).days)
    return TripCalendarReview(
        calendar=build_calendar_context(
            country=country,
            as_of=start,
            window_days=window_days,
            limit=6,
        ),
        window_start=start,
        window_end=window_end,
        truncated=end > window_end,
    )


def build_trip_readiness(
    context: DestinationContext,
    *,
    as_of: date,
    travel_start_date: date | None,
    travel_end_date: date | None,
    calendar_review: TripCalendarReview | None = None,
) -> dict[str, object] | None:
    """Summarize *existing* evidence without making claims about business hours.

    The canonical Money Context holiday window is relative to the review date,
    not necessarily the whole trip. Do not imply no holidays exist beyond it.
    Payment text is reviewed national guidance, never an executable card quote.
    """
    payment = context.payment
    tips: list[dict[str, str]] = []
    if payment is not None:
        for label, text in (
            ("At the card terminal", payment.dcc_warning),
            ("Cash and small purchases", payment.cash_usage),
            ("ATMs", payment.atm_notes),
        ):
            if text.strip():
                tips.append({"label": label, "text": text.strip()})
            if len(tips) >= 2:
                break

    holidays: list[dict[str, str]] = []
    calendar = calendar_review.calendar if calendar_review is not None else context.calendar
    if calendar is not None and travel_start_date is not None:
        if travel_end_date is None or travel_end_date < travel_start_date:
            travel_last_day = travel_start_date
        else:
            travel_last_day = travel_end_date
        for holiday in (*calendar.today, *calendar.upcoming):
            if travel_start_date <= holiday.date <= travel_last_day:
                holidays.append(
                    {
                        "name": holiday.name,
                        "date": date_format(holiday.date, "j M Y"),
                        "source_name": holiday.source_name,
                        "source_url": holiday.source_url,
                    }
                )
        holidays = holidays[:3]

    if not tips and not holidays:
        return None

    return {
        "country_name": context.country_name,
        "as_of": date_format(as_of, "j M Y"),
        "tips": tuple(tips),
        "payment_source": payment.source_name if tips and payment else "",
        "payment_source_url": payment.source_url if tips and payment else "",
        "payment_verified": (date_format(payment.verified_at, "j M Y") if tips and payment else ""),
        "holidays": tuple(holidays),
        "calendar_window_days": calendar.window_days if calendar is not None else 0,
        "has_calendar_evidence": calendar is not None,
        "trip_calendar_checked": calendar_review is not None,
        "trip_calendar_window_start": (
            date_format(calendar_review.window_start, "j M Y")
            if calendar_review is not None
            else ""
        ),
        "trip_calendar_window_end": (
            date_format(calendar_review.window_end, "j M Y")
            if calendar_review is not None
            else ""
        ),
        "trip_calendar_truncated": (
            calendar_review.truncated if calendar_review is not None else False
        ),
        "has_trip_dates": travel_start_date is not None,
    }
