from __future__ import annotations

import io
from decimal import Decimal

import pytest
from django.db import transaction
from PIL import Image

from apps.exchange.camera import (
    CameraAmountCandidate,
    CameraCandidateKind,
    CameraConfidence,
    CameraExtraction,
    CameraNoAmountFound,
)
from apps.exchange.camera_service import (
    CameraExtractionService,
    CameraFeatureDisabled,
    CameraProviderUnavailable,
    CameraTransactionPolicyError,
    build_camera_extraction_service,
)
from integrations.gemini.errors import AIProviderUnavailable


def _png_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (600, 400), "white").save(output, format="PNG")
    return output.getvalue()


class FakeExtractor:
    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = []

    def extract(self, image, *, expected_currency):
        self.calls.append((image, expected_currency))
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


def _result() -> CameraExtraction:
    return CameraExtraction(
        candidates=(
            CameraAmountCandidate(
                amount=Decimal("4800"),
                currency_code="JPY",
                kind=CameraCandidateKind.TOTAL,
                confidence=CameraConfidence.HIGH,
            ),
        ),
        provider_model="fake-camera",
        provider_response_id="response-1",
    )


@pytest.mark.django_db(transaction=True)
def test_camera_service_sanitizes_before_provider_and_returns_no_raw_media():
    extractor = FakeExtractor(_result())
    service = CameraExtractionService(enabled=True, extractor=extractor)

    delivery = service.scan(
        _png_bytes(),
        content_type="image/png",
        expected_currency="JPY",
    )

    assert delivery.extraction.candidates[0].amount == Decimal("4800")
    assert len(extractor.calls) == 1
    image, expected_currency = extractor.calls[0]
    assert image.mime_type == "image/jpeg"
    assert image.data.startswith(b"\xff\xd8")
    assert expected_currency == "JPY"
    assert not hasattr(delivery, "raw_image")


@pytest.mark.django_db(transaction=True)
def test_camera_service_does_not_process_media_when_feature_is_disabled():
    extractor = FakeExtractor(_result())
    service = CameraExtractionService(enabled=False, extractor=extractor)

    with pytest.raises(CameraFeatureDisabled):
        service.scan(
            b"not-even-an-image",
            content_type="image/jpeg",
            expected_currency="JPY",
        )

    assert extractor.calls == []


@pytest.mark.django_db(transaction=True)
def test_camera_service_preserves_no_amount_as_user_correctable_result():
    extractor = FakeExtractor(CameraNoAmountFound("No monetary amounts were found in this image."))
    service = CameraExtractionService(enabled=True, extractor=extractor)

    with pytest.raises(CameraNoAmountFound):
        service.scan(
            _png_bytes(),
            content_type="image/png",
            expected_currency="JPY",
        )


@pytest.mark.django_db(transaction=True)
def test_camera_service_normalizes_provider_failure_without_logging_media():
    extractor = FakeExtractor(AIProviderUnavailable("down"))
    service = CameraExtractionService(enabled=True, extractor=extractor)

    with pytest.raises(CameraProviderUnavailable, match="temporarily unavailable"):
        service.scan(
            _png_bytes(),
            content_type="image/png",
            expected_currency="JPY",
        )


@pytest.mark.django_db(transaction=True)
def test_live_camera_provider_call_is_forbidden_inside_database_transaction():
    extractor = FakeExtractor(_result())
    service = CameraExtractionService(enabled=True, extractor=extractor)

    with transaction.atomic(), pytest.raises(CameraTransactionPolicyError):
        service.scan(
            _png_bytes(),
            content_type="image/png",
            expected_currency="JPY",
        )

    assert extractor.calls == []


@pytest.mark.django_db(transaction=True)
def test_camera_service_factory_uses_deterministic_fixture_without_live_client(settings):
    settings.AI_CAMERA_EXTRACTION_ENABLED = True
    settings.AI_CAMERA_TEST_FIXTURE_ENABLED = True

    service = build_camera_extraction_service()
    delivery = service.scan(
        _png_bytes(),
        content_type="image/png",
        expected_currency="JPY",
    )

    assert delivery.extraction.provider_model == "deterministic-camera-fixture"
    assert delivery.extraction.candidates[0].amount == Decimal("4800")
    assert delivery.extraction.candidates[0].currency_code == "JPY"
