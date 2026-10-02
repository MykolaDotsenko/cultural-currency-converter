from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.db import DatabaseError
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.cache import patch_vary_headers
from django.views.decorators.http import require_http_methods

from apps.culture.explore import build_explore_destinations
from apps.culture.services import build_destination_context
from apps.exchange.ai.explore import (
    ExploreExplanationIntentError,
    build_explore_explanation_packet,
    build_explore_fallback_result,
    explore_explanation_intent_spec,
    parse_explore_explanation_intent,
)
from apps.exchange.web.common import is_htmx


@require_http_methods(["POST"])
def explore_explanation_view(
    request: HttpRequest,
    *,
    explanation_service_factory: Callable[[], Any],
) -> HttpResponse:
    if not settings.AI_RUNTIME_EXPLANATION_ENABLED:
        raise Http404("Runtime AI explanation is disabled.")

    explanation = None
    explanation_error = None
    response_status = 200
    destination_token = request.POST.get("destination_token", "").strip()
    prompt_id = request.POST.get("prompt_id")

    if not destination_token or len(destination_token) > 160:
        response_status = 422
        explanation_error = {
            "title": "Choose a reviewed destination first.",
            "detail": "Refresh Explore if the destination list has changed.",
        }
    else:
        selected_date = timezone.localdate()
        try:
            destinations = build_explore_destinations(as_of=selected_date, limit=24)
        except DatabaseError:
            response_status = 503
            explanation_error = {
                "title": "Reviewed destination context is temporarily unavailable.",
                "detail": "Explore remains usable without the optional AI explanation.",
            }
        else:
            destination = next(
                (item for item in destinations if item.token == destination_token),
                None,
            )
            if destination is None:
                response_status = 422
                explanation_error = {
                    "title": "This reviewed destination is no longer available.",
                    "detail": "Refresh Explore and choose a destination from the current list.",
                }
            else:
                try:
                    intent = parse_explore_explanation_intent(prompt_id)
                except ExploreExplanationIntentError:
                    response_status = 422
                    explanation_error = {
                        "title": "This explanation question is not available.",
                        "detail": "Choose one of the suggested Explore questions.",
                    }
                else:
                    try:
                        destination_context = build_destination_context(
                            country_code=destination.country_code,
                            converted_amount=Decimal("0"),
                            quote_currency=destination.currency_code,
                            as_of=selected_date,
                            city_slug=destination.city_slug,
                        )
                    except (DatabaseError, ValueError):
                        response_status = 503
                        explanation_error = {
                            "title": "Reviewed destination context is temporarily unavailable.",
                            "detail": "Explore remains usable without the optional AI explanation.",
                        }
                    else:
                        direct_city_evidence = (
                            not destination.city_slug
                            or (
                                destination_context is not None
                                and any(
                                    price.city_slug == destination.city_slug
                                    for price in destination_context.prices
                                )
                            )
                        )
                        if (
                            destination_context is None
                            or not destination_context.has_content
                            or not direct_city_evidence
                        ):
                            response_status = 422
                            explanation_error = {
                                "title": "This destination no longer has reviewable context.",
                                "detail": "Refresh Explore before requesting another explanation.",
                            }
                        else:
                            packet = build_explore_explanation_packet(
                                destination,
                                destination_context,
                                intent=intent,
                            )
                            service = explanation_service_factory()
                            delivery = service.explain_packet(
                                packet,
                                fallback_factory=lambda reason: build_explore_fallback_result(
                                    packet,
                                    intent=intent,
                                    reason=reason,
                                ),
                            )
                            explanation = {
                                "result": delivery.result,
                                "cache_status": delivery.cache_status,
                                "question": explore_explanation_intent_spec(intent).question,
                                "surface": "explore",
                            }

    fragment = is_htmx(request)
    context = {
        "explanation": explanation,
        "explanation_error": explanation_error,
        "is_htmx_fragment": fragment,
    }
    template = (
        "components/converter/explanation.html"
        if fragment
        else "pages/explore_explanation.html"
    )
    response = render(request, template, context, status=response_status)
    patch_vary_headers(response, ["HX-Request"])
    return response
