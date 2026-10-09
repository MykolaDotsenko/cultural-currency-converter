from __future__ import annotations

from urllib.parse import urlencode

from django.urls import reverse
from django.utils.formats import date_format

from apps.common.presentation.media_view_models import ImageViewModel
from apps.exchange.domain import RateSeriesResult, ThenNowComparison


def _rate_text(value) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _series_url(
    *,
    base: str,
    quote: str,
    selected_date,
    requested_date,
    period: str,
    amount=None,
    start_date=None,
    end_date=None,
) -> str:
    params = {
        "base": base,
        "quote": quote,
        "selected_date": selected_date.isoformat(),
        "period": period,
    }
    if requested_date is not None:
        params["requested_date"] = requested_date.isoformat()
    if amount is not None:
        params["amount"] = format(amount, "f")
    if start_date is not None:
        params["start_date"] = start_date.isoformat()
    if end_date is not None:
        params["end_date"] = end_date.isoformat()
    return f"{reverse('historical_series')}?{urlencode(params)}"


def build_then_now_component(
    comparison: ThenNowComparison,
    *,
    base_minor_units: int,
    quote_minor_units: int,
) -> dict[str, object]:
    historical = comparison.historical
    latest = comparison.latest
    difference = comparison.rate_difference_percent
    magnitude = abs(difference)
    input_text = f"{historical.input_amount:.{base_minor_units}f}"
    historical_output = f"{historical.output_amount:.{quote_minor_units}f}"
    latest_output = f"{latest.output_amount:.{quote_minor_units}f}"
    if difference > 0:
        difference_text = (
            f"The {latest.quote.quote_currency} amount per {input_text} "
            f"{latest.quote.base_currency} is about {magnitude}% higher in the latest "
            "reference rate than in the selected historical observation."
        )
    elif difference < 0:
        difference_text = (
            f"The {latest.quote.quote_currency} amount per {input_text} "
            f"{latest.quote.base_currency} is about {magnitude}% lower in the latest "
            "reference rate than in the selected historical observation."
        )
    else:
        difference_text = (
            f"The latest and selected historical reference rates produce the same "
            f"{latest.quote.quote_currency} amount per {input_text} "
            f"{latest.quote.base_currency} at this display precision."
        )

    return {
        "input_amount": input_text,
        "base_currency": historical.quote.base_currency,
        "quote_currency": historical.quote.quote_currency,
        "then": {
            "date_label": date_format(historical.quote.effective_date, "j M Y"),
            "output_amount": historical_output,
            "rate": _rate_text(historical.quote.rate),
            "providers": ", ".join(key.upper() for key in historical.quote.provider_keys),
        },
        "latest": {
            "date_label": date_format(latest.quote.effective_date, "j M Y"),
            "output_amount": latest_output,
            "rate": _rate_text(latest.quote.rate),
            "providers": ", ".join(key.upper() for key in latest.quote.provider_keys),
            "stale": latest.stale,
        },
        "difference_percent": _rate_text(difference),
        "difference_text": difference_text,
    }


def _timeline_landmarks(points, selected_date) -> list[dict[str, object]]:
    if not points:
        return []

    landmarks = []
    last_index = len(points) - 1
    for index, point in enumerate(points):
        roles = []
        if index == 0:
            roles.append("Range start")
        if point.observation_date == selected_date:
            roles.append("Selected observation")
        if index == last_index:
            roles.append("Range end")
        if not roles:
            continue
        landmarks.append(
            {
                "label": " · ".join(roles),
                "date": point.observation_date,
                "date_label": date_format(point.observation_date, "j M Y"),
                "date_iso": point.observation_date.isoformat(),
                "rate": _rate_text(point.rate),
                "selected": point.observation_date == selected_date,
                "provider_keys": ", ".join(key.upper() for key in point.provider_keys),
            }
        )
    return landmarks


