from __future__ import annotations

from collections.abc import Callable
from typing import Any

from django.conf import settings
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils.cache import patch_vary_headers
from django.views.decorators.http import require_POST

from apps.exchange.ai.contextual import (
    BUDGET_AI_CAPABILITY,
    COMPARISON_AI_CAPABILITY,
    ContextualExplanationError,
    explain_contextual_packet,
)
from apps.exchange.ai.packet_tokens import (
    GroundedPacketTokenError,
    load_grounded_packet_token,
)
from apps.exchange.web.common import is_htmx

ServiceFactory = Callable[[], Any]


@require_POST
def budget_explanation_view(
    request: HttpRequest,
    *,
    explanation_service_factory: ServiceFactory,
) -> HttpResponse:
    return _contextual_explanation_view(
        request,
        capability=BUDGET_AI_CAPABILITY,
        explanation_service_factory=explanation_service_factory,
        surface_label="Budget interpretation",
        back_url=reverse("converter"),
    )


@require_POST
def comparison_explanation_view(
    request: HttpRequest,
    *,
    explanation_service_factory: ServiceFactory,
) -> HttpResponse:
    return _contextual_explanation_view(
        request,
        capability=COMPARISON_AI_CAPABILITY,
        explanation_service_factory=explanation_service_factory,
        surface_label="Destination comparison",
        back_url=reverse("destination_comparison"),
    )


def _contextual_explanation_view(
    request: HttpRequest,
    *,
    capability: str,
    explanation_service_factory: ServiceFactory,
    surface_label: str,
    back_url: str,
) -> HttpResponse:
    if not settings.AI_RUNTIME_EXPLANATION_ENABLED:
        raise Http404("Runtime AI explanation is disabled.")

    explanation = None
    explanation_error = None
    response_status = 200
    token = request.POST.get("grounded_explanation_token", "")

    try:
        packet = load_grounded_packet_token(
            token,
            expected_capability=capability,
        )
    except GroundedPacketTokenError:
        response_status = 422
        explanation_error = {
            "title": "This explanation request is no longer valid.",
            "detail": (
                f"Reopen the {surface_label.lower()} and choose one of its current "
                "grounded questions."
            ),
        }
    else:
        try:
            delivery = explain_contextual_packet(
                packet,
                capability=capability,
                service=explanation_service_factory(),
            )
        except ContextualExplanationError:
            response_status = 422
            explanation_error = {
                "title": "This explanation question is not available.",
                "detail": (
                    f"Reopen the {surface_label.lower()} and choose one of its suggested questions."
                ),
            }
        else:
            supporting_fact_ids = {
                fact_id
                for insight in (
                    delivery.result.short_answer,
                    *delivery.result.key_factors,
                    delivery.result.watch_out_for,
                    delivery.result.next_step,
                )
                for fact_id in insight.supporting_fact_ids
            }
            explanation = {
                "result": delivery.result,
                "cache_status": delivery.cache_status,
                "question": packet.intent_question,
                "surface_label": surface_label,
                "facts_used": tuple(
                    fact for fact in packet.facts if fact.id in supporting_fact_ids
                ),
            }

    fragment = is_htmx(request)
    template = (
        "components/ai/contextual_explanation.html"
        if fragment
        else "pages/contextual_explanation.html"
    )
    response = render(
        request,
        template,
        {
            "explanation": explanation,
            "explanation_error": explanation_error,
            "is_htmx_fragment": fragment,
            "surface_label": surface_label,
            "back_url": back_url,
        },
        status=response_status,
    )
    patch_vary_headers(response, ["HX-Request"])
    return response
