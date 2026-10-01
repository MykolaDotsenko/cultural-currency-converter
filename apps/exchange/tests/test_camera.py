from __future__ import annotations

from decimal import Decimal

import pytest
from django.test import override_settings

from apps.exchange.camera import (
    CameraAmountKind,
    CameraCandidate,
    CameraConfidence,
    CameraExtractionState,
    CameraExtractionValidationError,
    dump_camera_candidate,
    load_camera_candidate,
    normalize_camera_payload,
    safely_extract_camera_candidate,
)
from integrations.gemini.errors import AIProviderUnavailable


def test_normalize_camera_candidate_is_strict_and_decimal_safe():
    extraction = normalize_camera_payload(
        {
            "status": "candidate",
            "amount": "4800",
            "currency_code": "jpy",
            "confidence": "high",
            "kind": "total",
        }
    )

    assert extraction.state is CameraExtractionState.CANDIDATE
    assert extraction.candidate is not None
    assert extraction.candidate.amount == Decimal("4800")
    assert extraction.candidate.currency_code == "JPY"
    assert extraction.candidate.confidence is CameraConfidence.HIGH
    assert extraction.candidate.kind is CameraAmountKind.TOTAL


@pytest.mark.parametrize(
    "payload",
    [
        {
            "status": "candidate",
            "amount": "4,800",
            "currency_code": "JPY",
            "confidence": "high",
            "kind": "total",
        },
        {
            "status": "candidate",
            "amount": "-1",
            "currency_code": "JPY",
            "confidence": "high",
            "kind": "total",
        },
        {
            "status": "candidate",
            "amount": "1",
            "currency_code": "not-a-code",
            "confidence": "high",
            "kind": "total",
        },
        {
            "status": "candidate",
            "amount": "1",
            "currency_code": "JPY",
            "confidence": "certain",
            "kind": "total",
        },
    ],
)
def test_invalid_camera_candidate_payload_fails_closed(payload):
    with pytest.raises(CameraExtractionValidationError):
        normalize_camera_payload(payload)


@pytest.mark.parametrize("state", ["ambiguous", "no_price", "unavailable"])
def test_non_candidate_states_carry_no_financial_value(state):
    extraction = normalize_camera_payload({"status": state})

    assert extraction.state.value == state
    assert extraction.candidate is None


@override_settings(SECRET_KEY="camera-test-secret")
def test_camera_confirmation_token_round_trips_without_image_data():
    candidate = CameraCandidate(
        amount=Decimal("4800"),
        currency_code="JPY",
        confidence=CameraConfidence.MEDIUM,
        kind=CameraAmountKind.ITEM,
    )

    token = dump_camera_candidate(candidate)
    snapshot = load_camera_candidate(token)

    assert "4800" not in token
    assert snapshot.amount == Decimal("4800")
    assert snapshot.currency_code == "JPY"
    assert snapshot.confidence is CameraConfidence.MEDIUM
    assert snapshot.kind is CameraAmountKind.ITEM


@override_settings(SECRET_KEY="camera-test-secret")
def test_camera_confirmation_token_rejects_tampering():
    candidate = CameraCandidate(
        amount=Decimal("4800"),
        currency_code="JPY",
        confidence=CameraConfidence.HIGH,
        kind=CameraAmountKind.TOTAL,
    )
    token = dump_camera_candidate(candidate)
    replacement = "A" if token[-1] != "A" else "B"

    with pytest.raises(CameraExtractionValidationError, match="expired or is invalid"):
        load_camera_candidate(token[:-1] + replacement)


class _UnavailableExtractor:
    def extract(self, *, image_bytes: bytes, mime_type: str):
        raise AIProviderUnavailable("provider unavailable")


def test_provider_failure_degrades_without_creating_a_candidate():
    extraction = safely_extract_camera_candidate(
        _UnavailableExtractor(),
        image_bytes=b"image",
        mime_type="image/png",
    )

    assert extraction.state is CameraExtractionState.UNAVAILABLE
    assert extraction.candidate is None
