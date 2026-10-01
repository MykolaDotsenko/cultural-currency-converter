from __future__ import annotations

import io
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from PIL import Image

from apps.countries.models import Currency
from apps.exchange.camera import (
    CameraAmountKind,
    CameraCandidate,
    CameraConfidence,
    CameraExtraction,
    CameraExtractionState,
)


class _FakeExtractor:
    def __init__(self, extraction: CameraExtraction) -> None:
        self.extraction = extraction
        self.calls: list[tuple[bytes, str]] = []

    def extract(self, *, image_bytes: bytes, mime_type: str) -> CameraExtraction:
        self.calls.append((image_bytes, mime_type))
        return self.extraction


def _png_upload(*, name: str = "price.png", content_type: str = "image/png"):
    stream = io.BytesIO()
    Image.new("RGB", (12, 8), "white").save(stream, format="PNG")
    return SimpleUploadedFile(
        name,
        stream.getvalue(),
        content_type=content_type,
    )


@pytest.fixture
def currencies(db):
    eur = Currency.objects.create(code="EUR", name="Euro", symbol="€", minor_units=2)
    jpy = Currency.objects.create(code="JPY", name="Japanese yen", symbol="¥", minor_units=0)
    return eur, jpy


@pytest.mark.django_db
def test_camera_page_is_available_as_progressive_feature(client, currencies):
    response = client.get(reverse("camera_capture"))

    assert response.status_code == 200
    assert b"Camera mode is not enabled in this environment." in response.content


@pytest.mark.django_db
def test_disabled_camera_post_never_calls_provider(client, currencies, monkeypatch):
    called = False

    def unexpected_factory():
        nonlocal called
        called = True
        raise AssertionError("camera provider should not be constructed")

    monkeypatch.setattr("apps.exchange.views.build_camera_extractor", unexpected_factory)

    response = client.post(
        reverse("camera_capture"),
        {
            "target_currency": "EUR",
            "image": _png_upload(),
        },
    )

    assert response.status_code == 503
    assert called is False
    assert b"Camera extraction is unavailable right now." in response.content


@pytest.mark.django_db
@override_settings(AI_CAMERA_EXTRACTION_ENABLED=True)
def test_camera_candidate_requires_explicit_review_before_conversion(
    client,
    currencies,
    monkeypatch,
):
    extractor = _FakeExtractor(
        CameraExtraction(
            state=CameraExtractionState.CANDIDATE,
            candidate=CameraCandidate(
                amount=Decimal("4800"),
                currency_code="JPY",
                confidence=CameraConfidence.HIGH,
                kind=CameraAmountKind.TOTAL,
            ),
            provider_model="camera-test-model",
        )
    )
    monkeypatch.setattr("apps.exchange.views.build_camera_extractor", lambda: extractor)

    response = client.post(
        reverse("camera_capture"),
        {
            "target_currency": "EUR",
            "image": _png_upload(),
        },
    )

    assert response.status_code == 200
    assert len(extractor.calls) == 1
    assert extractor.calls[0][1] == "image/png"
    assert b"Human confirmation required" in response.content
    assert b'value="4800"' in response.content
    assert b'value="JPY"' in response.content
    assert b"Confirm and convert" in response.content
    assert b"camera-test-model" not in response.content


@pytest.mark.django_db
@override_settings(AI_CAMERA_EXTRACTION_ENABLED=True)
def test_camera_rejects_declared_mime_mismatch_before_provider(
    client,
    currencies,
    monkeypatch,
):
    called = False

    def unexpected_factory():
        nonlocal called
        called = True
        raise AssertionError("provider should not see mismatched image bytes")

    monkeypatch.setattr("apps.exchange.views.build_camera_extractor", unexpected_factory)

    response = client.post(
        reverse("camera_capture"),
        {
            "target_currency": "EUR",
            "image": _png_upload(content_type="image/jpeg"),
        },
    )

    assert response.status_code == 422
    assert called is False
    assert b"Image content does not match its declared file type." in response.content


@pytest.mark.django_db
@override_settings(AI_CAMERA_EXTRACTION_ENABLED=True, SECRET_KEY="camera-web-test-secret")
def test_user_can_correct_camera_candidate_before_canonical_conversion(
    client,
    currencies,
    monkeypatch,
):
    extractor = _FakeExtractor(
        CameraExtraction(
            state=CameraExtractionState.CANDIDATE,
            candidate=CameraCandidate(
                amount=Decimal("4800"),
                currency_code="JPY",
                confidence=CameraConfidence.MEDIUM,
                kind=CameraAmountKind.ITEM,
            ),
        )
    )
    monkeypatch.setattr("apps.exchange.views.build_camera_extractor", lambda: extractor)

    extraction_response = client.post(
        reverse("camera_capture"),
        {
            "target_currency": "EUR",
            "image": _png_upload(),
        },
    )
    confirm_form = extraction_response.context["confirm_form"]
    token = str(confirm_form.initial["extraction_token"])

    response = client.post(
        reverse("camera_confirm"),
        {
            "extraction_token": token,
            "amount": "5000",
            "source_currency": "JPY",
            "target_currency": "EUR",
        },
    )

    assert response.status_code == 302
    parsed = urlparse(response["Location"])
    assert parsed.path == reverse("converter")
    query = parse_qs(parsed.query)
    assert query["convert"] == ["1"]
    assert query["amount"] == ["5000"]
    assert query["source_currency"] == ["JPY"]
    assert query["destination_currency"] == ["EUR"]
    assert query["source_country"] == [""]
    assert query["destination_country"] == [""]


@pytest.mark.django_db
@override_settings(SECRET_KEY="camera-web-test-secret")
def test_camera_confirmation_rejects_tampered_token(client, currencies):
    response = client.post(
        reverse("camera_confirm"),
        {
            "extraction_token": "tampered-token",
            "amount": "5000",
            "source_currency": "JPY",
            "target_currency": "EUR",
        },
    )

    assert response.status_code == 422
    assert b"Camera extraction confirmation has expired or is invalid." in response.content
