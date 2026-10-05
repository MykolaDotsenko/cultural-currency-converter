from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from django.core import signing

from apps.exchange.domain import (
    ConversionResult,
    FxDomainError,
    ObservationGranularity,
    normalize_currency_code,
    normalize_provider_keys,
)

_TOKEN_SALT = "exchange.share-conversion:v1"
_MAX_TOKEN_LENGTH = 8192


class ConversionShareTokenError(ValueError):
    """Raised when a public-by-link conversion snapshot cannot be trusted."""


@dataclass(frozen=True, slots=True)
class ConversionShareSnapshot:
    input_amount: Decimal
    output_amount: Decimal
    base_currency: str
    quote_currency: str
    rate: Decimal
    requested_date: date | None
    effective_date: date
    fetched_at: datetime
    historical: bool
    observation_granularity: ObservationGranularity
    provider_keys: tuple[str, ...]
    stale: bool

    @property
    def exact(self) -> bool:
        return self.base_currency == self.quote_currency


def build_conversion_share_token(result: ConversionResult) -> str:
    """Sign the already-computed conversion truth for an explicit share surface."""

    payload = {
        "v": 1,
        "input_amount": format(result.input_amount, "f"),
        "output_amount": format(result.output_amount, "f"),
        "base_currency": result.quote.base_currency,
        "quote_currency": result.quote.quote_currency,
        "rate": format(result.quote.rate, "f"),
        "requested_date": (
            result.quote.requested_date.isoformat()
            if result.quote.requested_date is not None
            else None
        ),
        "effective_date": result.quote.effective_date.isoformat(),
        "fetched_at": result.quote.fetched_at.isoformat(),
        "historical": result.quote.historical,
        "observation_granularity": result.quote.observation_granularity.value,
        "provider_keys": list(result.quote.provider_keys),
        "stale": result.stale,
    }
    return signing.dumps(payload, salt=_TOKEN_SALT, compress=True)


def load_conversion_share_token(token: str) -> ConversionShareSnapshot:
    """Load a durable immutable share token.

    Share links intentionally do not expire on a short runtime-token clock.
    Their numeric state is immutable and always rendered with effective/source
    metadata so an old share cannot masquerade as a current executable rate.
    """

    if not isinstance(token, str) or not token or len(token) > _MAX_TOKEN_LENGTH:
        raise ConversionShareTokenError("Conversion share token is missing or invalid.")

    try:
        payload = signing.loads(token, salt=_TOKEN_SALT)
    except signing.BadSignature as exc:
        raise ConversionShareTokenError("Conversion share token is invalid.") from exc

    if not isinstance(payload, dict) or payload.get("v") != 1:
        raise ConversionShareTokenError("Conversion share token version is unsupported.")

    expected_fields = {
        "v",
        "input_amount",
        "output_amount",
        "base_currency",
        "quote_currency",
        "rate",
        "requested_date",
        "effective_date",
        "fetched_at",
        "historical",
        "observation_granularity",
        "provider_keys",
        "stale",
    }
    if set(payload) != expected_fields:
        raise ConversionShareTokenError("Conversion share token fields are invalid.")

    try:
        input_amount = _finite_decimal(payload["input_amount"], minimum=Decimal("0"))
        output_amount = _finite_decimal(payload["output_amount"], minimum=Decimal("0"))
        rate = _finite_decimal(
            payload["rate"],
            minimum=Decimal("0"),
            strict_positive=True,
        )
        base_currency = normalize_currency_code(payload["base_currency"])
        quote_currency = normalize_currency_code(payload["quote_currency"])
        effective_date = date.fromisoformat(payload["effective_date"])
        requested_raw = payload["requested_date"]
        requested_date = date.fromisoformat(requested_raw) if requested_raw else None
        fetched_at = datetime.fromisoformat(payload["fetched_at"])
        historical = payload["historical"]
        stale = payload["stale"]
        granularity = ObservationGranularity(payload["observation_granularity"])
        raw_provider_keys = payload["provider_keys"]
    except (KeyError, TypeError, ValueError) as exc:
        raise ConversionShareTokenError("Conversion share token payload is invalid.") from exc

    if fetched_at.tzinfo is None or fetched_at.utcoffset() is None:
        raise ConversionShareTokenError("Conversion share token fetch time is invalid.")
    if not isinstance(historical, bool) or not isinstance(stale, bool):
        raise ConversionShareTokenError("Conversion share token flags are invalid.")
    if historical != (requested_date is not None):
        raise ConversionShareTokenError("Conversion share token historical semantics are invalid.")
    if requested_date is not None and effective_date > requested_date:
        raise ConversionShareTokenError("Conversion share token observation date is invalid.")
    if not isinstance(raw_provider_keys, list):
        raise ConversionShareTokenError("Conversion share provider attribution is invalid.")

    try:
        provider_keys = normalize_provider_keys(raw_provider_keys)
    except FxDomainError as exc:
        raise ConversionShareTokenError(
            "Conversion share provider attribution is invalid."
        ) from exc

    exact = base_currency == quote_currency
    if exact and rate != Decimal("1"):
        raise ConversionShareTokenError("Exact share snapshot must use a 1:1 rate.")
    if exact and provider_keys:
        raise ConversionShareTokenError(
            "Exact share snapshot must not claim an external provider."
        )
    if not exact and not provider_keys:
        raise ConversionShareTokenError(
            "Conversion share snapshot must retain provider attribution."
        )

    return ConversionShareSnapshot(
        input_amount=input_amount,
        output_amount=output_amount,
        base_currency=base_currency,
        quote_currency=quote_currency,
        rate=rate,
        requested_date=requested_date,
        effective_date=effective_date,
        fetched_at=fetched_at,
        historical=historical,
        observation_granularity=granularity,
        provider_keys=provider_keys,
        stale=stale,
    )


def _finite_decimal(
    value: Any,
    *,
    minimum: Decimal,
    strict_positive: bool = False,
) -> Decimal:
    if not isinstance(value, str) or len(value) > 80:
        raise ConversionShareTokenError("Conversion share numeric value is invalid.")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ConversionShareTokenError("Conversion share numeric value is invalid.") from exc
    if not parsed.is_finite():
        raise ConversionShareTokenError("Conversion share numeric value is invalid.")
    if strict_positive and parsed <= minimum:
        raise ConversionShareTokenError("Conversion share numeric value must be positive.")
    if not strict_positive and parsed < minimum:
        raise ConversionShareTokenError("Conversion share numeric value is out of range.")
    return parsed
