from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from django.utils.text import slugify
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from apps.travel.models import SavedScenario
from apps.travel.offline_pack import OfflineDestinationPackError, build_offline_destination_pack
from apps.travel.offline_snapshot import (
    OFFLINE_TRIP_SNAPSHOT_VERSION,
    build_offline_snapshot_revision,
)


def _owned_offline_scenario(request: HttpRequest, scenario_id: int) -> SavedScenario:
    return get_object_or_404(
        SavedScenario.objects.select_related(
            "source_currency",
            "destination_currency",
            "destination_country",
            "destination_city",
        ).prefetch_related(
            "budget_items",
            "observations",
            "spend_entries",
        ),
        pk=scenario_id,
        user=request.user,
    )


def _offline_security_headers(response: HttpResponse) -> HttpResponse:
    response["Cache-Control"] = "private, no-store"
    response["Pragma"] = "no-cache"
    response["X-Robots-Tag"] = "noindex, nofollow"
    response["Referrer-Policy"] = "no-referrer"
    response["Content-Security-Policy"] = (
        "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"
    )
    return response


@login_required
@require_GET
def download_offline_destination_pack(
    request: HttpRequest,
    scenario_id: int,
) -> HttpResponse:
    scenario = _owned_offline_scenario(request, scenario_id)

    try:
        pack = build_offline_destination_pack(scenario)
    except OfflineDestinationPackError as exc:
        raise Http404(str(exc)) from exc

    body = render_to_string(
        "travel/offline_destination_pack.html",
        {"pack": pack},
        request=request,
    )
    destination_slug = slugify(pack.destination_label) or "destination"
    filename = f"cultural-currency-{destination_slug}-offline-{pack.context_as_of.isoformat()}.html"

    response = HttpResponse(body, content_type="text/html; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return _offline_security_headers(response)


@login_required
@never_cache
@require_GET
def offline_trip_snapshot(
    request: HttpRequest,
    scenario_id: int,
) -> HttpResponse:
    """Render a private snapshot that can be stored only by an explicit browser action."""

    scenario = _owned_offline_scenario(request, scenario_id)
    try:
        pack = build_offline_destination_pack(scenario)
    except OfflineDestinationPackError as exc:
        raise Http404(str(exc)) from exc

    revision = build_offline_snapshot_revision(scenario)
    body = render_to_string(
        "travel/offline_destination_pack.html",
        {
            "pack": pack,
            "pwa_snapshot": True,
            "snapshot_revision": revision,
        },
        request=request,
    )
    response = HttpResponse(body, content_type="text/html; charset=utf-8")
    response["X-Cultural-Currency-Offline-Snapshot"] = str(OFFLINE_TRIP_SNAPSHOT_VERSION)
    response["X-Cultural-Currency-Snapshot-Revision"] = revision
    response["X-Cultural-Currency-Snapshot-Generated-At"] = pack.generated_at.isoformat()
    return _offline_security_headers(response)
