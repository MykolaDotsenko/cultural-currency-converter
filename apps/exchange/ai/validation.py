from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from apps.exchange.ai.contracts import (
    ExplanationInsight,
    ExplanationPacket,
    ExplanationResult,
)

_HTML_RE = re.compile(r"<[^>]+>")
_URL_RE = re.compile(r"(?:https?://|www\.)", re.IGNORECASE)
_MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\([^)]+\)")
_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_YEAR_RE = re.compile(r"\b(?:18|19|20)\d{2}\b")
_CURRENCY_RE = re.compile(r"\b[A-Z]{3}\b")
_NUMBER_RE = re.compile(r"(?<![\w-])[-+]?\d+(?:[.,]\d+)?(?![\w-])")
_FORBIDDEN_CAUSAL_PHRASES = (
    "because",
    "caused",
    "causes",
    "led to",
    "leads to",
    "due to",
    "as a result",
    "resulted in",
)
_FORBIDDEN_ADVICE_PHRASES = (
    "you should exchange",
    "you should buy",
    "you should sell",
    "best time to",
    "good time to",
    "investment",
    "trading strategy",
    "profit",
    "guaranteed return",
    "make money",
)
_FORBIDDEN_MARKET_INTERPRETATIONS = (
    "stronger currency",
    "weaker currency",
    "currency strengthened",
    "currency weakened",
    "gain",
    "loss",
    "return on",
)


class ExplanationValidationError(ValueError):
    pass


def validate_provider_payload(
    payload: dict[str, Any],
    *,
    packet: ExplanationPacket,
) -> ExplanationResult:
    expected_fields = {"short_answer", "key_factors", "watch_out_for", "next_step"}
    if set(payload) != expected_fields:
        raise ExplanationValidationError("Explanation output has unexpected top-level fields.")

    short_answer = _validated_insight(
        payload.get("short_answer"),
        packet=packet,
        field="short answer",
        max_length=220,
    )

    raw_key_factors = payload.get("key_factors")
    if not isinstance(raw_key_factors, list) or not 1 <= len(raw_key_factors) <= 3:
        raise ExplanationValidationError("Explanation must contain between 1 and 3 key factors.")
    key_factors = tuple(
        _validated_insight(
            raw_factor,
            packet=packet,
            field=f"key factor {index + 1}",
            max_length=200,
        )
        for index, raw_factor in enumerate(raw_key_factors)
    )

    watch_out_for = _validated_insight(
        payload.get("watch_out_for"),
        packet=packet,
        field="watch out for",
        max_length=220,
    )
    next_step = _validated_insight(
        payload.get("next_step"),
        packet=packet,
        field="next step",
        max_length=220,
    )

    insights = (short_answer, *key_factors, watch_out_for, next_step)
    cited_fact_ids = {fact_id for insight in insights for fact_id in insight.supporting_fact_ids}
    missing_required = set(packet.required_fact_ids) - cited_fact_ids
    if missing_required:
        raise ExplanationValidationError(
            "Explanation does not ground the selected question in its required facts."
        )

    all_text = " ".join(insight.text for insight in insights)
    _validate_semantics(all_text, packet=packet)

    return ExplanationResult(
        short_answer=short_answer,
        key_factors=key_factors,
        watch_out_for=watch_out_for,
        next_step=next_step,
        generated=True,
        source_label="AI-generated explanation",
    )


