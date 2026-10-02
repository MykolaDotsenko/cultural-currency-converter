from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

from django.core import signing
from django.utils import timezone

from apps.culture.services import DestinationContext
from apps.exchange.ai.contracts import (
    ExplanationInsight,
    ExplanationPacket,
    ExplanationResult,
)
from apps.exchange.ai.service import ExplanationDelivery

_TOKEN_SALT = "culture.explore-context-ai:v1"
_TOKEN_MAX_AGE_SECONDS = 6 * 60 * 60
_MAX_TOKEN_LENGTH = 16_384
_UPPERCASE_TOKEN_RE = re.compile(r"\b[A-Z]{3}\b")


class ExploreAIIntent(StrEnum):
    LOCAL_MONEY = "local_money"
    PAYMENTS = "payments"
    TRUST = "trust"


class ExploreAITokenError(ValueError):
    pass


class ExploreAIIntentError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ExploreAIPriceFact:
    label: str
    scope_label: str
    amount_low: Decimal
    amount_high: Decimal | None
    currency_code: str
    observed_at: date


@dataclass(frozen=True, slots=True)
class TrustedExploreContextSnapshot:
    country_code: str
    country_name: str
    city_slug: str
    city_name: str
    currency_code: str
    as_of: date
    prices: tuple[ExploreAIPriceFact, ...]
    payment_summary: str
    payment_customs: str
    cash_usage: str
    atm_notes: str
    dcc_warning: str
    payment_verified_at: date | None

    @property
    def scope_label(self) -> str:
        return (
            f"{self.city_name}, {self.country_name}"
            if self.city_name
            else self.country_name
        )


@dataclass(frozen=True, slots=True)
class ExploreAIIntentSpec:
    intent: ExploreAIIntent
    label: str
    question: str
    focus_instruction: str
    required_fact_ids: tuple[str, ...]


def build_explore_ai_snapshot_token(
    context: DestinationContext,
    *,
    currency_code: str,
) -> str:
    payment = context.payment
    payload = {
        "v": 1,
        "country_code": context.country_code,
        "country_name": context.country_name,
        "city_slug": context.city_slug,
        "city_name": context.city_name,
        "currency_code": currency_code,
        "as_of": context.as_of.isoformat(),
        "prices": [
            {
                "label": price.label,
                "scope_label": price.scope_label,
                "amount_low": format(price.amount_low, "f"),
                "amount_high": (
                    format(price.amount_high, "f")
                    if price.amount_high is not None
                    else None
                ),
                "currency_code": price.currency_code,
                "observed_at": price.observed_at.isoformat(),
            }
            for price in context.prices[:4]
        ],
        "payment": (
            {
                "summary": payment.summary,
                "payment_customs": payment.payment_customs,
                "cash_usage": payment.cash_usage,
                "atm_notes": payment.atm_notes,
                "dcc_warning": payment.dcc_warning,
                "verified_at": payment.verified_at.date().isoformat(),
            }
            if payment is not None
            else None
        ),
    }
    return signing.dumps(payload, salt=_TOKEN_SALT, compress=True)


