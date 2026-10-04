from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from django.core import signing

from apps.exchange.domain import (
    ConversionResult,
    FxSourcePolicy,
    ProviderPolicyMode,
    RateQuote,
)
from apps.exchange.shopping import ShoppingAssumptions
from apps.exchange.trusted_snapshot import (
    TOKEN_MAX_AGE_SECONDS,
    TrustedSnapshotTokenError,
    build_trusted_conversion_snapshot_token,
    load_trusted_conversion_snapshot_token,
)

_TOKEN_SALT = "exchange.shopping-context:v1"
_MAX_TOKEN_LENGTH = 8192


class ShoppingContextTokenError(ValueError):
    """Raised when a signed Shopping result cannot be trusted."""


@dataclass(frozen=True, slots=True)
class TrustedShoppingContextSnapshot:
    conversion: ConversionResult
    assumptions: ShoppingAssumptions
    purchase_country_code: str


def build_shopping_context_snapshot_token(
    *,
    conversion: ConversionResult,
    assumptions: ShoppingAssumptions,
    purchase_country_code: str = "",
) -> str:
    code = _normalize_country_code(purchase_country_code)
    _validate_semantics(conversion=conversion, assumptions=assumptions)

    quote = conversion.quote
    payload = {
        "v": 1,
        "conversion_token": build_trusted_conversion_snapshot_token(conversion),
        "fetched_at": quote.fetched_at.isoformat(),
        "provider_policy_mode": quote.provider_policy.mode.value,
        "provider_policy_key": quote.provider_policy.provider_key,
        "provider_policy_include_attribution": quote.provider_policy.include_attribution,
        "purchase_country_code": code,
        "item_price": format(assumptions.item_price, "f"),
        "shipping": format(assumptions.shipping, "f"),
        "known_fees": format(assumptions.known_fees, "f"),
        "fx_markup_percent": format(assumptions.fx_markup_percent, "f"),
    }
    return signing.dumps(payload, salt=_TOKEN_SALT, compress=True)


def load_shopping_context_snapshot_token(
    token: str,
    *,
    max_age: int = TOKEN_MAX_AGE_SECONDS,
) -> TrustedShoppingContextSnapshot:
    if not isinstance(token, str) or not token or len(token) > _MAX_TOKEN_LENGTH:
        raise ShoppingContextTokenError("Shopping context token is missing or invalid.")

    try:
        payload = signing.loads(token, salt=_TOKEN_SALT, max_age=max_age)
    except signing.SignatureExpired as exc:
        raise ShoppingContextTokenError("Shopping context token has expired.") from exc
    except signing.BadSignature as exc:
        raise ShoppingContextTokenError("Shopping context token is invalid.") from exc

    if not isinstance(payload, dict) or payload.get("v") != 1:
        raise ShoppingContextTokenError("Shopping context token version is unsupported.")

    try:
        conversion_token = payload["conversion_token"]
        fetched_at_raw = payload["fetched_at"]
        policy_mode_raw = payload["provider_policy_mode"]
        policy_key_raw = payload["provider_policy_key"]
        include_attribution = payload["provider_policy_include_attribution"]
        purchase_country_code = _normalize_country_code(payload["purchase_country_code"])
        assumptions = ShoppingAssumptions(
            item_price=_finite_decimal(payload["item_price"]),
            shipping=_finite_decimal(payload["shipping"]),
            known_fees=_finite_decimal(payload["known_fees"]),
            fx_markup_percent=_finite_decimal(payload["fx_markup_percent"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ShoppingContextTokenError("Shopping context token payload is invalid.") from exc

    if not isinstance(include_attribution, bool):
        raise ShoppingContextTokenError("Shopping context provider policy is invalid.")
    if policy_key_raw is not None and not isinstance(policy_key_raw, str):
        raise ShoppingContextTokenError("Shopping context provider policy is invalid.")

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
        raise ShoppingContextTokenError("Shopping context conversion payload is invalid.") from exc

    if fetched_at.tzinfo is None:
        raise ShoppingContextTokenError("Shopping context fetched-at value must be timezone-aware.")

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
        _validate_semantics(conversion=conversion, assumptions=assumptions)
    except ValueError as exc:
        raise ShoppingContextTokenError("Shopping context semantics are invalid.") from exc

    return TrustedShoppingContextSnapshot(
        conversion=conversion,
        assumptions=assumptions,
        purchase_country_code=purchase_country_code,
    )


def _validate_semantics(
    *,
    conversion: ConversionResult,
    assumptions: ShoppingAssumptions,
) -> None:
    if conversion.quote.historical:
        raise ShoppingContextTokenError("Shopping context requires a current conversion.")
    if conversion.quote.base_currency == conversion.quote.quote_currency:
        raise ShoppingContextTokenError("Shopping context requires two different currencies.")
    if conversion.input_amount != assumptions.purchase_total:
        raise ShoppingContextTokenError(
            "Shopping context conversion input does not match the explicit purchase total."
        )


def _normalize_country_code(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("Purchase country code must be text.")
    code = value.upper().strip()
    if code and (len(code) != 2 or not code.isascii() or not code.isalpha()):
        raise ValueError("Purchase country code must be two ASCII letters.")
    return code


def _finite_decimal(value: Any) -> Decimal:
    if not isinstance(value, str) or len(value) > 80:
        raise ShoppingContextTokenError("Shopping context numeric value is invalid.")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ShoppingContextTokenError("Shopping context numeric value is invalid.") from exc
    if not parsed.is_finite() or parsed < 0:
        raise ShoppingContextTokenError("Shopping context numeric value is invalid.")
    return parsed
