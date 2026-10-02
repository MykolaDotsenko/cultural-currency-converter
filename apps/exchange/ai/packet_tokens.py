from __future__ import annotations

import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from django.core import signing

from apps.exchange.ai.contracts import ExplanationPacket, GroundedFact
from apps.exchange.trusted_snapshot import TOKEN_MAX_AGE_SECONDS

_TOKEN_SALT = "exchange.grounded-explanation-packet:v1"
_MAX_TOKEN_LENGTH = 32768
_CAPABILITY_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_FACT_ID_RE = re.compile(r"^[a-z][a-z0-9_:-]{0,63}$")
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_UPPERCASE_TOKEN_RE = re.compile(r"^[A-Z][A-Z0-9_-]{1,15}$")


class GroundedPacketTokenError(ValueError):
    """Raised when a signed grounded-explanation packet cannot be trusted."""


def build_grounded_packet_token(
    packet: ExplanationPacket,
    *,
    capability: str,
) -> str:
    normalized_capability = _validate_capability(capability)
    packet_payload = json.loads(packet.canonical_json())
    _packet_from_payload(packet_payload)
    return signing.dumps(
        {
            "v": 1,
            "capability": normalized_capability,
            "packet": packet_payload,
        },
        salt=_TOKEN_SALT,
        compress=True,
    )


def load_grounded_packet_token(
    token: str,
    *,
    expected_capability: str,
    max_age: int = TOKEN_MAX_AGE_SECONDS,
) -> ExplanationPacket:
    if not isinstance(token, str) or not token or len(token) > _MAX_TOKEN_LENGTH:
        raise GroundedPacketTokenError("Grounded explanation token is missing or invalid.")

    try:
        payload = signing.loads(token, salt=_TOKEN_SALT, max_age=max_age)
    except signing.SignatureExpired as exc:
        raise GroundedPacketTokenError("Grounded explanation token has expired.") from exc
    except signing.BadSignature as exc:
        raise GroundedPacketTokenError("Grounded explanation token is invalid.") from exc

    if not isinstance(payload, dict) or payload.get("v") != 1:
        raise GroundedPacketTokenError("Grounded explanation token version is unsupported.")

    capability = payload.get("capability")
    if capability != _validate_capability(expected_capability):
        raise GroundedPacketTokenError("Grounded explanation token capability is invalid.")

    return _packet_from_payload(payload.get("packet"))


