from __future__ import annotations

import io
from decimal import Decimal
from uuid import UUID

import pytest
from django.core import signing
from PIL import Image

from apps.exchange.camera import (
    CameraAmountCandidate,
    CameraCandidateKind,
    CameraConfidence,
    CameraExtractionError,
    CameraImageError,
    CameraNoAmountFound,
    CameraTokenError,
    load_camera_candidate_token,
    load_confirmed_camera_amount_token,
    make_camera_candidate_token,
    make_confirmed_camera_amount_token,
    normalize_camera_provider_payload,
    sanitize_camera_image,
)


def _image_bytes(
    *,
    size: tuple[int, int] = (3200, 1600),
    image_format: str = "PNG",
) -> bytes:
    image = Image.new("RGB", size, "white")
    output = io.BytesIO()
    image.save(output, format=image_format)
    return output.getvalue()


def test_camera_image_is_decoded_resized_and_reencoded_without_persistence():
    result = sanitize_camera_image(
        _image_bytes(),
        content_type="image/png",
    )

    assert result.mime_type == "image/jpeg"
    assert result.width == 2048
    assert result.height == 1024
    assert result.data.startswith(b"\xff\xd8")


def test_camera_image_reencode_strips_exif_metadata():
    source = Image.new("RGB", (640, 480), "white")
    exif = source.getexif()
    exif[270] = "sensitive receipt context"
    raw = io.BytesIO()
    source.save(raw, format="JPEG", exif=exif)

    result = sanitize_camera_image(
        raw.getvalue(),
        content_type="image/jpeg",
    )

    with Image.open(io.BytesIO(result.data)) as normalized:
        assert len(normalized.getexif()) == 0


@pytest.mark.parametrize(
    ("raw", "content_type", "message"),
    [
        (b"", "image/jpeg", "Choose an image"),
        (b"not-an-image", "image/jpeg", "not a valid supported image"),
        (_image_bytes(size=(20, 20)), "image/gif", "JPEG, PNG or WebP"),
    ],
)
def test_camera_image_rejects_invalid_inputs(raw, content_type, message):
    with pytest.raises(CameraImageError, match=message):
        sanitize_camera_image(raw, content_type=content_type)


def test_camera_provider_payload_normalizes_bounded_candidates():
    result = normalize_camera_provider_payload(
        {
            "candidates": [
                {
                    "amount": "4800",
                    "currency_code": "jpy",
                    "kind": "total",
                    "confidence": "high",
                },
                {
                    "amount": "820",
                    "currency_code": "",
                    "kind": "line_item",
                    "confidence": "medium",
                },
            ]
        },
        provider_model="gemini-model",
        provider_response_id="response-1",
    )

    assert result.provider_model == "gemini-model"
    assert result.provider_response_id == "response-1"
    assert result.candidates[0].amount == Decimal("4800")
    assert result.candidates[0].currency_code == "JPY"
    assert result.candidates[0].kind is CameraCandidateKind.TOTAL
    assert result.candidates[1].currency_code == ""


def test_camera_provider_payload_distinguishes_no_amount_from_malformed_response():
    with pytest.raises(CameraNoAmountFound):
        normalize_camera_provider_payload(
            {"candidates": []},
            provider_model="gemini-model",
            provider_response_id=None,
        )

    with pytest.raises(CameraExtractionError, match="missing candidates"):
        normalize_camera_provider_payload(
            {},
            provider_model="gemini-model",
            provider_response_id=None,
        )


@pytest.mark.parametrize("amount", [Decimal("0"), Decimal("-1"), Decimal("NaN")])
def test_camera_candidate_requires_positive_finite_amount(amount):
    with pytest.raises(CameraExtractionError):
        CameraAmountCandidate(
            amount=amount,
            currency_code="JPY",
            kind=CameraCandidateKind.OTHER,
            confidence=CameraConfidence.LOW,
        )


def test_candidate_token_is_scope_bound_and_tamper_resistant():
    candidate = CameraAmountCandidate(
        amount=Decimal("4800"),
        currency_code="JPY",
        kind=CameraCandidateKind.TOTAL,
        confidence=CameraConfidence.HIGH,
    )
    token = make_camera_candidate_token(candidate, scope="saved-scenario:17")

    snapshot = load_camera_candidate_token(
        token,
        expected_scope="saved-scenario:17",
    )

    assert snapshot.amount == Decimal("4800")
    assert snapshot.currency_code == "JPY"
    assert snapshot.kind is CameraCandidateKind.TOTAL

    with pytest.raises(CameraTokenError, match="does not belong"):
        load_camera_candidate_token(
            token,
            expected_scope="saved-scenario:18",
        )

    with pytest.raises(CameraTokenError, match="invalid"):
        load_camera_candidate_token(
            token + "tampered",
            expected_scope="saved-scenario:17",
        )


def test_confirmed_camera_token_contains_only_confirmed_money_scope():
    token = make_confirmed_camera_amount_token(
        scope="saved-scenario:17",
        amount=Decimal("4800"),
        currency_code="JPY",
    )

    snapshot = load_confirmed_camera_amount_token(
        token,
        expected_scope="saved-scenario:17",
    )

    assert snapshot.amount == Decimal("4800")
    assert snapshot.currency_code == "JPY"
    assert isinstance(snapshot.confirmation_id, UUID)

    raw_payload = signing.loads(
        token,
        salt="exchange.camera-confirmed.v1",
    )
    assert set(raw_payload) == {"scope", "amount", "currency_code", "confirmation_id"}
    assert raw_payload["confirmation_id"] == str(snapshot.confirmation_id)
