from __future__ import annotations

from django.conf import settings

from apps.exchange.camera import CameraExtraction, normalize_camera_payload
from integrations.gemini.client import GeminiStructuredClient

_CAMERA_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {
            "type": "string",
            "enum": ["candidate", "ambiguous", "no_price"],
        },
        "amount": {"type": "string"},
        "currency_code": {"type": "string"},
        "confidence": {
            "type": "string",
            "enum": ["high", "medium", "low"],
        },
        "kind": {
            "type": "string",
            "enum": ["total", "item", "atm", "unknown"],
        },
    },
    "required": ["status", "amount", "currency_code", "confidence", "kind"],
    "additionalProperties": False,
}

_CAMERA_SYSTEM_INSTRUCTION = """
You extract one travel-money amount from a user-supplied image.

Return only the required JSON schema.

Rules:
- Prefer one clearly salient amount: a receipt total, one focused item price, or an ATM amount.
- If several amounts are equally plausible, use status "ambiguous".
- If no usable monetary amount is visible, use status "no_price".
- For candidate status, amount must use ASCII digits and at most one decimal point.
- Never include thousands separators, currency symbols, labels, or prose in amount.
- currency_code must be an uppercase ISO 4217 code when reasonably supported by the image.
- If currency identity is too ambiguous to propose safely, use status "ambiguous".
- Do not infer bank credentials, card numbers, account data, merchant identity, or personal details.
- Do not calculate exchange rates or fees.
- The user will explicitly confirm or correct the extracted amount and currency before conversion.
""".strip()

_CAMERA_USER_CONTENT = """
Inspect only the supplied image for one monetary amount suitable for travel-money conversion.
Do not transcribe unrelated text. Do not explain your choice.
""".strip()


class GeminiCameraExtractor:
    def __init__(
        self,
        *,
        client: GeminiStructuredClient,
        model: str,
    ) -> None:
        self._client = client
        self._model = model

    def extract(self, *, image_bytes: bytes, mime_type: str) -> CameraExtraction:
        generation = self._client.generate_json_with_image(
            model=self._model,
            system_instruction=_CAMERA_SYSTEM_INSTRUCTION,
            contents=_CAMERA_USER_CONTENT,
            image_bytes=image_bytes,
            image_mime_type=mime_type,
            response_json_schema=_CAMERA_RESPONSE_SCHEMA,
        )
        return normalize_camera_payload(
            generation.data,
            provider_model=generation.provider_model,
            response_id=generation.response_id,
            usage=generation.usage,
        )


def build_camera_extractor() -> GeminiCameraExtractor | None:
    if not bool(settings.AI_CAMERA_EXTRACTION_ENABLED):
        return None

    client = GeminiStructuredClient(
        api_key=settings.GEMINI_API_KEY,
        timeout_seconds=settings.AI_TIMEOUT_SECONDS,
        max_attempts=settings.AI_MAX_ATTEMPTS,
    )
    return GeminiCameraExtractor(
        client=client,
        model=settings.AI_CAMERA_MODEL,
    )
