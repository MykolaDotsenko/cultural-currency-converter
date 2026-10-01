from __future__ import annotations

import logging
from typing import Callable

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from apps.exchange.camera import (
    MAX_CAMERA_UPLOAD_BYTES,
    CameraImageError,
    CameraNoAmountFound,
    make_camera_candidate_token,
    make_confirmed_camera_amount_token,
)
from apps.exchange.camera_service import (
    CameraExtractionService,
    CameraFeatureDisabled,
    CameraProviderUnavailable,
    build_camera_extraction_service,
)
from apps.travel.camera_forms import (
    CameraCandidateConfirmationForm,
    CameraUploadForm,
    camera_scope_for_scenario,
)
from apps.travel.models import SavedScenario, SavedScenarioKind

logger = logging.getLogger("cultural_currency.travel")

CameraServiceFactory = Callable[[], CameraExtractionService]


def _owned_budget_scenario(request: HttpRequest, scenario_id: int) -> SavedScenario:
    scenario = get_object_or_404(
        SavedScenario.objects.select_related(
            "destination_currency",
            "destination_country",
            "destination_city",
        ),
        pk=scenario_id,
        user=request.user,
    )
    if scenario.kind != SavedScenarioKind.BUDGET:
        raise Http404("Camera spend confirmation requires a saved budget scenario.")
    return scenario


def _base_context(
    scenario: SavedScenario,
    *,
    upload_form: CameraUploadForm | None = None,
) -> dict[str, object]:
    return {
        "scenario": scenario,
        "upload_form": upload_form or CameraUploadForm(),
        "candidate_rows": (),
        "confirmation_form": None,
        "confirmed_amount": None,
        "confirmed_camera_token": "",
        "provider_unavailable": False,
    }


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def camera_scan_saved_scenario(
    request: HttpRequest,
    scenario_id: int,
    *,
    service_factory: CameraServiceFactory = build_camera_extraction_service,
) -> HttpResponse:
    """Ephemerally extract and confirm one destination-currency amount.

    This endpoint never persists the uploaded image or the confirmed amount.
    Persistence into Trip Budget Remaining is a separate explicit handoff.
    """

    scenario = _owned_budget_scenario(request, scenario_id)
    context = _base_context(scenario)

    if request.method == "GET":
        return render(request, "travel/camera_scan.html", context)

    action = request.POST.get("action", "scan")
    if action == "confirm":
        return _confirm_candidate(request, scenario, context)
    if action != "scan":
        raise Http404("Unknown camera action.")

    upload_form = CameraUploadForm(request.POST, request.FILES)
    context["upload_form"] = upload_form
    if not upload_form.is_valid():
        return render(request, "travel/camera_scan.html", context, status=422)

    upload = upload_form.cleaned_data["image"]
    raw = upload.read(MAX_CAMERA_UPLOAD_BYTES + 1)
    content_type = str(getattr(upload, "content_type", "") or "")

    try:
        delivery = service_factory().scan(
            raw,
            content_type=content_type,
            expected_currency=scenario.destination_currency.code,
        )
    except CameraImageError as exc:
        upload_form.add_error("image", str(exc))
        return render(request, "travel/camera_scan.html", context, status=422)
    except CameraNoAmountFound as exc:
        upload_form.add_error("image", str(exc))
        return render(request, "travel/camera_scan.html", context, status=422)
    except (CameraFeatureDisabled, CameraProviderUnavailable):
        context["provider_unavailable"] = True
        return render(request, "travel/camera_scan.html", context, status=503)

    scope = camera_scope_for_scenario(scenario.pk)
    candidate_rows: list[dict[str, object]] = []
    for index, candidate in enumerate(delivery.extraction.candidates, start=1):
        currency_matches = (
            not candidate.currency_code
            or candidate.currency_code == scenario.destination_currency.code
        )
        token = (
            make_camera_candidate_token(candidate, scope=scope)
            if currency_matches
            else ""
        )
        form = (
            CameraCandidateConfirmationForm(
                scenario_id=scenario.pk,
                destination_currency_code=scenario.destination_currency.code,
                destination_minor_units=scenario.destination_currency.minor_units,
                initial={
                    "candidate_token": token,
                    "amount": format(candidate.amount, "f"),
                },
                auto_id=f"id_candidate_{index}_%s",
            )
            if currency_matches
            else None
        )
        candidate_rows.append(
            {
                "candidate": candidate,
                "form": form,
                "currency_matches": currency_matches,
                "display_currency": candidate.currency_code
                or scenario.destination_currency.code,
            }
        )

    context["candidate_rows"] = tuple(candidate_rows)
    context["image_dimensions"] = f"{delivery.image_width} × {delivery.image_height}"
    return render(request, "travel/camera_scan.html", context)


def _confirm_candidate(
    request: HttpRequest,
    scenario: SavedScenario,
    context: dict[str, object],
) -> HttpResponse:
    form = CameraCandidateConfirmationForm(
        request.POST,
        scenario_id=scenario.pk,
        destination_currency_code=scenario.destination_currency.code,
        destination_minor_units=scenario.destination_currency.minor_units,
    )
    context["confirmation_form"] = form
    if not form.is_valid():
        return render(request, "travel/camera_scan.html", context, status=422)

    amount = form.cleaned_data.get("confirmed_amount")
    if amount is None:
        raise RuntimeError("Valid camera confirmation returned no amount.")

    scope = camera_scope_for_scenario(scenario.pk)
    context["confirmed_amount"] = amount
    context["confirmed_camera_token"] = make_confirmed_camera_amount_token(
        scope=scope,
        amount=amount,
        currency_code=scenario.destination_currency.code,
    )
    return render(request, "travel/camera_confirmed.html", context)