def build_rate_series_component(
    result: RateSeriesResult,
    *,
    selected_date,
    requested_date=None,
    period: str,
    amount=None,
    then_now: dict[str, object] | None = None,
    then_media: ImageViewModel | None = None,
    now_media: ImageViewModel | None = None,
    timeline_media: ImageViewModel | None = None,
    comparison_notice: str | None = None,
) -> dict[str, object]:
    series = result.series
    points = [
        {
            "date": point.observation_date,
            "date_label": date_format(point.observation_date, "j M Y"),
            "date_iso": point.observation_date.isoformat(),
            "rate": _rate_text(point.rate),
            "selected": point.observation_date == selected_date,
            "provider_keys": ", ".join(key.upper() for key in point.provider_keys),
        }
        for point in series.points
    ]

    minimum = series.minimum_point
    maximum = series.maximum_point
    last = series.points[-1] if series.points else None
    selected_point = next(
        (point for point in series.points if point.observation_date == selected_date),
        None,
    )
    provider_keys = sorted({key.upper() for point in series.points for key in point.provider_keys})

    # A historical observation is only a source-backed navigation starting point.
    # Never embed an observed rate in the URL: the converter must independently
    # validate the pair, amount and historical date on the user's explicit request.
    historical_replay_url = None
    if selected_point is not None and amount is not None:
        replay_params = {
            "convert": "1",
            "rate_mode": "historical",
            "requested_date": selected_point.observation_date.isoformat(),
            "source_country": "",
            "source_currency": series.base_currency,
            "destination_country": "",
            "destination_currency": series.quote_currency,
            "amount": format(amount, "f"),
        }
        historical_replay_url = f"{reverse('converter')}?{urlencode(replay_params)}"

    period_links = []
    for key, label in (("1y", "1Y"), ("5y", "5Y"), ("10y", "10Y")):
        period_links.append(
            {
                "key": key,
                "label": label,
                "active": period == key,
                "url": _series_url(
                    base=series.base_currency,
                    quote=series.quote_currency,
                    selected_date=selected_date,
                    requested_date=requested_date,
                    period=key,
                    amount=amount,
                ),
            }
        )

    summary = (
        "No published observations are available in this range."
        if not series.points
        else (
            f"{len(series.points)} published observations from "
            f"{date_format(series.points[0].observation_date, 'j M Y')} to "
            f"{date_format(series.points[-1].observation_date, 'j M Y')}. "
            f"The observed range was {_rate_text(minimum.rate)} to "
            f"{_rate_text(maximum.rate)} {series.quote_currency} per "
            f"{series.base_currency}."
        )
    )

    return {
        "id": "historical-trend",
        "pair": f"{series.base_currency} → {series.quote_currency}",
        "base_currency": series.base_currency,
        "quote_currency": series.quote_currency,
        "selected_date": selected_date,
        "selected_date_label": date_format(selected_date, "j M Y"),
        "requested_date": requested_date,
        "requested_date_label": (
            date_format(requested_date, "j M Y") if requested_date is not None else None
        ),
        "period": period,
        "period_links": period_links,
        "amount": format(amount, "f") if amount is not None else None,
        "start_date": series.start_date,
        "start_date_iso": series.start_date.isoformat(),
        "end_date": series.end_date,
        "end_date_iso": series.end_date.isoformat(),
        "grouping": series.grouping.value.capitalize(),
        "observation_granularity": series.observation_granularity.value.capitalize(),
        "stale": result.stale,
        "points": points,
        "point_count": len(points),
        "timeline_landmarks": _timeline_landmarks(series.points, selected_date),
        "chart_payload": {
            "pair": f"{series.base_currency} → {series.quote_currency}",
            "baseCurrency": series.base_currency,
            "quoteCurrency": series.quote_currency,
            "selectedDate": selected_date.isoformat(),
            "labels": [point["date_label"] for point in points],
            "dates": [point["date_iso"] for point in points],
            "rates": [point["rate"] for point in points],
            "selectedIndex": next(
                (index for index, point in enumerate(points) if point["selected"]),
                None,
            ),
        },
        "then_now": then_now,
        "then_media": then_media if then_now is not None else None,
        "now_media": now_media if then_now is not None else None,
        "timeline_media": timeline_media,
        "comparison_notice": comparison_notice,
        "historical_replay_url": historical_replay_url,
        "selected_point": (
            {
                "date_label": date_format(selected_point.observation_date, "j M Y"),
                "rate": _rate_text(selected_point.rate),
            }
            if selected_point is not None
            else None
        ),
        "last_point": (
            {
                "date_label": date_format(last.observation_date, "j M Y"),
                "rate": _rate_text(last.rate),
            }
            if last is not None
            else None
        ),
        "minimum": (
            {
                "date_label": date_format(minimum.observation_date, "j M Y"),
                "rate": _rate_text(minimum.rate),
            }
            if minimum is not None
            else None
        ),
        "maximum": (
            {
                "date_label": date_format(maximum.observation_date, "j M Y"),
                "rate": _rate_text(maximum.rate),
            }
            if maximum is not None
            else None
        ),
        "providers": ", ".join(provider_keys) or "Provider attribution unavailable",
        "summary": summary,
        "custom_url": _series_url(
            base=series.base_currency,
            quote=series.quote_currency,
            selected_date=selected_date,
            requested_date=requested_date,
            period="custom",
            amount=amount,
            start_date=series.start_date,
            end_date=series.end_date,
        ),
    }
