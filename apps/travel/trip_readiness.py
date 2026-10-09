"""Opt-in, provider-free presentation of reviewed saved-trip readiness evidence."""

from __future__ import annotations

from datetime import date

from django.utils.formats import date_format

from apps.culture.services import DestinationContext


def build_trip_readiness(
    context: DestinationContext,
    *,
    as_of: date,
    travel_start_date: date | None,
    travel_end_date: date | None,
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
    calendar = context.calendar
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
        "payment_verified": (
            date_format(payment.verified_at, "j M Y") if tips and payment else ""
        ),
        "holidays": tuple(holidays),
        "calendar_window_days": calendar.window_days if calendar is not None else 30,
        "has_trip_dates": travel_start_date is not None,
    }
