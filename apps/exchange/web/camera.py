from __future__ import annotations

import logging
from urllib.parse import urlencode

from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from apps.countries.models import Currency
from apps.exchange.camera import CameraExtractionError
from apps.exchange.camera_forms import CameraConfirmForm, CameraUploadForm
from apps.exchange.camera_gemini import GeminiCameraExtractor, build_camera_extractor
from apps.exchange.camera_media import CameraImageError, prepare_camera_image
from apps.exchange.camera_tokens import (
    CameraExtractionTokenError,
    create_camera_extraction_token,
    load_camera_extraction_token,
)
from integrations.gemini.errors import AIProviderError

logger = logging.getLogger("cultural_currency.ai")


def _confidence_label(value) -> str:
    if value >= 0.85:
        return "High"
    if value >= 0.6:
        return "Medium"
    return "Low"


def _initial_currency(code: str, *, fallback: str = "") -> str:
    normalized = code.upper().strip()
    if normalized and Currency.objects.filter(code=normalized, is_active=True).exists():
        return normalized
    if fallback and Currency.objects.filter(code=fallback, is_active=True).exists():
        return fallback
    return ""


def _converter_url(form: CameraConfirmForm) -> str:
    cleaned = form.cleaned_data
    params = {
        "convert": "1",
        "amount": format(cleaned["amount_decimal"], "f"),
        "source_country": "",
        "source_currency": cleaned["currency"],
        "destination_country": "",
        "destination_currency": cleaned["target_currency"],
    }
    return f"{reverse('converter')}?{urlencode(params)}"


@require_http_methods(["GET", "POST"])
def camera_capture_view(
    request: HttpRequest,
    *,
    extractor_factory=build_camera_extractor,
) -> HttpResponse:
    upload_form: CameraUploadForm | None = None
    confirmation_form: CameraConfirmForm | None = None
    extraction = None
    page_error = None
    response_status = 200

    if request.method == "GET":
        target = _initial_currency(request.GET.get("target_currency", ""), fallback="EUR")
        expected = _initial_currency(request.GET.get("expected_currency", ""))
        upload_form = CameraUploadForm(
            initial={
                "expected_currency": expected,
                "target_currency": target,
            }
        )
    elif request.POST.get("action") == "confirm":
        confirmation_form = CameraConfirmForm(request.POST)
        token = request.POST.get("extraction_token", "")
        try:
            snapshot = load_camera_extraction_token(token)
        except CameraExtractionTokenError:
            response_status = 422
            page_error = {
                "title": "This camera result is no longer valid.",
                "detail": "Upload the image again, then confirm the detected price.",
            }
        else:
            extraction = {
                "context_kind": snapshot.context_kind.value,
                "confidence_label": _confidence_label(snapshot.confidence),
                "provider_model": snapshot.provider_model,
            }
            if confirmation_form.is_valid():
                return redirect(_converter_url(confirmation_form))
            response_status = 422
    else:
        upload_form = CameraUploadForm(request.POST, request.FILES)
        if upload_form.is_valid():
            uploaded = upload_form.cleaned_data["image"]
            try:
                raw_bytes = uploaded.read()
                prepared = prepare_camera_image(
                    raw_bytes,
                    filename=str(getattr(uploaded, "name", "") or "camera.jpg"),
                )
                extractor: GeminiCameraExtractor | None = extractor_factory()
                if extractor is None:
                    response_status = 503
                    page_error = {
                        "title": "Camera reading is not enabled on this deployment.",
                        "detail": (
                            "The standard converter remains available. "
                            "No uploaded image has been stored."
                        ),
                    }
                else:
                    candidate = extractor.extract(
                        prepared,
                        expected_currency=upload_form.cleaned_data["expected_currency"],
                    )
                    if not candidate.found:
                        response_status = 422
                        page_error = {
                            "title": "No single clear price could be read.",
                            "detail": (
                                "Try a tighter photo with one visible amount and currency, "
                                "or use the standard converter."
                            ),
                        }
                    elif not Currency.objects.filter(
                        code=candidate.currency_code,
                        is_active=True,
                    ).exists():
                        response_status = 422
                        page_error = {
                            "title": "The detected currency is not available for current conversion.",
                            "detail": "Confirm the price manually in the standard converter.",
                        }
                    else:
                        token = create_camera_extraction_token(candidate)
                        confirmation_form = CameraConfirmForm(
                            initial={
                                "extraction_token": token,
                                "amount": format(candidate.amount, "f"),
                                "currency": candidate.currency_code,
                                "target_currency": upload_form.cleaned_data["target_currency"],
                            }
                        )
                        extraction = {
                            "context_kind": candidate.context_kind.value,
                            "confidence_label": _confidence_label(candidate.confidence),
                            "provider_model": candidate.provider_model,
                        }
            except CameraImageError as exc:
                response_status = 422
                upload_form.add_error("image", str(exc))
            except CameraExtractionError as exc:
                logger.warning(
                    "camera_extraction_invalid_provider_payload",
                    extra={"error_code": exc.__class__.__name__},
                )
                response_status = 502
                page_error = {
                    "title": "The camera reader returned an unusable result.",
                    "detail": "No conversion was performed. Try another image or use the converter.",
                }
            except AIProviderError as exc:
                logger.warning(
                    "camera_extraction_provider_failure",
                    extra={"error_code": exc.__class__.__name__},
                )
                response_status = 503
                page_error = {
                    "title": "Camera reading is temporarily unavailable.",
                    "detail": "No conversion was performed. Try again later or use the converter.",
                }
        else:
            response_status = 422

    return render(
        request,
        "pages/camera.html",
        {
            "upload_form": upload_form,
            "confirmation_form": confirmation_form,
            "extraction": extraction,
            "camera_error": page_error,
        },
        status=response_status,
    )
