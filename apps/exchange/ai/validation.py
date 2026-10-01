from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from apps.exchange.ai.contracts import (
    ExplanationBullet,
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
    if set(payload) != {"headline", "bullets", "caveat"}:
        raise ExplanationValidationError("Explanation output has unexpected top-level fields.")

    headline = _validated_text(payload.get("headline"), field="headline", max_length=100)
    caveat = _validated_text(payload.get("caveat"), field="caveat", max_length=240)

    raw_bullets = payload.get("bullets")
    if not isinstance(raw_bullets, list) or not 1 <= len(raw_bullets) <= 4:
        raise ExplanationValidationError("Explanation must contain between 1 and 4 bullets.")

    bullets: list[ExplanationBullet] = []
    known_fact_ids = packet.fact_ids
    for index, raw_bullet in enumerate(raw_bullets):
        if not isinstance(raw_bullet, dict) or set(raw_bullet) != {
            "text",
            "supporting_fact_ids",
        }:
            raise ExplanationValidationError(f"Bullet {index + 1} has an invalid structure.")
        text = _validated_text(
            raw_bullet.get("text"),
            field=f"bullet {index + 1}",
            max_length=220,
        )
        raw_ids = raw_bullet.get("supporting_fact_ids")
        if not isinstance(raw_ids, list) or not 1 <= len(raw_ids) <= 6:
            raise ExplanationValidationError(
                f"Bullet {index + 1} must reference between 1 and 6 facts."
            )
        fact_ids: list[str] = []
        for fact_id in raw_ids:
            if not isinstance(fact_id, str) or fact_id not in known_fact_ids:
                raise ExplanationValidationError(
                    f"Bullet {index + 1} references an unknown fact ID."
                )
            if fact_id not in fact_ids:
                fact_ids.append(fact_id)
        bullets.append(ExplanationBullet(text=text, supporting_fact_ids=tuple(fact_ids)))

    cited_fact_ids = {fact_id for bullet in bullets for fact_id in bullet.supporting_fact_ids}
    missing_required = set(packet.required_fact_ids) - cited_fact_ids
    if missing_required:
        raise ExplanationValidationError(
            "Explanation does not ground the selected question in its required facts."
        )

    all_text = " ".join([headline, caveat, *(bullet.text for bullet in bullets)])
    _validate_semantics(all_text, packet=packet)

    return ExplanationResult(
        headline=headline,
        bullets=tuple(bullets),
        caveat=caveat,
        generated=True,
        source_label="AI-generated explanation",
    )


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
    if any(phrase in lowered for phrase in _FORBIDDEN_CAUSAL_PHRASES):
        raise ExplanationValidationError("Explanation makes an unsupported causal claim.")
    if any(phrase in lowered for phrase in _FORBIDDEN_ADVICE_PHRASES):
        raise ExplanationValidationError("Explanation contains financial or timing advice.")
    if any(phrase in lowered for phrase in _FORBIDDEN_MARKET_INTERPRETATIONS):
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


def _decimal_identity(value: str) -> Decimal:
    try:
        decimal_value = Decimal(value)
    except InvalidOperation as exc:
        raise ExplanationValidationError("Explanation contains an invalid number.") from exc
    if not decimal_value.is_finite():
        raise ExplanationValidationError("Explanation contains a non-finite number.")
    return decimal_value.normalize()
