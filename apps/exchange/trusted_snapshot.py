from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from django.core import signing

from apps.exchange.domain import ConversionResult, ObservationGranularity, normalize_currency_code

# Keep the original runtime-explanation salt so snapshots created before this
# boundary was generalized remain valid for their normal short lifetime.
_TOKEN_SALT = "exchange.runtime-explanation:v1"
TOKEN_MAX_AGE_SECONDS = 24 * 60 * 60
MAX_TRUSTED_PROVIDER_KEYS = 64
MAX_TRUSTED_PROVIDER_KEY_LENGTH = 40
MAX_PROVIDER_KEYS = 128
MAX_PROVIDER_KEY_LENGTH = 80


class TrustedSnapshotTokenError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class TrustedConversionSnapshot:
    input_amount: Decimal
    output_amount: Decimal
    base_currency: str
    quote_currency: str
    rate: Decimal
    requested_date: date | None
    effective_date: date
    historical: bool
    observation_granularity: ObservationGranularity
    provider_keys: tuple[str, ...]
    stale: bool


def build_trusted_conversion_snapshot_token(result: ConversionResult) -> str:
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
        "historical": result.quote.historical,
        "observation_granularity": result.quote.observation_granularity.value,
        "provider_keys": list(result.quote.provider_keys),
        "stale": result.stale,
    }
    return signing.dumps(payload, salt=_TOKEN_SALT, compress=True)


def load_trusted_conversion_snapshot_token(
    token: str,
    *,
    max_age: int = TOKEN_MAX_AGE_SECONDS,
) -> TrustedConversionSnapshot:
    if not isinstance(token, str) or not token or len(token) > 4096:
        raise TrustedSnapshotTokenError("Conversion snapshot token is missing or invalid.")
    try:
        payload = signing.loads(token, salt=_TOKEN_SALT, max_age=max_age)
    except signing.SignatureExpired as exc:
        raise TrustedSnapshotTokenError("Conversion snapshot token has expired.") from exc
    except signing.BadSignature as exc:
        raise TrustedSnapshotTokenError("Conversion snapshot token is invalid.") from exc

    if not isinstance(payload, dict) or payload.get("v") != 1:
        raise TrustedSnapshotTokenError("Conversion snapshot token version is unsupported.")

    try:
        input_amount = _finite_decimal(payload["input_amount"], minimum=Decimal("0"))
        output_amount = _finite_decimal(payload["output_amount"], minimum=Decimal("0"))
        rate = _finite_decimal(payload["rate"], minimum=Decimal("0"), strict_positive=True)
        base_currency = normalize_currency_code(payload["base_currency"])
        quote_currency = normalize_currency_code(payload["quote_currency"])
        effective_date = date.fromisoformat(payload["effective_date"])
        requested_raw = payload.get("requested_date")
        requested_date = date.fromisoformat(requested_raw) if requested_raw else None
        historical = payload["historical"]
        stale = payload["stale"]
        granularity = ObservationGranularity(payload["observation_granularity"])
        raw_provider_keys = payload["provider_keys"]
    except (KeyError, TypeError, ValueError) as exc:
        raise TrustedSnapshotTokenError("Conversion snapshot token payload is invalid.") from exc

    if not isinstance(historical, bool) or not isinstance(stale, bool):
        raise TrustedSnapshotTokenError("Conversion snapshot token flags are invalid.")
    if historical != (requested_date is not None):
        raise TrustedSnapshotTokenError(
            "Conversion snapshot token historical semantics are invalid."
        )
    if requested_date is not None and effective_date > requested_date:
        raise TrustedSnapshotTokenError("Conversion snapshot token observation date is invalid.")
    if not isinstance(raw_provider_keys, list) or len(raw_provider_keys) > MAX_PROVIDER_KEYS:
        raise TrustedSnapshotTokenError(
            "Conversion snapshot token provider attribution is invalid."
        )

    provider_keys: list[str] = []
    for value in raw_provider_keys:
        if not isinstance(value, str):
            raise TrustedSnapshotTokenError(
                "Conversion snapshot token provider attribution is invalid."
            )
        normalized = value.strip().lower()
        if not normalized or len(normalized) > MAX_PROVIDER_KEY_LENGTH:
            raise TrustedSnapshotTokenError(
                "Conversion snapshot token provider attribution is invalid."
            )
        if normalized not in provider_keys:
            provider_keys.append(normalized)

    return TrustedConversionSnapshot(
        input_amount=input_amount,
        output_amount=output_amount,
        base_currency=base_currency,
        quote_currency=quote_currency,
        rate=rate,
        requested_date=requested_date,
        effective_date=effective_date,
        historical=historical,
        observation_granularity=granularity,
        provider_keys=tuple(sorted(provider_keys)),
        stale=stale,
    )


def _finite_decimal(
    value: Any,
    *,
    minimum: Decimal,
    strict_positive: bool = False,
) -> Decimal:
    if not isinstance(value, str) or len(value) > 80:
        raise TrustedSnapshotTokenError("Conversion snapshot numeric value is invalid.")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise TrustedSnapshotTokenError("Conversion snapshot numeric value is invalid.") from exc
    if not parsed.is_finite():
        raise TrustedSnapshotTokenError("Conversion snapshot numeric value is invalid.")
    if strict_positive and parsed <= minimum:
        raise TrustedSnapshotTokenError("Conversion snapshot numeric value must be positive.")
    if not strict_positive and parsed < minimum:
        raise TrustedSnapshotTokenError("Conversion snapshot numeric value is out of range.")
    return parsed
