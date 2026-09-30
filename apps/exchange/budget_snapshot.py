from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from django.core import signing
from django.utils import timezone

from apps.exchange.domain import (
    ConversionResult,
    FxSourcePolicy,
    ProviderPolicyMode,
    RateQuote,
)
from apps.exchange.money_context import MoneyContext
from apps.exchange.trusted_snapshot import (
    TOKEN_MAX_AGE_SECONDS,
    TrustedSnapshotTokenError,
    build_trusted_conversion_snapshot_token,
    load_trusted_conversion_snapshot_token,
)

_TOKEN_SALT = "exchange.budget-context:v1"
_MAX_TOKEN_LENGTH = 8192


class BudgetContextTokenError(ValueError):
    """Raised when a signed budget-context token cannot be trusted."""


@dataclass(frozen=True, slots=True)
class TrustedBudgetContextSnapshot:
    conversion: ConversionResult
    destination_country_code: str
    destination_city_slug: str
    as_of: date


def build_budget_context_snapshot_token(context: MoneyContext) -> str:
    if context.conversion.quote.historical:
        raise BudgetContextTokenError(
            "Budget context tokens are defined for current conversions only."
        )

    quote = context.conversion.quote
    payload = {
        "v": 1,
        "conversion_token": build_trusted_conversion_snapshot_token(context.conversion),
        "fetched_at": quote.fetched_at.isoformat(),
        "provider_policy_mode": quote.provider_policy.mode.value,
        "provider_policy_key": quote.provider_policy.provider_key,
        "provider_policy_include_attribution": quote.provider_policy.include_attribution,
        "destination_country_code": context.destination_country_code,
        "destination_city_slug": context.destination_city_slug,
        "as_of": context.as_of.isoformat(),
    }
    return signing.dumps(payload, salt=_TOKEN_SALT, compress=True)


def load_budget_context_snapshot_token(
    token: str,
    *,
    max_age: int = TOKEN_MAX_AGE_SECONDS,
) -> TrustedBudgetContextSnapshot:
    if not isinstance(token, str) or not token or len(token) > _MAX_TOKEN_LENGTH:
        raise BudgetContextTokenError("Budget context token is missing or invalid.")

    try:
        payload = signing.loads(token, salt=_TOKEN_SALT, max_age=max_age)
    except signing.SignatureExpired as exc:
        raise BudgetContextTokenError("Budget context token has expired.") from exc
    except signing.BadSignature as exc:
        raise BudgetContextTokenError("Budget context token is invalid.") from exc

    if not isinstance(payload, dict) or payload.get("v") != 1:
        raise BudgetContextTokenError("Budget context token version is unsupported.")

    try:
        conversion_token = payload["conversion_token"]
        fetched_at_raw = payload["fetched_at"]
        policy_mode_raw = payload["provider_policy_mode"]
        policy_key_raw = payload["provider_policy_key"]
        include_attribution = payload["provider_policy_include_attribution"]
        country_code = _normalize_country_code(payload["destination_country_code"])
        city_slug = _normalize_city_slug(payload["destination_city_slug"])
        as_of = date.fromisoformat(payload["as_of"])
    except (KeyError, TypeError, ValueError) as exc:
        raise BudgetContextTokenError("Budget context token payload is invalid.") from exc

    if city_slug and not country_code:
        raise BudgetContextTokenError("Budget context city requires a destination country.")
    if as_of > timezone.localdate():
        raise BudgetContextTokenError("Budget context date cannot be in the future.")
    if not isinstance(include_attribution, bool):
        raise BudgetContextTokenError("Budget context provider policy is invalid.")
    if policy_key_raw is not None and not isinstance(policy_key_raw, str):
        raise BudgetContextTokenError("Budget context provider policy is invalid.")

    try:
        conversion_snapshot = load_trusted_conversion_snapshot_token(
            conversion_token,
            max_age=max_age,
        )
        fetched_at = datetime.fromisoformat(fetched_at_raw)
        policy_mode = ProviderPolicyMode(policy_mode_raw)
        provider_policy = FxSourcePolicy(
            mode=policy_mode,
            provider_key=policy_key_raw,
            include_attribution=include_attribution,
        )
    except (TrustedSnapshotTokenError, TypeError, ValueError) as exc:
        raise BudgetContextTokenError("Budget context conversion payload is invalid.") from exc

    if fetched_at.tzinfo is None:
        raise BudgetContextTokenError("Budget context fetched-at value must be timezone-aware.")
    if conversion_snapshot.historical:
        raise BudgetContextTokenError(
            "Budget context tokens are defined for current conversions only."
        )

    try:
        quote = RateQuote(
            base_currency=conversion_snapshot.base_currency,
            quote_currency=conversion_snapshot.quote_currency,
            rate=conversion_snapshot.rate,
            requested_date=conversion_snapshot.requested_date,
            effective_date=conversion_snapshot.effective_date,
            fetched_at=fetched_at,
            provider_policy=provider_policy,
            provider_keys=conversion_snapshot.provider_keys,
            historical=conversion_snapshot.historical,
            observation_granularity=conversion_snapshot.observation_granularity,
        )
        conversion = ConversionResult(
            input_amount=conversion_snapshot.input_amount,
            output_amount=conversion_snapshot.output_amount,
            quote=quote,
            stale=conversion_snapshot.stale,
        )
    except ValueError as exc:
        raise BudgetContextTokenError("Budget context conversion semantics are invalid.") from exc

    return TrustedBudgetContextSnapshot(
        conversion=conversion,
        destination_country_code=country_code,
        destination_city_slug=city_slug,
        as_of=as_of,
    )


def _normalize_country_code(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("Destination country code must be text.")
    code = value.upper().strip()
    if code and (len(code) != 2 or not code.isascii() or not code.isalpha()):
        raise ValueError("Destination country code must be two ASCII letters.")
    return code


def _normalize_city_slug(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("Destination city slug must be text.")
    slug = value.strip().lower()
    if len(slug) > 140:
        raise ValueError("Destination city slug is too long.")
    if slug and any(character.isspace() for character in slug):
        raise ValueError("Destination city slug must be canonical.")
    return slug
