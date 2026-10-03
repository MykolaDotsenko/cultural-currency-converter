from __future__ import annotations

from decimal import Decimal

from apps.exchange.camera import (
    CameraAmountCandidate,
    CameraCandidateKind,
    CameraConfidence,
    CameraExtraction,
    SanitizedCameraImage,
)


class DeterministicTestCameraAmountExtractor:
    """Offline Camera extractor used only by browser/release-quality tests."""

    def extract(
        self,
        image: SanitizedCameraImage,
        *,
        expected_currency: str,
    ) -> CameraExtraction:
        currency = expected_currency.upper().strip()
        return CameraExtraction(
            candidates=(
                CameraAmountCandidate(
                    amount=Decimal("4800"),
                    currency_code=currency,
                    kind=CameraCandidateKind.TOTAL,
                    confidence=CameraConfidence.HIGH,
                ),
            ),
            provider_model="deterministic-camera-fixture",
            provider_response_id=f"fixture-{image.width}x{image.height}",
        )
