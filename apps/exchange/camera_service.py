from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from django.conf import settings
from django.db import transaction

from apps.exchange.ai.providers.deterministic_camera import DeterministicTestCameraAmountExtractor
from apps.exchange.ai.providers.gemini_camera import GeminiCameraAmountExtractor
from apps.exchange.camera import (
    CameraAmountExtractor,
    CameraExtraction,
    CameraExtractionError,
    CameraNoAmountFound,
    sanitize_camera_image,
)
from integrations.gemini.client import GeminiStructuredClient
from integrations.gemini.errors import AIProviderError

logger = logging.getLogger("cultural_currency.ai")


class CameraFeatureDisabled(RuntimeError):
    pass


class CameraProviderUnavailable(RuntimeError):
    pass


class CameraTransactionPolicyError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CameraScanDelivery:
    extraction: CameraExtraction
    image_width: int
    image_height: int


class CameraExtractionService:
    def __init__(
        self,
        *,
        enabled: bool,
        extractor: CameraAmountExtractor | None,
    ) -> None:
        self.enabled = enabled
        self._extractor = extractor

    def scan(
        self,
        raw_image: bytes,
        *,
        content_type: str,
        expected_currency: str,
    ) -> CameraScanDelivery:
        if not self.enabled or self._extractor is None:
            raise CameraFeatureDisabled("Camera extraction is not enabled.")

        image = sanitize_camera_image(raw_image, content_type=content_type)

        connection = transaction.get_connection()
        if connection.in_atomic_block:
            raise CameraTransactionPolicyError(
                "Live camera extraction is forbidden inside database transactions."
            )

        started = time.perf_counter()
        try:
            extraction = self._extractor.extract(
                image,
                expected_currency=expected_currency,
            )
        except CameraNoAmountFound:
            logger.info(
                "Camera extraction found no monetary amount",
                extra={
                    "capability": "camera_amount_extraction",
                    "provider": "google",
                    "operation": "extract",
                    "outcome": "no_amount",
                    "latency_ms": round((time.perf_counter() - started) * 1000),
                },
            )
            raise
        except CameraExtractionError as exc:
            logger.warning(
                "Camera extraction returned invalid structured data",
                extra={
                    "capability": "camera_amount_extraction",
                    "provider": "google",
                    "operation": "extract",
                    "outcome": "invalid_response",
                    "error_code": exc.__class__.__name__,
                    "latency_ms": round((time.perf_counter() - started) * 1000),
                },
            )
            raise CameraProviderUnavailable(
                "Camera extraction returned an invalid response."
            ) from exc
        except AIProviderError as exc:
            logger.warning(
                "Camera extraction provider unavailable",
                extra={
                    "capability": "camera_amount_extraction",
                    "provider": "google",
                    "operation": "extract",
                    "outcome": exc.__class__.__name__,
                    "latency_ms": round((time.perf_counter() - started) * 1000),
                },
            )
            raise CameraProviderUnavailable(
                "Camera extraction is temporarily unavailable."
            ) from exc

        logger.info(
            "Camera extraction success",
            extra={
                "capability": "camera_amount_extraction",
                "provider": "google",
                "model": extraction.provider_model,
                "operation": "extract",
                "outcome": "success",
                "candidate_count": len(extraction.candidates),
                "latency_ms": round((time.perf_counter() - started) * 1000),
            },
        )
        return CameraScanDelivery(
            extraction=extraction,
            image_width=image.width,
            image_height=image.height,
        )


def build_camera_extraction_service() -> CameraExtractionService:
    enabled = bool(settings.AI_CAMERA_EXTRACTION_ENABLED)
    if not enabled:
        return CameraExtractionService(enabled=False, extractor=None)

    if settings.AI_CAMERA_TEST_FIXTURE_ENABLED:
        return CameraExtractionService(
            enabled=True,
            extractor=DeterministicTestCameraAmountExtractor(),
        )

    client = GeminiStructuredClient(
        api_key=settings.GEMINI_API_KEY,
        timeout_seconds=settings.AI_TIMEOUT_SECONDS,
        max_attempts=settings.AI_MAX_ATTEMPTS,
    )
    extractor = GeminiCameraAmountExtractor(
        client=client,
        model=settings.AI_TEXT_MODEL,
    )
    return CameraExtractionService(enabled=True, extractor=extractor)
