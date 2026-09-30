from __future__ import annotations

from django.http import HttpRequest, HttpResponse

from apps.exchange.ai.service import build_runtime_explanation_service
from apps.exchange.services import (
    compare_historical_to_latest,
    get_rate_series,
    quote_conversion,
)
from apps.exchange.web.budget import budget_interpretation_view
from apps.exchange.web.converter import converter_view
from apps.exchange.web.explanation import conversion_explanation_view
from apps.exchange.web.gateways import (
    build_historical_quote_gateway,
    build_historical_series_gateway,
    build_latest_quote_gateway,
)
from apps.exchange.web.history import historical_series_view
from apps.exchange.web.payment_estimate import payment_estimate_view
from apps.exchange.web.picker import picker_options_view
from apps.travel.history import record_recent_conversion
from apps.travel.queries import is_user_favourite


def converter(request: HttpRequest) -> HttpResponse:
    """Compatibility façade for the main converter endpoint and its patch seams."""

    return converter_view(
        request,
        latest_gateway_factory=build_latest_quote_gateway,
        historical_gateway_factory=build_historical_quote_gateway,
        record_recent_conversion_fn=record_recent_conversion,
        is_user_favourite_fn=is_user_favourite,
    )


def picker_options(request: HttpRequest) -> HttpResponse:
    return picker_options_view(request)


def historical_series(request: HttpRequest) -> HttpResponse:
    """Compatibility façade for historical-series dependencies used by tests/tools."""

    return historical_series_view(
        request,
        series_gateway_factory=build_historical_series_gateway,
        latest_gateway_factory=build_latest_quote_gateway,
        get_rate_series_fn=get_rate_series,
        quote_conversion_fn=quote_conversion,
        compare_historical_to_latest_fn=compare_historical_to_latest,
    )


def payment_estimate(request: HttpRequest) -> HttpResponse:
    return payment_estimate_view(request)


def budget_interpretation(request: HttpRequest) -> HttpResponse:
    return budget_interpretation_view(request)


def conversion_explanation(request: HttpRequest) -> HttpResponse:
    return conversion_explanation_view(
        request,
        explanation_service_factory=build_runtime_explanation_service,
    )
