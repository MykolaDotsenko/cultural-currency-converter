from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings

from apps.exchange.camera import CameraExtractionCandidate, parse_camera_provider_payload
from apps.exchange.camera_media import PreparedCameraImage
from integrations.gemini.client import GeminiStructuredClient

_SYSTEM_INSTRUCTION = """You extract one travel-money price candidate from a user-supplied image.
Return structured data only. Do not return OCR text, merchant names, account numbers, card numbers,
PINs, or any other unrelated content. Extract one clearly visible amount only when it can be paired
with a defensible ISO 4217 currency code. If multiple totals/amounts are plausible, or the currency
cannot be determined from visible evidence, return found=false. A provided expected currency is only
a hint and must never override contradictory or ambiguous image evidence. This is extraction only:
do not calculate exchange rates, fees, affordability, or financial advice."""

_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "found": {"type": "boolean"},
        "amount": {"type": "string"},
        "currency_code": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "context_kind": {
            "type": "string",
            "enum": ["menu", "receipt", "shelf", "atm", "other"],
        },
    },
    "required": [
        "found",
        "amount",
        "currency_code",
        "confidence",
        "context_kind",
    ],
    "additionalProperties": False,
}


@dataclass(frozen=True, slots=True)
class GeminiCameraExtractor:
    client: GeminiStructuredClient
    model: str

    def extract(
        self,
        image: PreparedCameraImage,
        *,
        expected_currency: str = "",
    ) -> CameraExtractionCandidate:
        hint = (
            f"Expected currency hint: {expected_currency}. "
            if expected_currency
            else "No expected currency hint is available. "
        )
        prompt = (
            "Identify one clearly visible travel-money price or transaction amount. "
            f"{hint}"
            "If no single defensible amount+currency pair is visible, return found=false "
            "with empty amount and currency_code."
        )
        generation = self.client.generate_json_with_image(
            model=self.model,
            system_instruction=_SYSTEM_INSTRUCTION,
            prompt=prompt,
            image_bytes=image.data,
            image_mime_type=image.mime_type,
            response_json_schema=_RESPONSE_SCHEMA,
            max_output_tokens=220,
        )
        return parse_camera_provider_payload(
            generation.data,
            provider_model=generation.provider_model,
            response_id=generation.response_id,
        )


def build_camera_extractor() -> GeminiCameraExtractor | None:
    if not settings.AI_CAMERA_EXTRACTION_ENABLED:
        return None
    return GeminiCameraExtractor(
        client=GeminiStructuredClient(
            api_key=settings.GEMINI_API_KEY,
            timeout_seconds=settings.AI_TIMEOUT_SECONDS,
            max_attempts=settings.AI_MAX_ATTEMPTS,
        ),
        model=settings.AI_TEXT_MODEL,
    )
