from __future__ import annotations

from collections.abc import Callable
from typing import Any

from django.conf import settings
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils.cache import patch_vary_headers
from django.views.decorators.http import require_http_methods

from apps.exchange.snapshot_tokens import (
    ConversionSnapshotTokenError,
    load_conversion_snapshot_token,
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
        snapshot = load_conversion_snapshot_token(token)
    except ConversionSnapshotTokenError:
        response_status = 422
        explanation_error = {
            "title": "This explanation request is no longer valid.",
            "detail": "Run the conversion again, then choose Explain this.",
        }
    else:
        service = explanation_service_factory()
        delivery = service.explain(snapshot)
        explanation = {
            "result": delivery.result,
            "cache_status": delivery.cache_status,
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
