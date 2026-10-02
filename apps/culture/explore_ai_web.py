from __future__ import annotations

from decimal import Decimal
from urllib.parse import urlencode

from django.db import DatabaseError
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.utils.cache import patch_vary_headers
from django.views.decorators.http import require_http_methods

from apps.countries.models import City, CountryCurrency
from apps.culture.explore_ai import (
    ExploreAIIntentError,
    ExploreAITokenError,
    available_explore_ai_intents,
    build_explore_ai_fallback_delivery,
    build_explore_ai_packet,
    build_explore_ai_snapshot_token,
    load_explore_ai_snapshot_token,
    parse_explore_ai_intent,
)
from apps.culture.services import build_destination_context
from apps.exchange.ai.service import build_runtime_explanation_service


def _resolve_destination(token: str):
    normalized = token.strip()
    country_code, separator, city_slug = normalized.partition(":")
    country_code = country_code.upper().strip()
    city_slug = city_slug.strip().lower() if separator else ""
    if len(country_code) != 2 or not country_code.isascii() or not country_code.isalpha():
        return None

    link = (
        CountryCurrency.objects.current()
        .primary()
        .filter(country__iso2=country_code, country__is_active=True)
        .select_related("country", "currency")
        .first()
    )
    if link is None:
        return None

    city = None
    if city_slug:
        city = City.objects.filter(
            country=link.country,
            slug=city_slug,
            is_active=True,
        ).first()
        if city is None:
            return None
    return link, city


def _context_page_data(token: str):
    resolved = _resolve_destination(token)
    if resolved is None:
        return None
    link, city = resolved
    context = build_destination_context(
        country_code=link.country.iso2,
        city_slug=city.slug if city is not None else "",
        converted_amount=Decimal("1"),
        quote_currency=link.currency.code,
        as_of=timezone.localdate(),
        price_limit=4,
    )
    if context is None or not context.has_content:
        return None

    signed_token = build_explore_ai_snapshot_token(
        context,
        currency_code=link.currency.code,
    )
    snapshot = load_explore_ai_snapshot_token(signed_token)
    canonical_token = (
        f"{link.country.iso2}:{city.slug}" if city is not None else link.country.iso2
    )
    return {
        "snapshot": snapshot,
        "signed_token": signed_token,
        "intents": available_explore_ai_intents(snapshot),
        "canonical_token": canonical_token,
        "explore_url": reverse("explore"),
        "converter_url": (
            f"{reverse('converter')}?"
            f"{urlencode({
                'load': '1',
                'destination_country': link.country.iso2,
                'destination_currency': link.currency.code,
                **(
                    {'destination_city_slug': city.slug}
                    if city is not None
                    else {}
                ),
            })}"
        ),
        "budget_url": (
            f"{reverse('destination_mode')}?"
            f"{urlencode({'destination': canonical_token})}"
        ),
    }


@require_http_methods(["GET", "POST"])
def explore_context_ai_view(request: HttpRequest) -> HttpResponse:
    """Explain only signed, reviewed Explore facts; never create discovery truth."""

    explanation = None
    explanation_error = None
    page_data = None
    status = 200

    if request.method == "GET":
        token = str(request.GET.get("destination") or "")
        try:
            page_data = _context_page_data(token)
        except DatabaseError:
            page_data = None
        if page_data is None:
            raise Http404("Reviewed Explore context is not available.")
    else:
        signed_token = request.POST.get("explore_context_token", "")
        try:
            snapshot = load_explore_ai_snapshot_token(signed_token)
            spec = parse_explore_ai_intent(
                request.POST.get("prompt_id"),
                snapshot=snapshot,
            )
        except (ExploreAITokenError, ExploreAIIntentError):
            status = 422
            explanation_error = {
                "title": "This Explore explanation request is no longer valid.",
                "detail": "Open the destination from Explore again, then choose a suggested question.",
            }
        else:
            packet = build_explore_ai_packet(snapshot, spec=spec)
            service = build_runtime_explanation_service()
            delivery = service.explain_packet(
                packet,
                fallback_delivery_factory=lambda reason: build_explore_ai_fallback_delivery(
                    snapshot,
                    spec=spec,
                    packet=packet,
                    reason=reason,
                ),
                capability="explore_context_explanation",
            )
            explanation = {
                "result": delivery.result,
                "cache_status": delivery.cache_status,
                "question": spec.question,
            }
            page_data = {
                "snapshot": snapshot,
                "signed_token": signed_token,
                "intents": available_explore_ai_intents(snapshot),
                "canonical_token": (
                    f"{snapshot.country_code}:{snapshot.city_slug}"
                    if snapshot.city_slug
                    else snapshot.country_code
                ),
                "explore_url": reverse("explore"),
                "converter_url": reverse("converter"),
                "budget_url": reverse("destination_mode"),
            }

    fragment = bool(request.htmx) and request.method == "POST"
    context = {
        "explore_ai": page_data,
        "explanation": explanation,
        "explanation_error": explanation_error,
        "is_htmx_fragment": fragment,
    }
    template = (
        "components/culture/explore_explanation.html"
        if fragment
        else "pages/explore_context_ai.html"
    )
    response = render(request, template, context, status=status)
    patch_vary_headers(response, ["HX-Request"])
    return response
