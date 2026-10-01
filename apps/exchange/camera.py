from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

from apps.exchange.domain import normalize_currency_code

MAX_CAMERA_AMOUNT = Decimal("1000000000")


class CameraContextKind(StrEnum):
    MENU = "menu"
    RECEIPT = "receipt"
    SHELF = "shelf"
    ATM = "atm"
    OTHER = "other"


class CameraExtractionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CameraExtractionCandidate:
    found: bool
    amount: Decimal | None
    currency_code: str | None
    confidence: Decimal
    context_kind: CameraContextKind
    provider_model: str
    response_id: str | None

    def __post_init__(self) -> None:
        if not Decimal("0") <= self.confidence <= Decimal("1"):
            raise CameraExtractionError("Camera extraction confidence must be between 0 and 1.")
        if self.found:
            if self.amount is None or self.currency_code is None:
                raise CameraExtractionError(
                    "A found camera price requires both amount and currency."
                )
            if self.amount <= 0 or self.amount > MAX_CAMERA_AMOUNT:
                raise CameraExtractionError("Camera extraction amount is outside supported bounds.")
        elif self.amount is not None or self.currency_code is not None:
            raise CameraExtractionError(
                "A not-found camera result cannot carry amount or currency."
            )

    @property
    def needs_confirmation(self) -> bool:
        return True


def parse_camera_provider_payload(
    payload: dict[str, Any],
    *,
    provider_model: str,
    response_id: str | None,
) -> CameraExtractionCandidate:
    found = payload.get("found")
    if not isinstance(found, bool):
        raise CameraExtractionError("Camera provider payload is missing a valid found flag.")

    context_raw = payload.get("context_kind")
    try:
        context_kind = CameraContextKind(str(context_raw))
    except ValueError as exc:
        raise CameraExtractionError("Camera provider returned an unsupported context kind.") from exc

    confidence_raw = payload.get("confidence")
    if isinstance(confidence_raw, bool):
        raise CameraExtractionError("Camera provider returned invalid confidence.")
    try:
        confidence = Decimal(str(confidence_raw))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise CameraExtractionError("Camera provider returned invalid confidence.") from exc

    amount: Decimal | None = None
    currency_code: str | None = None
    if found:
        raw_amount = payload.get("amount")
        raw_currency = payload.get("currency_code")
        if not isinstance(raw_amount, str) or not raw_amount.strip():
            raise CameraExtractionError("Camera provider returned an invalid amount.")
        try:
            amount = Decimal(raw_amount.strip())
        except InvalidOperation as exc:
            raise CameraExtractionError("Camera provider returned an invalid amount.") from exc
        if not isinstance(raw_currency, str):
            raise CameraExtractionError("Camera provider returned an invalid currency.")
        try:
            currency_code = normalize_currency_code(raw_currency)
        except ValueError as exc:
            raise CameraExtractionError("Camera provider returned an invalid currency.") from exc

    return CameraExtractionCandidate(
        found=found,
        amount=amount,
        currency_code=currency_code,
        confidence=confidence,
        context_kind=context_kind,
        provider_model=provider_model.strip() or "unknown",
        response_id=response_id,
    )
