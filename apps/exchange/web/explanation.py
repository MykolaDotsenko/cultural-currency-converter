from __future__ import annotations

from collections.abc import Callable
from typing import Any

from django.conf import settings
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils.cache import patch_vary_headers
from django.views.decorators.http import require_http_methods

from apps.exchange.ai.intents import (
    ExplanationIntentError,
    ensure_explanation_intent_available,
    parse_explanation_intent,
)
from apps.exchange.trusted_snapshot import (
    TrustedSnapshotTokenError,
    load_trusted_conversion_snapshot_token,
)
from apps.exchange.web.common import is_htmx


@require_http_methods(["POST"])
def conversion_explanation_view(
    request: HttpRequest,
    *,
    explanation_service_factory: Callable[[], Any],
) -> HttpResponse:
    if not settings.AI_RUNTIME_EXPLANATION_ENABLED:
        raise Http404("Runtime AI explanation is disabled.")

    token = request.POST.get("explanation_token", "")
    explanation = None
    explanation_error = None
    response_status = 200

    try:
        snapshot = load_trusted_conversion_snapshot_token(token)
    except TrustedSnapshotTokenError:
        response_status = 422
        explanation_error = {
            "title": "This explanation request is no longer valid.",
            "detail": "Run the conversion again, then choose one of the suggested questions.",
        }
    else:
        try:
            intent = parse_explanation_intent(request.POST.get("prompt_id"))
            intent_spec = ensure_explanation_intent_available(
                intent,
                historical=snapshot.historical,
                stale=snapshot.stale,
            )
        except ExplanationIntentError:
            response_status = 422
            explanation_error = {
                "title": "This explanation question is not available.",
                "detail": "Choose one of the suggested questions for this conversion.",
            }
        else:
            service = explanation_service_factory()
            delivery = service.explain(snapshot, intent=intent)
            explanation = {
                "result": delivery.result,
                "cache_status": delivery.cache_status,
                "question": intent_spec.question,
            }

    context = {
        "explanation": explanation,
        "explanation_error": explanation_error,
    }
    fragment = is_htmx(request)
    template = (
        "components/converter/explanation.html" if fragment else "pages/conversion_explanation.html"
    )
    response = render(request, template, context, status=response_status)
    patch_vary_headers(response, ["HX-Request"])
    return response