def load_explore_ai_snapshot_token(
    token: str,
    *,
    max_age: int = _TOKEN_MAX_AGE_SECONDS,
) -> TrustedExploreContextSnapshot:
    if not isinstance(token, str) or not token or len(token) > _MAX_TOKEN_LENGTH:
        raise ExploreAITokenError("Explore context token is missing or invalid.")
    try:
        payload = signing.loads(token, salt=_TOKEN_SALT, max_age=max_age)
    except signing.SignatureExpired as exc:
        raise ExploreAITokenError("Explore context token has expired.") from exc
    except signing.BadSignature as exc:
        raise ExploreAITokenError("Explore context token is invalid.") from exc

    if not isinstance(payload, dict) or payload.get("v") != 1:
        raise ExploreAITokenError("Explore context token version is unsupported.")

    try:
        country_code = _country_code(payload["country_code"])
        country_name = _bounded_text(payload["country_name"], maximum=120)
        city_slug = _bounded_text(payload.get("city_slug", ""), maximum=140).lower()
        city_name = _bounded_text(payload.get("city_name", ""), maximum=160)
        currency_code = _currency_code(payload["currency_code"])
        as_of = date.fromisoformat(payload["as_of"])
        raw_prices = payload.get("prices", [])
        raw_payment = payload.get("payment")
    except (KeyError, TypeError, ValueError) as exc:
        raise ExploreAITokenError("Explore context token payload is invalid.") from exc

    if as_of > timezone.localdate():
        raise ExploreAITokenError("Explore context date cannot be in the future.")
    if city_slug and not city_name:
        raise ExploreAITokenError("Explore city scope is incomplete.")
    if not isinstance(raw_prices, list) or len(raw_prices) > 4:
        raise ExploreAITokenError("Explore price context is invalid.")

    prices: list[ExploreAIPriceFact] = []
    for raw in raw_prices:
        if not isinstance(raw, dict):
            raise ExploreAITokenError("Explore price context is invalid.")
        try:
            low = _positive_decimal(raw["amount_low"])
            high = (
                _positive_decimal(raw["amount_high"])
                if raw.get("amount_high") is not None
                else None
            )
            observed_at = date.fromisoformat(raw["observed_at"])
            price_currency = _currency_code(raw["currency_code"])
            label = _bounded_text(raw["label"], maximum=160)
            scope_label = _bounded_text(raw["scope_label"], maximum=200)
        except (KeyError, TypeError, ValueError) as exc:
            raise ExploreAITokenError("Explore price context is invalid.") from exc
        if high is not None and high < low:
            raise ExploreAITokenError("Explore price range is invalid.")
        if price_currency != currency_code or observed_at > as_of:
            raise ExploreAITokenError("Explore price scope is inconsistent.")
        prices.append(
            ExploreAIPriceFact(
                label=label,
                scope_label=scope_label,
                amount_low=low,
                amount_high=high,
                currency_code=price_currency,
                observed_at=observed_at,
            )
        )

    payment_summary = payment_customs = cash_usage = atm_notes = dcc_warning = ""
    payment_verified_at = None
    if raw_payment is not None:
        if not isinstance(raw_payment, dict):
            raise ExploreAITokenError("Explore payment context is invalid.")
        try:
            payment_summary = _bounded_text(raw_payment.get("summary", ""), maximum=800)
            payment_customs = _bounded_text(
                raw_payment.get("payment_customs", ""),
                maximum=1200,
            )
            cash_usage = _bounded_text(raw_payment.get("cash_usage", ""), maximum=1200)
            atm_notes = _bounded_text(raw_payment.get("atm_notes", ""), maximum=1200)
            dcc_warning = _bounded_text(raw_payment.get("dcc_warning", ""), maximum=1200)
            payment_verified_at = date.fromisoformat(raw_payment["verified_at"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ExploreAITokenError("Explore payment context is invalid.") from exc
        if payment_verified_at > as_of:
            raise ExploreAITokenError("Explore payment context date is inconsistent.")

    return TrustedExploreContextSnapshot(
        country_code=country_code,
        country_name=country_name,
        city_slug=city_slug,
        city_name=city_name,
        currency_code=currency_code,
        as_of=as_of,
        prices=tuple(prices),
        payment_summary=payment_summary,
        payment_customs=payment_customs,
        cash_usage=cash_usage,
        atm_notes=atm_notes,
        dcc_warning=dcc_warning,
        payment_verified_at=payment_verified_at,
    )


def available_explore_ai_intents(
    snapshot: TrustedExploreContextSnapshot,
) -> tuple[ExploreAIIntentSpec, ...]:
    specs: list[ExploreAIIntentSpec] = []
    if snapshot.prices:
        specs.append(
            ExploreAIIntentSpec(
                intent=ExploreAIIntent.LOCAL_MONEY,
                label="Everyday money",
                question=f"What should I know about everyday money in {snapshot.scope_label}?",
                focus_instruction=(
                    "Summarize only the supplied reviewed price anchors and their scope. "
                    "Do not infer affordability, purchasing power or a cost-of-living ranking."
                ),
                required_fact_ids=("price_1",),
            )
        )
    payment_fact = _first_payment_fact_id(snapshot)
    if payment_fact:
        specs.append(
            ExploreAIIntentSpec(
                intent=ExploreAIIntent.PAYMENTS,
                label="Paying here",
                question=f"What should I know about paying in {snapshot.country_name}?",
                focus_instruction=(
                    "Summarize only the supplied reviewed payment facts. "
                    "Do not infer merchant acceptance or fees that are not supplied."
                ),
                required_fact_ids=(payment_fact,),
            )
        )
    specs.append(
        ExploreAIIntentSpec(
            intent=ExploreAIIntent.TRUST,
            label="Sources & freshness",
            question="How current and scoped is this destination context?",
            focus_instruction=(
                "Explain the supplied city/country scope and evidence dates. "
                "Do not claim broader coverage than the supplied facts."
            ),
            required_fact_ids=("scope", "evidence_scope"),
        )
    )
    return tuple(specs)


def parse_explore_ai_intent(
    value: str | None,
    *,
    snapshot: TrustedExploreContextSnapshot,
) -> ExploreAIIntentSpec:
    try:
        intent = ExploreAIIntent((value or "").strip())
    except ValueError as exc:
        raise ExploreAIIntentError("Unknown Explore explanation question.") from exc

    available = {
        spec.intent: spec for spec in available_explore_ai_intents(snapshot)
    }
    spec = available.get(intent)
    if spec is None:
        raise ExploreAIIntentError(
            "Explore explanation question is not available for this context."
        )
    return spec


def build_explore_ai_packet(
    snapshot: TrustedExploreContextSnapshot,
    *,
    spec: ExploreAIIntentSpec,
    locale: str = "en",
) -> ExplanationPacket:
    facts: list[tuple[str, str]] = [
        (
            "scope",
            f"Reviewed destination context is scoped to {snapshot.scope_label}.",
        ),
        (
            "currency",
            f"The current local currency code is {snapshot.currency_code}.",
        ),
        (
            "evidence_scope",
            (
                "Only reviewed facts supplied by the application may be explained; "
                "missing destination facts must not be inferred."
            ),
        ),
    ]

    allowed_dates: set[str] = {snapshot.as_of.isoformat()}
    allowed_numbers: set[str] = set()
    for index, price in enumerate(snapshot.prices, start=1):
        price_id = f"price_{index}"
        low = format(price.amount_low, "f")
        allowed_numbers.add(low)
        if price.amount_high is not None and price.amount_high != price.amount_low:
            high = format(price.amount_high, "f")
            allowed_numbers.add(high)
            amount_text = f"{low}–{high} {price.currency_code}"
        else:
            amount_text = f"{low} {price.currency_code}"
        observed = price.observed_at.isoformat()
        allowed_dates.add(observed)
        facts.append(
            (
                price_id,
                (
                    f"{price.label} is a reviewed {price.scope_label} price anchor of "
                    f"{amount_text}, observed {observed}."
                ),
            )
        )

    payment_pairs = (
        ("payment_summary", snapshot.payment_summary),
        ("payment_customs", snapshot.payment_customs),
        ("cash_usage", snapshot.cash_usage),
        ("atm_notes", snapshot.atm_notes),
        ("dcc_warning", snapshot.dcc_warning),
    )
    for fact_id, value in payment_pairs:
        if value.strip():
            facts.append((fact_id, value.strip()))

    if snapshot.payment_verified_at is not None:
        verified = snapshot.payment_verified_at.isoformat()
        allowed_dates.add(verified)
        facts.append(
            (
                "payment_verified",
                f"The reviewed payment context was verified on {verified}.",
            )
        )

    fact_statements = tuple(statement for _fact_id, statement in facts)
    uppercase_tokens = {
        token
        for statement in fact_statements
        for token in _UPPERCASE_TOKEN_RE.findall(statement)
        if token != snapshot.currency_code
    }

    from apps.exchange.ai.contracts import GroundedFact

    return ExplanationPacket(
        packet_version="explore-context:v1",
        locale=locale,
        intent_id=spec.intent.value,
        intent_question=spec.question,
        focus_instruction=spec.focus_instruction,
        required_fact_ids=spec.required_fact_ids,
        facts=tuple(GroundedFact(id=fact_id, statement=statement) for fact_id, statement in facts),
        allowed_currencies=(snapshot.currency_code,),
        allowed_uppercase_tokens=tuple(sorted(uppercase_tokens)),
        allowed_dates=tuple(sorted(allowed_dates)),
        allowed_numbers=tuple(sorted(allowed_numbers)),
    )


def build_explore_ai_fallback_delivery(
    snapshot: TrustedExploreContextSnapshot,
    *,
    spec: ExploreAIIntentSpec,
    packet: ExplanationPacket,
    reason: str,
) -> ExplanationDelivery:
    facts = {fact.id: fact for fact in packet.facts}

    if spec.intent is ExploreAIIntent.LOCAL_MONEY:
        primary = facts["price_1"]
        factors = tuple(
            ExplanationInsight(text=facts[f"price_{index}"].statement, supporting_fact_ids=(f"price_{index}",))
            for index in range(2, min(len(snapshot.prices), 3) + 1)
            if f"price_{index}" in facts
        ) or (
            ExplanationInsight(
                text=facts["currency"].statement,
                supporting_fact_ids=("currency",),
            ),
        )
    elif spec.intent is ExploreAIIntent.PAYMENTS:
        primary_id = _first_payment_fact_id(snapshot) or "evidence_scope"
        primary = facts[primary_id]
        factor_ids = [
            fact_id
            for fact_id in ("payment_customs", "cash_usage", "atm_notes", "dcc_warning")
            if fact_id in facts and fact_id != primary_id
        ][:3]
        factors = tuple(
            ExplanationInsight(text=facts[fact_id].statement, supporting_fact_ids=(fact_id,))
            for fact_id in factor_ids
        ) or (
            ExplanationInsight(
                text=facts["scope"].statement,
                supporting_fact_ids=("scope",),
            ),
        )
    else:
        primary = facts["evidence_scope"]
        factors_list = [
            ExplanationInsight(
                text=facts["scope"].statement,
                supporting_fact_ids=("scope",),
            )
        ]
        if "payment_verified" in facts:
            factors_list.append(
                ExplanationInsight(
                    text=facts["payment_verified"].statement,
                    supporting_fact_ids=("payment_verified",),
                )
            )
        elif snapshot.prices:
            factors_list.append(
                ExplanationInsight(
                    text=facts["price_1"].statement,
                    supporting_fact_ids=("price_1",),
                )
            )
        factors = tuple(factors_list)

    return ExplanationDelivery(
        result=ExplanationResult(
            short_answer=ExplanationInsight(
                text=primary.statement,
                supporting_fact_ids=(primary.id,),
            ),
            key_factors=factors,
            watch_out_for=ExplanationInsight(
                text=facts["evidence_scope"].statement,
                supporting_fact_ids=("evidence_scope",),
            ),
            next_step=ExplanationInsight(
                text="Use the reviewed destination context alongside the canonical converter, budget or comparison flow.",
                supporting_fact_ids=("scope",),
            ),
            generated=False,
            source_label="Built-in Explore explanation",
            fallback_reason=reason,
        ),
        cache_status="deterministic_fallback",
        packet_hash=packet.packet_hash,
    )


def _first_payment_fact_id(snapshot: TrustedExploreContextSnapshot) -> str:
    for fact_id, value in (
        ("payment_summary", snapshot.payment_summary),
        ("payment_customs", snapshot.payment_customs),
        ("cash_usage", snapshot.cash_usage),
        ("atm_notes", snapshot.atm_notes),
        ("dcc_warning", snapshot.dcc_warning),
    ):
        if value.strip():
            return fact_id
    return ""


def _country_code(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("Country code must be text.")
    normalized = value.upper().strip()
    if len(normalized) != 2 or not normalized.isascii() or not normalized.isalpha():
        raise ValueError("Country code is invalid.")
    return normalized


def _currency_code(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("Currency code must be text.")
    normalized = value.upper().strip()
    if len(normalized) != 3 or not normalized.isascii() or not normalized.isalpha():
        raise ValueError("Currency code is invalid.")
    return normalized


def _bounded_text(value: Any, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError("Context text must be text.")
    normalized = " ".join(value.split())
    if len(normalized) > maximum:
        raise ValueError("Context text is too long.")
    return normalized


def _positive_decimal(value: Any) -> Decimal:
    if not isinstance(value, str) or len(value) > 80:
        raise ValueError("Price amount is invalid.")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Price amount is invalid.") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise ValueError("Price amount must be positive.")
    return parsed
