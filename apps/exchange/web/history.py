from __future__ import annotations

import logging
from decimal import Decimal
from typing import TYPE_CHECKING

from django.db import DatabaseError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.cache import patch_vary_headers
from django.views.decorators.http import require_GET

from apps.countries.models import Currency
from apps.exchange.domain import (
    ConversionRepresentationError,
    ConversionResult,
    HistoricalObservationUnavailable,
    HistoricalOutOfCoverage,
    RateQuote,
    RateSeriesRangeError,
    convert_amount,
)
from apps.exchange.forms import HistoricalSeriesForm
from apps.exchange.providers.base import (
    FxProviderError,
    FxProviderInvalidPayload,
    FxProviderUnsupportedPair,
)
from apps.exchange.series_presentation import (
    build_rate_series_component,
    build_then_now_component,
)
from apps.exchange.web.common import is_htmx
from apps.media.models import MediaRole
from apps.media.presentation import select_media_for_display

if TYPE_CHECKING:
    from apps.common.presentation.media_view_models import ImageViewModel

logger = logging.getLogger("cultural_currency.exchange")


def _select_then_media(
    *,
    quote_currency: Currency | None,
    selected_date,
) -> ImageViewModel | None:
    if quote_currency is None:
        return None
    try:
        selection = select_media_for_display(
            role=MediaRole.COMPARISON_THEN,
            currency=quote_currency,
            target_date=selected_date,
            aspect_ratio="3 / 2",
        )
    except (DatabaseError, ValueError) as exc:
        logger.warning(
            "Historical comparison media lookup failed",
            extra={
                "exchange.currency": quote_currency.code,
                "error_code": exc.__class__.__name__,
            },
        )
        return None
    return selection.image if selection is not None else None


def _build_then_now_enrichment(
    cleaned,
    series_result,
    *,
    base_currency: Currency | None,
    quote_currency: Currency | None,
    latest_gateway_factory,
    quote_conversion_fn,
    compare_historical_to_latest_fn,
):
    if base_currency is None or quote_currency is None:
        return None, "Latest comparison is unavailable because currency metadata is incomplete."

    amount = cleaned.get("amount_decimal")
    comparison_amount_error = cleaned.get("comparison_amount_error")

    historical_amount = amount if amount is not None else Decimal("1")
    requested_date = cleaned.get("requested_date") or cleaned["selected_date"]
    exact_series_point = next(
        (
            point
            for point in series_result.series.points
            if point.observation_date == cleaned["selected_date"]
        ),
        None,
    )
    if exact_series_point is None:
        return (
            None,
            "Then & Now comparison is unavailable because the selected observation "
            "is not present in the loaded series.",
        )

    historical_quote = RateQuote(
        base_currency=series_result.series.base_currency,
        quote_currency=series_result.series.quote_currency,
        rate=exact_series_point.rate,
        requested_date=requested_date,
        effective_date=exact_series_point.observation_date,
        fetched_at=series_result.series.fetched_at,
        provider_policy=series_result.series.provider_policy,
        provider_keys=exact_series_point.provider_keys,
        historical=True,
        observation_granularity=series_result.series.observation_granularity,
    )
    try:
        historical_output = convert_amount(
            historical_amount,
            historical_quote,
            minor_units=quote_currency.minor_units,
        )
    except ConversionRepresentationError:
        return (
            None,
            "Then & Now comparison is unavailable because the selected reference rate "
            "cannot be represented safely. The historical trend remains valid.",
        )

    historical = ConversionResult(
        input_amount=historical_amount,
        output_amount=historical_output,
        quote=historical_quote,
        stale=series_result.stale,
    )

    if comparison_amount_error:
        return None, comparison_amount_error
    if amount is None:
        return None, None

    inactive = [
        currency.code for currency in (base_currency, quote_currency) if not currency.is_active
    ]
    if inactive:
        codes = ", ".join(inactive)
        return (
            None,
            f"Latest reference comparison is not shown because {codes} is archived "
            "and has no current-market interpretation.",
        )

    try:
        latest = quote_conversion_fn(
            amount=amount,
            base_currency=cleaned["base"],
            quote_currency=cleaned["quote"],
            quote_minor_units=quote_currency.minor_units,
            gateway=latest_gateway_factory(),
        )
    except FxProviderError:
        return (
            None,
            "Latest reference comparison is temporarily unavailable. "
            "The historical trend remains valid.",
        )
    except ConversionRepresentationError:
        return (
            None,
            "Then & Now comparison is unavailable because the latest reference amount "
            "cannot be represented safely. The historical trend remains valid.",
        )

    try:
        comparison = compare_historical_to_latest_fn(historical, latest)
    except ConversionRepresentationError:
        return (
            None,
            "Then & Now comparison is unavailable because the rate difference "
            "cannot be represented safely. The historical trend remains valid.",
        )
    return (
        build_then_now_component(
            comparison,
            base_minor_units=base_currency.minor_units,
            quote_minor_units=quote_currency.minor_units,
        ),
        None,
    )


