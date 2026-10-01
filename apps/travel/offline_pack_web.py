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


@login_required
@never_cache
@require_GET
def download_offline_destination_pack(
    request: HttpRequest,
    scenario_id: int,
) -> HttpResponse:
    scenario = get_object_or_404(
        SavedScenario.objects.select_related(
            "source_currency",
            "destination_currency",
            "destination_country",
            "destination_city",
        ).prefetch_related(
            "observations",
            "spend_entries",
        ),
        pk=scenario_id,
        user=request.user,
    )

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
    filename = (
        f"cultural-currency-{destination_slug}-offline-{pack.context_as_of.isoformat()}.html"
    )

    response = HttpResponse(body, content_type="text/html; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["Cache-Control"] = "private, no-store"
    response["Pragma"] = "no-cache"
    response["X-Robots-Tag"] = "noindex, nofollow"
    response["Referrer-Policy"] = "no-referrer"
    response["Content-Security-Policy"] = (
        "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"
    )
    return response
