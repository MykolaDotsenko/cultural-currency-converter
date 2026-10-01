from __future__ import annotations

from apps.exchange.ai.contracts import ExplanationPacket, GroundedFact, ProviderExplanation
from integrations.gemini.errors import AIProviderTimeout
from integrations.gemini.models import ProviderUsage


class DeterministicTestExplanationDrafter:
    """Offline runtime-AI drafter for browser/release-quality tests only."""

    def draft(self, packet: ExplanationPacket) -> ProviderExplanation:
        if packet.intent_id == "payment_difference":
            raise AIProviderTimeout("Deterministic browser fixture timeout.")

        facts = {fact.id: fact for fact in packet.facts}
        required = [
            facts[fact_id]
            for fact_id in packet.required_fact_ids
            if fact_id in facts
        ]
        primary = required[0] if required else _preferred_fact(facts, "conversion", "rate")
        factor_candidates = required[1:] or [
            _preferred_fact(facts, "effective_date", "rate", "conversion")
        ]
        key_factors = [
            _grounded(fact)
            for fact in _dedupe_facts(factor_candidates)
        ][:3]

        scope = facts.get("historical_scope") if packet.intent_id == "historical_context" else None
        scope = scope or facts.get("reference_scope") or primary
        next_step_support = facts.get("reference_scope") or facts.get("effective_date") or primary

        return ProviderExplanation(
            payload={
                "short_answer": _grounded(primary),
                "key_factors": key_factors,
                "watch_out_for": _grounded(scope),
                "next_step": {
                    "text": "Use this reference observation as a comparison point.",
                    "supporting_fact_ids": [next_step_support.id],
                },
            },
            provider_model="deterministic-browser-fixture",
            response_id=f"fixture-{packet.intent_id}",
            usage=ProviderUsage(input_tokens=0, output_tokens=0, total_tokens=0),
        )


def _preferred_fact(facts: dict[str, GroundedFact], *fact_ids: str) -> GroundedFact:
    for fact_id in fact_ids:
        if fact_id in facts:
            return facts[fact_id]
    return next(iter(facts.values()))


def _grounded(fact: GroundedFact) -> dict[str, object]:
    return {
        "text": fact.statement,
        "supporting_fact_ids": [fact.id],
    }


def _dedupe_facts(facts: list[GroundedFact]) -> list[GroundedFact]:
    result: list[GroundedFact] = []
    seen: set[str] = set()
    for fact in facts:
        if fact.id in seen:
            continue
        seen.add(fact.id)
        result.append(fact)
    return result
