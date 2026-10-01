from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ExplanationIntent(StrEnum):
    OVERVIEW = "overview"
    RATE_MEANING = "rate_meaning"
    PAYMENT_DIFFERENCE = "payment_difference"
    HISTORICAL_CONTEXT = "historical_context"
    STALE_REFERENCE = "stale_reference"


class ExplanationIntentError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ExplanationIntentSpec:
    intent: ExplanationIntent
    label: str
    question: str
    focus_instruction: str
    required_fact_ids: tuple[str, ...]


_SPECS = {
    ExplanationIntent.OVERVIEW: ExplanationIntentSpec(
        intent=ExplanationIntent.OVERVIEW,
        label="Explain this",
        question="What does this reference conversion mean?",
        focus_instruction=(
            "Summarize the displayed reference conversion, its observation timing and its "
            "reference-rate limitation."
        ),
        required_fact_ids=(),
    ),
    ExplanationIntent.RATE_MEANING: ExplanationIntentSpec(
        intent=ExplanationIntent.RATE_MEANING,
        label="What does this rate mean?",
        question="What does this reference rate mean?",
        focus_instruction=(
            "Explain what the displayed reference rate and effective observation date mean. "
            "Do not speculate about why the rate has this value."
        ),
        required_fact_ids=("rate", "effective_date"),
    ),
    ExplanationIntent.PAYMENT_DIFFERENCE: ExplanationIntentSpec(
        intent=ExplanationIntent.PAYMENT_DIFFERENCE,
        label="Why might my bank or card differ?",
        question="Why might my bank or card show a different result?",
        focus_instruction=(
            "Explain only the supplied limitation of the reference rate versus a payment-provider "
            "outcome. Do not invent a bank, card, markup or fee."
        ),
        required_fact_ids=("reference_scope",),
    ),
    ExplanationIntent.HISTORICAL_CONTEXT: ExplanationIntentSpec(
        intent=ExplanationIntent.HISTORICAL_CONTEXT,
        label="What date does this historical rate represent?",
        question="What date does this historical reference rate represent?",
        focus_instruction=(
            "Explain the requested and effective historical dates using only the supplied "
            "historical facts. Keep historical FX separate from purchasing power."
        ),
        required_fact_ids=("effective_date", "historical_status"),
    ),
    ExplanationIntent.STALE_REFERENCE: ExplanationIntentSpec(
        intent=ExplanationIntent.STALE_REFERENCE,
        label="Why is this result marked cached?",
        question="Why is this reference result marked cached?",
        focus_instruction=(
            "Explain only the supplied stale/cached-reference status and observation date. "
            "Do not imply the cached value is fresh."
        ),
        required_fact_ids=("stale_status",),
    ),
}


def explanation_intent_spec(intent: ExplanationIntent) -> ExplanationIntentSpec:
    return _SPECS[intent]


def parse_explanation_intent(value: str | None) -> ExplanationIntent:
    normalized = (value or "").strip()
    if not normalized:
        return ExplanationIntent.OVERVIEW
    try:
        return ExplanationIntent(normalized)
    except ValueError as exc:
        raise ExplanationIntentError("Unknown explanation question.") from exc


def available_explanation_intents(
    *,
    historical: bool,
    stale: bool,
) -> tuple[ExplanationIntentSpec, ...]:
    intents = [ExplanationIntent.RATE_MEANING]
    if historical:
        intents.append(ExplanationIntent.HISTORICAL_CONTEXT)
    else:
        intents.append(ExplanationIntent.PAYMENT_DIFFERENCE)
        if stale:
            intents.append(ExplanationIntent.STALE_REFERENCE)
    return tuple(explanation_intent_spec(intent) for intent in intents)


def ensure_explanation_intent_available(
    intent: ExplanationIntent,
    *,
    historical: bool,
    stale: bool,
) -> ExplanationIntentSpec:
    if intent is ExplanationIntent.OVERVIEW:
        return explanation_intent_spec(intent)
    available = {
        spec.intent
        for spec in available_explanation_intents(
            historical=historical,
            stale=stale,
        )
    }
    if intent not in available:
        raise ExplanationIntentError("Explanation question is not available for this conversion.")
    return explanation_intent_spec(intent)
