from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import httpx
from google import genai
from google.genai import errors, types

from integrations.gemini.errors import (
    AIConfigurationError,
    AIInvalidResponse,
    AIProviderTimeout,
    AIProviderUnavailable,
    AIRateLimited,
    AIRefusal,
    AISafetyBlocked,
)
from integrations.gemini.models import ProviderUsage, StructuredGeneration

_RETRYABLE_STATUS_CODES = frozenset({408, 500, 502, 503, 504})


class GeminiStructuredClient:
    """Narrow server-side Gemini transport for schema-constrained text output."""

    def __init__(
        self,
        *,
        api_key: str,
        timeout_seconds: float,
        max_attempts: int,
    ) -> None:
        if not api_key.strip():
            raise AIConfigurationError("Gemini API key is required.")
        if not 0.5 <= timeout_seconds <= 15:
            raise AIConfigurationError("Gemini timeout is outside the supported runtime range.")
        if max_attempts not in {1, 2}:
            raise AIConfigurationError("Gemini max attempts must be 1 or 2.")

        self._max_attempts = max_attempts
        self._client = genai.Client(
            api_key=api_key.strip(),
            http_options=types.HttpOptions(timeout=round(timeout_seconds * 1000)),
        )

    def generate_json(
        self,
        *,
        model: str,
        system_instruction: str,
        contents: str,
        response_json_schema: Mapping[str, Any],
        max_output_tokens: int = 700,
    ) -> StructuredGeneration:
        if not contents.strip():
            raise AIConfigurationError(
                "Gemini structured generation requires instructions and content."
            )
        return self._generate_json_contents(
            model=model,
            system_instruction=system_instruction,
            contents=contents,
            response_json_schema=response_json_schema,
            max_output_tokens=max_output_tokens,
        )

    def generate_json_with_image(
        self,
        *,
        model: str,
        system_instruction: str,
        prompt: str,
        image_bytes: bytes,
        image_mime_type: str,
        response_json_schema: Mapping[str, Any],
        max_output_tokens: int = 350,
    ) -> StructuredGeneration:
        if not prompt.strip() or not image_bytes:
            raise AIConfigurationError(
                "Gemini image understanding requires a prompt and image bytes."
            )
        if image_mime_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise AIConfigurationError("Gemini image MIME type is not supported.")

        contents = [
            types.Part.from_bytes(data=image_bytes, mime_type=image_mime_type),
            prompt,
        ]
        return self._generate_json_contents(
            model=model,
            system_instruction=system_instruction,
            contents=contents,
            response_json_schema=response_json_schema,
            max_output_tokens=max_output_tokens,
        )

    def _generate_json_contents(
        self,
        *,
        model: str,
        system_instruction: str,
        contents: Any,
        response_json_schema: Mapping[str, Any],
        max_output_tokens: int,
    ) -> StructuredGeneration:
        if not model.strip():
            raise AIConfigurationError("Gemini model is required.")
        if not system_instruction.strip():
            raise AIConfigurationError(
                "Gemini structured generation requires a system instruction."
            )

        for attempt in range(1, self._max_attempts + 1):
            try:
                response = self._client.models.generate_content(
                    model=model,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        response_mime_type="application/json",
                        response_json_schema=dict(response_json_schema),
                        temperature=0.1,
                        max_output_tokens=max_output_tokens,
                    ),
                )
            except errors.APIError as exc:
                status = int(getattr(exc, "code", 0) or 0)
                if status in {401, 403}:
                    raise AIConfigurationError("Gemini authentication failed.") from exc
                if status == 429:
                    raise AIRateLimited("Gemini quota or rate limit was reached.") from exc
                if status in _RETRYABLE_STATUS_CODES and attempt < self._max_attempts:
                    continue
                if status == 408:
                    raise AIProviderTimeout("Gemini request timed out.") from exc
                if status >= 500:
                    raise AIProviderUnavailable("Gemini is temporarily unavailable.") from exc
                raise AIInvalidResponse(
                    f"Gemini rejected the structured request (HTTP {status})."
                ) from exc
            except (httpx.TimeoutException, TimeoutError) as exc:
                if attempt < self._max_attempts:
                    continue
                raise AIProviderTimeout("Gemini request timed out.") from exc
            except httpx.TransportError as exc:
                if attempt < self._max_attempts:
                    continue
                raise AIProviderUnavailable("Gemini transport is temporarily unavailable.") from exc

            return self._normalize_response(response, requested_model=model)

        raise AIProviderUnavailable("Gemini generation exhausted its bounded retry policy.")

    @staticmethod
    def _normalize_response(response: Any, *, requested_model: str) -> StructuredGeneration:
        prompt_feedback = getattr(response, "prompt_feedback", None)
        block_reason = getattr(prompt_feedback, "block_reason", None)
        if block_reason:
            raise AISafetyBlocked("Gemini blocked the explanation request.")

        parsed = getattr(response, "parsed", None)
        if isinstance(parsed, dict):
            data = parsed
        else:
            text = getattr(response, "text", None)
            if not isinstance(text, str) or not text.strip():
                candidates = getattr(response, "candidates", None) or ()
                finish_reasons = {
                    str(getattr(candidate, "finish_reason", "")).upper()
                    for candidate in candidates
                }
                if any("SAFETY" in reason for reason in finish_reasons):
                    raise AISafetyBlocked("Gemini blocked the explanation output.")
                raise AIRefusal("Gemini returned no usable explanation.")
            try:
                decoded = json.loads(text)
            except json.JSONDecodeError as exc:
                raise AIInvalidResponse("Gemini returned malformed structured JSON.") from exc
            if not isinstance(decoded, dict):
                raise AIInvalidResponse("Gemini structured output must be a JSON object.")
            data = decoded

        usage_metadata = getattr(response, "usage_metadata", None)
        usage = ProviderUsage(
            input_tokens=_positive_int_or_none(
                getattr(usage_metadata, "prompt_token_count", None)
            ),
            output_tokens=_positive_int_or_none(
                getattr(usage_metadata, "candidates_token_count", None)
            ),
            total_tokens=_positive_int_or_none(
                getattr(usage_metadata, "total_token_count", None)
            ),
        )
        provider_model = str(getattr(response, "model_version", "") or requested_model)
        response_id = getattr(response, "response_id", None)
        return StructuredGeneration(
            data=data,
            provider_model=provider_model,
            response_id=str(response_id) if response_id else None,
            usage=usage,
        )


def _positive_int_or_none(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value
