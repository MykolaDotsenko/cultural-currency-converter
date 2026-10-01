from __future__ import annotations

from apps.exchange.camera import (
    CameraExtraction,
    SanitizedCameraImage,
    normalize_camera_provider_payload,
)
from integrations.gemini.client import GeminiStructuredClient

_CAMERA_SYSTEM_INSTRUCTION = """You extract visible monetary amount candidates from a
user-supplied travel-money image.

Return only the structured monetary fields requested by the schema.
Do not return or transcribe merchant names, personal names, addresses, account numbers,
card numbers, phone numbers, loyalty identifiers, receipt text, or any other surrounding
content.

Never infer hidden or unreadable digits. If the currency is not explicit or unambiguous,
return an empty currency_code. The expected currency is contextual guidance only and must
not override a clearly visible conflicting currency.

Prefer the payable total, amount due, selected ATM amount, or clearly prominent price.
Line-item amounts may be returned when useful. Return at most six candidates.
"""

_CAMERA_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "candidates": {
            "type": "array",
            "maxItems": 6,
            "items": {
                "type": "object",
                "properties": {
                    "amount": {"type": "string"},
                    "currency_code": {"type": "string"},
                    "kind": {
                        "type": "string",
                        "enum": ["total", "line_item", "atm_amount", "other"],
                    },
                    "confidence": {
                        "type": "string",
                        "enum": ["high", "medium", "low"],
                    },
                },
                "required": ["amount", "currency_code", "kind", "confidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["candidates"],
    "additionalProperties": False,
}


class GeminiCameraAmountExtractor:
    """Ephemeral multimodal adapter for monetary amount candidates."""

    def __init__(
        self,
        *,
        client: GeminiStructuredClient,
        model: str,
    ) -> None:
        self._client = client
        self._model = model

    def extract(
        self,
        image: SanitizedCameraImage,
        *,
        expected_currency: str,
    ) -> CameraExtraction:
        generation = self._client.generate_json_with_image(
            model=self._model,
            system_instruction=_CAMERA_SYSTEM_INSTRUCTION,
            prompt=(
                "Extract visible monetary amount candidates. "
                f"Expected trip currency: {expected_currency.upper().strip() or 'unknown'}."
            ),
            image_bytes=image.data,
            image_mime_type=image.mime_type,
            response_json_schema=_CAMERA_RESPONSE_SCHEMA,
            max_output_tokens=500,
        )
        return normalize_camera_provider_payload(
            generation.data,
            provider_model=generation.provider_model,
            provider_response_id=generation.response_id,
        )