def _series_error(exc: Exception) -> tuple[int, dict[str, str]]:
    if isinstance(exc, HistoricalObservationUnavailable):
        return 422, {
            "title": "Historical trend cannot confirm the selected observation.",
            "detail": (
                "The selected observation falls outside the accepted observation window. "
                "The original single-date conversion remains intact."
            ),
        }
    if isinstance(exc, (RateSeriesRangeError, HistoricalOutOfCoverage)):
        return 422, {
            "title": "Choose a supported historical range.",
            "detail": str(exc),
        }
    if isinstance(exc, FxProviderUnsupportedPair):
        return 422, {
            "title": "Historical series is unavailable for this pair.",
            "detail": "Single-date conversion remains available when the selected observation is supported.",
        }
    if isinstance(exc, FxProviderInvalidPayload):
        return 502, {
            "title": "The rate source returned unusable historical series data.",
            "detail": "Single-date conversion remains intact. Try the trend again later.",
        }
    return 503, {
        "title": "Historical series is unavailable.",
        "detail": "Single-date conversion remains intact. Try the trend again later.",
    }


@require_GET
def historical_series_view(
    request: HttpRequest,
    *,
    series_gateway_factory,
    latest_gateway_factory,
    get_rate_series_fn,
    quote_conversion_fn,
    compare_historical_to_latest_fn,
) -> HttpResponse:
    form = HistoricalSeriesForm(request.GET)
    component = None
    error = None
    response_status = 200

    if form.is_valid():
        cleaned = form.cleaned_data
        try:
            result = get_rate_series_fn(
                base_currency=cleaned["base"],
                quote_currency=cleaned["quote"],
                start_date=cleaned["start_date_resolved"],
                end_date=cleaned["end_date_resolved"],
                gateway=series_gateway_factory,
                current_date=timezone.localdate(),
            )
            currencies = {
                currency.code: currency
                for currency in Currency.objects.filter(
                    code__in=(cleaned["base"], cleaned["quote"])
                )
            }
            base_currency = currencies.get(cleaned["base"])
            quote_currency = currencies.get(cleaned["quote"])
            then_now, comparison_notice = _build_then_now_enrichment(
                cleaned,
                result,
                base_currency=base_currency,
                quote_currency=quote_currency,
                latest_gateway_factory=latest_gateway_factory,
                quote_conversion_fn=quote_conversion_fn,
                compare_historical_to_latest_fn=compare_historical_to_latest_fn,
            )
            then_media = (
                _select_then_media(
                    quote_currency=quote_currency,
                    selected_date=cleaned["selected_date"],
                )
                if then_now is not None
                else None
            )
            component = build_rate_series_component(
                result,
                selected_date=cleaned["selected_date"],
                requested_date=cleaned.get("requested_date"),
                period=cleaned["period"],
                amount=cleaned.get("amount_decimal"),
                then_now=then_now,
                then_media=then_media,
                comparison_notice=comparison_notice,
            )
        except (
            RateSeriesRangeError,
            HistoricalObservationUnavailable,
            HistoricalOutOfCoverage,
            FxProviderError,
        ) as exc:
            response_status, error = _series_error(exc)
    else:
        response_status = 422
        error = {
            "title": "Choose a valid historical trend range.",
            "detail": "Check the pair, selected observation date and range controls.",
        }

    context = {
        "series_form": form,
        "series_component": component,
        "series_error": error,
    }
    fragment = is_htmx(request)
    template = (
        "components/converter/rate_series.html" if fragment else "pages/historical_series.html"
    )
    response = render(request, template, context, status=response_status)
    patch_vary_headers(response, ["HX-Request"])
    return response
