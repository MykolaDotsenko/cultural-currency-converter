from __future__ import annotations

from urllib.parse import urlencode

from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.http import require_GET

from apps.travel.share_presentation import build_scenario_share_card
from apps.travel.share_snapshot import ScenarioShareTokenError, load_scenario_share_token


def _share_snapshot(request: HttpRequest):
    token = str(request.GET.get("snapshot") or "")
    try:
        snapshot = load_scenario_share_token(token)
    except ScenarioShareTokenError as exc:
        raise Http404("Shared travel-money snapshot is invalid.") from exc
    return token, snapshot


def _private_share_headers(response: HttpResponse) -> HttpResponse:
    response["Cache-Control"] = "private, no-store"
    response["Pragma"] = "no-cache"
    response["X-Robots-Tag"] = "noindex, nofollow"
    response["Referrer-Policy"] = "no-referrer"
    return response


@require_GET
def scenario_share_card(request: HttpRequest) -> HttpResponse:
    token, snapshot = _share_snapshot(request)
    card = build_scenario_share_card(snapshot)
    query = urlencode({"snapshot": token})
    relative_share_url = f"{reverse('share_scenario_card')}?{query}"
    card_image_url = f"{reverse('share_scenario_card_svg')}?{query}"

    response = render(
        request,
        "pages/share_scenario.html",
        {
            "share_card": card,
            "share_url": request.build_absolute_uri(relative_share_url),
            "card_image_url": card_image_url,
            "card_download_name": (
                f"cultural-currency-{snapshot.base_currency.lower()}-"
                f"{snapshot.quote_currency.lower()}-travel-share.svg"
            ),
        },
    )
    return _private_share_headers(response)


@require_GET
def scenario_share_card_svg(request: HttpRequest) -> HttpResponse:
    _token, snapshot = _share_snapshot(request)
    card = build_scenario_share_card(snapshot)
    body = render_to_string(
        "share/scenario_card.svg",
        {"share_card": card},
        request=request,
    )
    response = HttpResponse(body, content_type="image/svg+xml; charset=utf-8")
    response["Content-Disposition"] = (
        f'inline; filename="cultural-currency-{snapshot.base_currency.lower()}-'
        f'{snapshot.quote_currency.lower()}-travel-share.svg"'
    )
    response["X-Content-Type-Options"] = "nosniff"
    return _private_share_headers(response)
