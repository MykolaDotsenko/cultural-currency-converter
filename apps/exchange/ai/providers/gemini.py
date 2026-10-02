from __future__ import annotations

from apps.exchange.ai.contracts import ExplanationPacket, ProviderExplanation
from apps.exchange.ai.prompts import RESPONSE_JSON_SCHEMA, SYSTEM_INSTRUCTION, build_user_content
from integrations.gemini.client import GeminiStructuredClient


class GeminiExplanationDrafter:
    def __init__(
        self,
        *,
        client: GeminiStructuredClient,
        model: str,
        system_instruction: str = SYSTEM_INSTRUCTION,
    ) -> None:
        self._client = client
        self._model = model
        self._system_instruction = system_instruction

    def draft(self, packet: ExplanationPacket) -> ProviderExplanation:
        generation = self._client.generate_json(
            model=self._model,
            system_instruction=self._system_instruction,
            contents=build_user_content(packet),
            response_json_schema=RESPONSE_JSON_SCHEMA,
        )
        return ProviderExplanation(
            payload=generation.data,
            provider_model=generation.provider_model,
            response_id=generation.response_id,
            usage=generation.usage,
        )