def _validated_insight(
    value: Any,
    *,
    packet: ExplanationPacket,
    field: str,
    max_length: int,
) -> ExplanationInsight:
    if not isinstance(value, dict) or set(value) != {"text", "supporting_fact_ids"}:
        raise ExplanationValidationError(f"Explanation {field} has an invalid structure.")

    text = _validated_text(value.get("text"), field=field, max_length=max_length)
    raw_ids = value.get("supporting_fact_ids")
    if not isinstance(raw_ids, list) or not 1 <= len(raw_ids) <= 6:
        raise ExplanationValidationError(
            f"Explanation {field} must reference between 1 and 6 facts."
        )

    fact_ids: list[str] = []
    known_fact_ids = packet.fact_ids
    for fact_id in raw_ids:
        if not isinstance(fact_id, str) or fact_id not in known_fact_ids:
            raise ExplanationValidationError(f"Explanation {field} references an unknown fact ID.")
        if fact_id not in fact_ids:
            fact_ids.append(fact_id)

    return ExplanationInsight(text=text, supporting_fact_ids=tuple(fact_ids))


def _validated_text(value: Any, *, field: str, max_length: int) -> str:
    if not isinstance(value, str):
        raise ExplanationValidationError(f"Explanation {field} must be text.")
    normalized = " ".join(value.split())
    if not normalized:
        raise ExplanationValidationError(f"Explanation {field} cannot be empty.")
    if len(normalized) > max_length:
        raise ExplanationValidationError(f"Explanation {field} exceeds its length limit.")
    if any(ord(character) < 32 for character in normalized):
        raise ExplanationValidationError(f"Explanation {field} contains control characters.")
    if (
        _HTML_RE.search(normalized)
        or _URL_RE.search(normalized)
        or _MARKDOWN_LINK_RE.search(normalized)
        or chr(96) in normalized
    ):
        raise ExplanationValidationError(
            f"Explanation {field} contains disallowed markup or links."
        )
    return normalized


def _validate_semantics(text: str, *, packet: ExplanationPacket) -> None:
    lowered = text.casefold()
    if _contains_forbidden_phrase(lowered, _FORBIDDEN_CAUSAL_PHRASES):
        raise ExplanationValidationError("Explanation makes an unsupported causal claim.")
    if _contains_forbidden_phrase(lowered, _FORBIDDEN_ADVICE_PHRASES):
        raise ExplanationValidationError("Explanation contains financial or timing advice.")
    if _contains_forbidden_phrase(lowered, _FORBIDDEN_MARKET_INTERPRETATIONS):
        raise ExplanationValidationError("Explanation adds unsupported market interpretation.")
    if "%" in text:
        raise ExplanationValidationError("Explanation introduces an unsupported percentage.")

    allowed_uppercase = set(packet.allowed_currencies) | set(packet.allowed_uppercase_tokens)
    unknown_uppercase = set(_CURRENCY_RE.findall(text)) - allowed_uppercase
    if unknown_uppercase:
        raise ExplanationValidationError("Explanation introduces an unknown uppercase code.")

    allowed_dates = set(packet.allowed_dates)
    observed_dates = set(_DATE_RE.findall(text))
    if not observed_dates.issubset(allowed_dates):
        raise ExplanationValidationError("Explanation introduces an unknown date.")

    text_without_dates = _DATE_RE.sub("", text)
    allowed_years = {value[:4] for value in allowed_dates}
    observed_years = set(_YEAR_RE.findall(text_without_dates))
    if not observed_years.issubset(allowed_years):
        raise ExplanationValidationError("Explanation introduces an unsupported year.")

    allowed_numbers = {_decimal_identity(value) for value in packet.allowed_numbers}
    for raw_number in _NUMBER_RE.findall(text_without_dates):
        identity = _decimal_identity(raw_number.replace(",", "."))
        if identity not in allowed_numbers:
            raise ExplanationValidationError("Explanation introduces an unsupported number.")


def _contains_forbidden_phrase(text: str, phrases: tuple[str, ...]) -> bool:
    return any(re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text) for phrase in phrases)


def _decimal_identity(value: str) -> Decimal:
    try:
        decimal_value = Decimal(value)
    except InvalidOperation as exc:
        raise ExplanationValidationError("Explanation contains an invalid number.") from exc
    if not decimal_value.is_finite():
        raise ExplanationValidationError("Explanation contains a non-finite number.")
    return decimal_value.normalize()
