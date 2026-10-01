from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Mapping, Protocol

from django.core import signing

from apps.exchange.domain import FxDomainError, normalize_currency_code
from integrations.gemini.errors import AIProviderError
from integrations.gemini.models import ProviderUsage

_MAX_CAMERA_AMOUNT = Decimal("1000000000")
_NORMALIZED_AMOUNT_PATTERN = re.compile(r"^\d+(?:\.\d{1,6})?$")
_CAMERA_TOKEN_SALT = "cultural-currency.camera-extraction.v1"
CAMERA_TOKEN_MAX_AGE_SECONDS = 10 * 60


class CameraExtractionValidationError(ValueError):
    pass


class CameraExtractionState(StrEnum):
    CANDIDATE = "candidate"
    AMBIGUOUS = "ambiguous"
    NO_PRICE = "no_price"
    UNAVAILABLE = "unavailable"


class CameraConfidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class CameraAmountKind(StrEnum):
    TOTAL = "total"
    ITEM = "item"
    ATM = "atm"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class CameraCandidate:
    amount: Decimal
    currency_code: str
    confidence: CameraConfidence
    kind: CameraAmountKind

    def __post_init__(self) -> None:
        if not self.amount.is_finite() or self.amount <= 0 or self.amount > _MAX_CAMERA_AMOUNT:
            raise CameraExtractionValidationError("Camera amount is outside the supported range.")
        try:
            currency_code = normalize_currency_code(self.currency_code)
        except FxDomainError as exc:
            raise CameraExtractionValidationError("Camera currency code is invalid.") from exc
        object.__setattr__(self, "currency_code", currency_code)


@dataclass(frozen=True, slots=True)
class CameraExtraction:
    state: CameraExtractionState
    candidate: CameraCandidate | None
    provider_model: str = ""
    response_id: str | None = None
    usage: ProviderUsage = ProviderUsage()

    def __post_init__(self) -> None:
        if self.state is CameraExtractionState.CANDIDATE and self.candidate is None:
            raise CameraExtractionValidationError("Candidate state requires a candidate.")
        if self.state is not CameraExtractionState.CANDIDATE and self.candidate is not None:
            raise CameraExtractionValidationError("Non-candidate state cannot carry a candidate.")


class CameraExtractor(Protocol):
    def extract(self, *, image_bytes: bytes, mime_type: str) -> CameraExtraction: ...


@dataclass(frozen=True, slots=True)
class CameraConfirmationSnapshot:
    amount: Decimal
    currency_code: str
    confidence: CameraConfidence
    kind: CameraAmountKind

    @classmethod
    def from_candidate(cls, candidate: CameraCandidate) -> CameraConfirmationSnapshot:
        return cls(
            amount=candidate.amount,
            currency_code=candidate.currency_code,
            confidence=candidate.confidence,
            kind=candidate.kind,
        )


def normalize_camera_payload(
    payload: Mapping[str, object],
    *,
    provider_model: str = "",
    response_id: str | None = None,
    usage: ProviderUsage | None = None,
) -> CameraExtraction:
    state_raw = payload.get("status")
    if not isinstance(state_raw, str):
        raise CameraExtractionValidationError("Camera extraction status is missing.")
    try:
        state = CameraExtractionState(state_raw)
    except ValueError as exc:
        raise CameraExtractionValidationError("Camera extraction status is invalid.") from exc

    if state is not CameraExtractionState.CANDIDATE:
        return CameraExtraction(
            state=state,
            candidate=None,
            provider_model=provider_model,
            response_id=response_id,
            usage=usage or ProviderUsage(),
        )

    raw_amount = payload.get("amount")
    raw_currency = payload.get("currency_code")
    raw_confidence = payload.get("confidence")
    raw_kind = payload.get("kind")

    if not isinstance(raw_amount, str) or not _NORMALIZED_AMOUNT_PATTERN.fullmatch(raw_amount):
        raise CameraExtractionValidationError(
            "Camera amount must be a normalized decimal string without grouping separators."
        )
    try:
        amount = Decimal(raw_amount)
    except InvalidOperation as exc:
        raise CameraExtractionValidationError("Camera amount is not a valid Decimal.") from exc

    if not isinstance(raw_currency, str):
        raise CameraExtractionValidationError("Camera currency code is missing.")
    if not isinstance(raw_confidence, str):
        raise CameraExtractionValidationError("Camera confidence is missing.")
    if not isinstance(raw_kind, str):
        raise CameraExtractionValidationError("Camera amount kind is missing.")

    try:
        confidence = CameraConfidence(raw_confidence)
        kind = CameraAmountKind(raw_kind)
    except ValueError as exc:
        raise CameraExtractionValidationError("Camera extraction enum value is invalid.") from exc

    return CameraExtraction(
        state=state,
        candidate=CameraCandidate(
            amount=amount,
            currency_code=raw_currency,
            confidence=confidence,
            kind=kind,
        ),
        provider_model=provider_model,
        response_id=response_id,
        usage=usage or ProviderUsage(),
    )


def dump_camera_candidate(candidate: CameraCandidate) -> str:
    snapshot = CameraConfirmationSnapshot.from_candidate(candidate)
    return signing.dumps(
        {
            "amount": format(snapshot.amount, "f"),
            "currency_code": snapshot.currency_code,
            "confidence": snapshot.confidence.value,
            "kind": snapshot.kind.value,
        },
        salt=_CAMERA_TOKEN_SALT,
        compress=True,
    )


def load_camera_candidate(
    token: str,
    *,
    max_age_seconds: int = CAMERA_TOKEN_MAX_AGE_SECONDS,
) -> CameraConfirmationSnapshot:
    try:
        payload = signing.loads(
            token,
            salt=_CAMERA_TOKEN_SALT,
            max_age=max_age_seconds,
        )
    except signing.BadSignature as exc:
        raise CameraExtractionValidationError(
            "Camera extraction confirmation has expired or is invalid."
        ) from exc

    if not isinstance(payload, dict):
        raise CameraExtractionValidationError("Camera extraction confirmation is invalid.")

    extraction = normalize_camera_payload(
        {
            "status": CameraExtractionState.CANDIDATE.value,
            "amount": payload.get("amount"),
            "currency_code": payload.get("currency_code"),
            "confidence": payload.get("confidence"),
            "kind": payload.get("kind"),
        }
    )
    if extraction.candidate is None:
        raise CameraExtractionValidationError("Camera extraction confirmation is invalid.")
    return CameraConfirmationSnapshot.from_candidate(extraction.candidate)


def unavailable_camera_extraction() -> CameraExtraction:
    return CameraExtraction(
        state=CameraExtractionState.UNAVAILABLE,
        candidate=None,
    )


def safely_extract_camera_candidate(
    extractor: CameraExtractor | None,
    *,
    image_bytes: bytes,
    mime_type: str,
) -> CameraExtraction:
    if extractor is None:
        return unavailable_camera_extraction()
    try:
        return extractor.extract(image_bytes=image_bytes, mime_type=mime_type)
    except (AIProviderError, CameraExtractionValidationError):
        return unavailable_camera_extraction()
