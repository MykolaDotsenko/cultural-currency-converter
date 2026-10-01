from __future__ import annotations

import logging
from decimal import Decimal
from urllib.parse import urlencode

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST, require_http_methods

from apps.countries.models import Currency
from apps.exchange.camera import (
    CameraCandidate,
    CameraExtractionState,
    CameraExtractor,
    CameraExtractionValidationError,
    dump_camera_candidate,
    load_camera_candidate,
    safely_extract_camera_candidate,
)
from apps.exchange.camera_forms import (
    MAX_CAMERA_UPLOAD_BYTES,
    CameraConfirmForm,
    CameraUploadForm,
)
from apps.exchange.camera_provider import build_camera_extractor
from apps.media.validation import MediaValidationError, validate_raster_image

logger = logging.getLogger("cultural_currency.ai")


def _render_camera(
    request: HttpRequest,
    *,
    upload_form: CameraUploadForm | None = None,
    confirm_form: CameraConfirmForm | None = None,
    extraction_state: CameraExtractionState | None = None,
    candidate: CameraCandidate | None = None,
    status: int = 200,
) -> HttpResponse:
    return render(
        request,
        "pages/camera.html",
        {
            "upload_form": upload_form or CameraUploadForm(),
            "confirm_form": confirm_form,
            "camera_available": bool(settings.AI_CAMERA_EXTRACTION_ENABLED),
            "extraction_state": extraction_state,
            "camera_candidate": candidate,
        },
        status=status,
    )


@require_http_methods(["GET", "POST"])
def camera_view(
    request: HttpRequest,
    *,
    extractor_factory=build_camera_extractor,
) -> HttpResponse:
    if request.method == "GET":
        return _render_camera(request)

    form = CameraUploadForm(request.POST, request.FILES)
    if not bool(settings.AI_CAMERA_EXTRACTION_ENABLED):
        return _render_camera(
            request,
            upload_form=form,
            extraction_state=CameraExtractionState.UNAVAILABLE,
            status=503,
        )
    if not form.is_valid():
        return _render_camera(request, upload_form=form, status=422)

    uploaded = form.cleaned_data["image"]
    image_bytes = uploaded.read(MAX_CAMERA_UPLOAD_BYTES + 1)
    try:
        validated = validate_raster_image(
            image_bytes,
            filename=uploaded.name,
            max_bytes=MAX_CAMERA_UPLOAD_BYTES,
        )
    except MediaValidationError as exc:
        form.add_error("image", str(exc))
        return _render_camera(request, upload_form=form, status=422)

    declared_mime_type = str(getattr(uploaded, "content_type", "") or "").lower()
    if declared_mime_type != validated.mime_type:
        form.add_error("image", "Image content does not match its declared file type.")
        return _render_camera(request, upload_form=form, status=422)

    extraction = safely_extract_camera_candidate(
        extractor_factory(),
        image_bytes=image_bytes,
        mime_type=validated.mime_type,
    )
    logger.info(
        "Camera extraction completed",
        extra={
            "capability": "camera_extraction",
            "operation": "extract",
            "outcome": extraction.state.value,
            "mime_type": validated.mime_type,
            "width": validated.width,
            "height": validated.height,
            "input_bytes": len(image_bytes),
            "provider_model": extraction.provider_model,
        },
    )

    if extraction.state is CameraExtractionState.UNAVAILABLE:
        return _render_camera(
            request,
            upload_form=form,
            extraction_state=extraction.state,
            status=503,
        )
    if extraction.state in {CameraExtractionState.AMBIGUOUS, CameraExtractionState.NO_PRICE}:
        return _render_camera(
            request,
            upload_form=CameraUploadForm(
                initial={"target_currency": form.cleaned_data["target_currency"]}
            ),
            extraction_state=extraction.state,
            status=200,
        )

    candidate = extraction.candidate
    if candidate is None:
        raise RuntimeError("Candidate camera extraction returned no candidate.")

    source_supported = Currency.objects.filter(
        code=candidate.currency_code,
        is_active=True,
    ).exists()
    confirm_form = CameraConfirmForm(
        initial={
            "extraction_token": dump_camera_candidate(candidate),
            "amount": format(candidate.amount, "f"),
            "source_currency": candidate.currency_code if source_supported else "",
            "target_currency": form.cleaned_data["target_currency"],
        }
    )
    return _render_camera(
        request,
        upload_form=CameraUploadForm(
            initial={"target_currency": form.cleaned_data["target_currency"]}
        ),
        confirm_form=confirm_form,
        extraction_state=extraction.state,
        candidate=candidate,
    )


@require_POST
def camera_confirm_view(request: HttpRequest) -> HttpResponse:
    form = CameraConfirmForm(request.POST)
    token = str(request.POST.get("extraction_token") or "")
    try:
        load_camera_candidate(token)
    except CameraExtractionValidationError as exc:
        form.add_error(None, str(exc))

    if not form.is_valid():
        return _render_camera(
            request,
            confirm_form=form,
            extraction_state=CameraExtractionState.CANDIDATE,
            status=422,
        )

    amount = form.cleaned_data.get("amount_decimal")
    if not isinstance(amount, Decimal):
        raise RuntimeError("Valid camera confirmation returned no Decimal amount.")

    params = {
        "convert": "1",
        "amount": format(amount, "f"),
        "source_country": "",
        "source_currency": form.cleaned_data["source_currency"],
        "destination_country": "",
        "destination_currency": form.cleaned_data["target_currency"],
    }
    return redirect(f"{reverse('converter')}?{urlencode(params)}")
