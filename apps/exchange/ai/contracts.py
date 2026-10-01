from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Protocol

from integrations.gemini.models import ProviderUsage


@dataclass(frozen=True, slots=True)
class GroundedFact:
    id: str
    statement: str


@dataclass(frozen=True, slots=True)
class ExplanationPacket:
    packet_version: str
    locale: str
    intent_id: str
    intent_question: str
    focus_instruction: str
    required_fact_ids: tuple[str, ...]
    facts: tuple[GroundedFact, ...]
    allowed_currencies: tuple[str, ...]
    allowed_uppercase_tokens: tuple[str, ...]
    allowed_dates: tuple[str, ...]
    allowed_numbers: tuple[str, ...]

    def canonical_json(self) -> str:
        payload = {
            "packet_version": self.packet_version,
            "locale": self.locale,
            "intent_id": self.intent_id,
            "intent_question": self.intent_question,
            "focus_instruction": self.focus_instruction,
            "required_fact_ids": list(self.required_fact_ids),
            "facts": [asdict(fact) for fact in self.facts],
            "allowed_currencies": list(self.allowed_currencies),
            "allowed_uppercase_tokens": list(self.allowed_uppercase_tokens),
            "allowed_dates": list(self.allowed_dates),
            "allowed_numbers": list(self.allowed_numbers),
        }
        return json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)

    @property
    def packet_hash(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @property
    def fact_ids(self) -> frozenset[str]:
        return frozenset(fact.id for fact in self.facts)


@dataclass(frozen=True, slots=True)
class ExplanationInsight:
    text: str
    supporting_fact_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ExplanationResult:
    short_answer: ExplanationInsight
    key_factors: tuple[ExplanationInsight, ...]
    watch_out_for: ExplanationInsight
    next_step: ExplanationInsight
    generated: bool
    source_label: str
    fallback_reason: str = ""

    def as_json(self) -> dict[str, object]:
        def serialize(item: ExplanationInsight) -> dict[str, object]:
            return {
                "text": item.text,
                "supporting_fact_ids": list(item.supporting_fact_ids),
            }

        return {
            "short_answer": serialize(self.short_answer),
            "key_factors": [serialize(item) for item in self.key_factors],
            "watch_out_for": serialize(self.watch_out_for),
            "next_step": serialize(self.next_step),
            "generated": self.generated,
            "source_label": self.source_label,
            "fallback_reason": self.fallback_reason,
        }


@dataclass(frozen=True, slots=True)
class ProviderExplanation:
    payload: dict[str, object]
    provider_model: str
    response_id: str | None
    usage: ProviderUsage


class ExplanationDrafter(Protocol):
    def draft(self, packet: ExplanationPacket) -> ProviderExplanation: ...