def _packet_from_payload(value: Any) -> ExplanationPacket:
    if not isinstance(value, dict):
        raise GroundedPacketTokenError("Grounded explanation packet is invalid.")

    expected_fields = {
        "packet_version",
        "locale",
        "intent_id",
        "intent_question",
        "focus_instruction",
        "required_fact_ids",
        "facts",
        "allowed_currencies",
        "allowed_uppercase_tokens",
        "allowed_dates",
        "allowed_numbers",
    }
    if set(value) != expected_fields:
        raise GroundedPacketTokenError("Grounded explanation packet fields are invalid.")

    packet_version = _bounded_text(value["packet_version"], field="packet version", maximum=96)
    locale = _bounded_text(value["locale"], field="locale", maximum=24)
    intent_id = _bounded_text(value["intent_id"], field="intent", maximum=64)
    intent_question = _bounded_text(
        value["intent_question"],
        field="intent question",
        maximum=320,
    )
    focus_instruction = _bounded_text(
        value["focus_instruction"],
        field="focus instruction",
        maximum=640,
    )

    raw_facts = value["facts"]
    if not isinstance(raw_facts, list) or not 1 <= len(raw_facts) <= 24:
        raise GroundedPacketTokenError("Grounded explanation facts are invalid.")

    facts: list[GroundedFact] = []
    seen_fact_ids: set[str] = set()
    for raw_fact in raw_facts:
        if not isinstance(raw_fact, dict) or set(raw_fact) != {"id", "statement"}:
            raise GroundedPacketTokenError("Grounded explanation fact structure is invalid.")
        fact_id = _bounded_text(raw_fact["id"], field="fact id", maximum=64)
        if not _FACT_ID_RE.fullmatch(fact_id) or fact_id in seen_fact_ids:
            raise GroundedPacketTokenError("Grounded explanation fact identity is invalid.")
        statement = _bounded_text(raw_fact["statement"], field="fact statement", maximum=720)
        seen_fact_ids.add(fact_id)
        facts.append(GroundedFact(id=fact_id, statement=statement))

    required_fact_ids = _string_list(
        value["required_fact_ids"],
        field="required facts",
        maximum_items=8,
        item_maximum=64,
    )
    if any(
        not _FACT_ID_RE.fullmatch(fact_id) or fact_id not in seen_fact_ids
        for fact_id in required_fact_ids
    ):
        raise GroundedPacketTokenError("Grounded explanation required facts are invalid.")

    currencies = _string_list(
        value["allowed_currencies"],
        field="allowed currencies",
        maximum_items=8,
        item_maximum=3,
    )
    if any(not _CURRENCY_RE.fullmatch(code) for code in currencies):
        raise GroundedPacketTokenError("Grounded explanation currency allow-list is invalid.")

    uppercase_tokens = _string_list(
        value["allowed_uppercase_tokens"],
        field="allowed uppercase tokens",
        maximum_items=32,
        item_maximum=16,
    )
    if any(not _UPPERCASE_TOKEN_RE.fullmatch(token) for token in uppercase_tokens):
        raise GroundedPacketTokenError("Grounded explanation token allow-list is invalid.")

    allowed_dates = _string_list(
        value["allowed_dates"],
        field="allowed dates",
        maximum_items=32,
        item_maximum=10,
    )
    try:
        for raw_date in allowed_dates:
            date.fromisoformat(raw_date)
    except ValueError as exc:
        raise GroundedPacketTokenError("Grounded explanation date allow-list is invalid.") from exc

    allowed_numbers = _string_list(
        value["allowed_numbers"],
        field="allowed numbers",
        maximum_items=96,
        item_maximum=80,
    )
    try:
        for raw_number in allowed_numbers:
            parsed = Decimal(raw_number)
            if not parsed.is_finite():
                raise InvalidOperation
    except (InvalidOperation, ValueError) as exc:
        raise GroundedPacketTokenError("Grounded explanation number allow-list is invalid.") from exc

    return ExplanationPacket(
        packet_version=packet_version,
        locale=locale,
        intent_id=intent_id,
        intent_question=intent_question,
        focus_instruction=focus_instruction,
        required_fact_ids=required_fact_ids,
        facts=tuple(facts),
        allowed_currencies=currencies,
        allowed_uppercase_tokens=uppercase_tokens,
        allowed_dates=allowed_dates,
        allowed_numbers=allowed_numbers,
    )


def _validate_capability(value: str) -> str:
    if not isinstance(value, str):
        raise GroundedPacketTokenError("Grounded explanation capability is invalid.")
    normalized = value.strip()
    if not _CAPABILITY_RE.fullmatch(normalized):
        raise GroundedPacketTokenError("Grounded explanation capability is invalid.")
    return normalized


def _bounded_text(value: Any, *, field: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise GroundedPacketTokenError(f"Grounded explanation {field} must be text.")
    normalized = " ".join(value.split())
    if not normalized or len(normalized) > maximum:
        raise GroundedPacketTokenError(f"Grounded explanation {field} is invalid.")
    if any(ord(character) < 32 for character in normalized):
        raise GroundedPacketTokenError(f"Grounded explanation {field} is invalid.")
    return normalized


def _string_list(
    value: Any,
    *,
    field: str,
    maximum_items: int,
    item_maximum: int,
) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > maximum_items:
        raise GroundedPacketTokenError(f"Grounded explanation {field} are invalid.")

    result: list[str] = []
    for item in value:
        normalized = _bounded_text(item, field=field, maximum=item_maximum)
        if normalized in result:
            continue
        result.append(normalized)
    return tuple(result)
