from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from django.core import signing

from apps.exchange.camera import CameraContextKind, CameraExtractionCandidate
from apps.exchange.domain import normalize_currency_code

_TOKEN_SALT = "exchange.camera-extraction:v1"
CAMERA_TOKEN_MAX_AGE_SECONDS = 15 * 60


class CameraExtractionTokenError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CameraExtractionSnapshot:
    amount: Decimal
    currency_code: str
    confidence: Decimal
    context_kind: CameraContextKind
    provider_model: str
    response_id: str | None


def create_camera_extraction_token(candidate: CameraExtractionCandidate) -> str:
    if not candidate.found or candidate.amount is None or candidate.currency_code is None:
        raise CameraExtractionTokenError("Only a found camera candidate can be signed.")
    return signing.dumps(
        {
            "amount": format(candidate.amount, "f"),
            "currency_code": candidate.currency_code,
            "confidence": format(candidate.confidence, "f"),
            "context_kind": candidate.context_kind.value,
            "provider_model": candidate.provider_model[:120],
            "response_id": (candidate.response_id or "")[:160],
        },
        salt=_TOKEN_SALT,
        compress=True,
    )


def load_camera_extraction_token(token: str) -> CameraExtractionSnapshot:
    try:
        payload = signing.loads(
            token,
            salt=_TOKEN_SALT,
            max_age=CAMERA_TOKEN_MAX_AGE_SECONDS,
        )
    except signing.BadSignature as exc:
        raise CameraExtractionTokenError("Camera extraction token is invalid or expired.") from exc
    if not isinstance(payload, dict):
        raise CameraExtractionTokenError("Camera extraction token payload is invalid.")

    try:
        amount = Decimal(str(payload["amount"]))
        confidence = Decimal(str(payload["confidence"]))
        currency_code = normalize_currency_code(str(payload["currency_code"]))
        context_kind = CameraContextKind(str(payload["context_kind"]))
    except (KeyError, InvalidOperation, ValueError) as exc:
        raise CameraExtractionTokenError("Camera extraction token payload is invalid.") from exc

    if amount <= 0 or not Decimal("0") <= confidence <= Decimal("1"):
        raise CameraExtractionTokenError("Camera extraction token payload is invalid.")

    provider_model = str(payload.get("provider_model") or "").strip()[:120] or "unknown"
    response_id = str(payload.get("response_id") or "").strip()[:160] or None
    return CameraExtractionSnapshot(
        amount=amount,
        currency_code=currency_code,
        confidence=confidence,
        context_kind=context_kind,
        provider_model=provider_model,
        response_id=response_id,
    )
