from __future__ import annotations

import io
import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any, Protocol
from warnings import catch_warnings, simplefilter

from django.core import signing
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_CAMERA_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_CAMERA_PIXELS = 24_000_000
MAX_CAMERA_EDGE = 2048
MAX_CAMERA_CANDIDATES = 6
MAX_CAMERA_AMOUNT = Decimal("1000000000000")
CAMERA_CANDIDATE_TOKEN_MAX_AGE_SECONDS = 15 * 60
_CAMERA_TOKEN_SALT = "exchange.camera-candidate.v1"
_CAMERA_CONFIRMED_TOKEN_SALT = "exchange.camera-confirmed.v1"
_CURRENCY_CODE_RE = re.compile(r"^[A-Z]{3}$")


class CameraImageError(ValueError):
    pass


class CameraExtractionError(ValueError):
    pass


class CameraNoAmountFound(CameraExtractionError):
    pass


class CameraTokenError(ValueError):
    pass


class CameraCandidateKind(StrEnum):
    TOTAL = "total"
    LINE_ITEM = "line_item"
    ATM_AMOUNT = "atm_amount"
    OTHER = "other"


class CameraConfidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True, slots=True)
class SanitizedCameraImage:
    data: bytes
    mime_type: str
    width: int
    height: int

    def __post_init__(self) -> None:
        if self.mime_type != "image/jpeg":
            raise CameraImageError("Sanitized camera images must use JPEG.")
        if not self.data:
            raise CameraImageError("Sanitized camera image is empty.")
        if self.width <= 0 or self.height <= 0:
            raise CameraImageError("Sanitized camera image dimensions are invalid.")


@dataclass(frozen=True, slots=True)
class CameraAmountCandidate:
    amount: Decimal
    currency_code: str
    kind: CameraCandidateKind
    confidence: CameraConfidence

    def __post_init__(self) -> None:
        if not isinstance(self.amount, Decimal):
            raise CameraExtractionError("Camera amount must be a Decimal.")
        if not self.amount.is_finite() or self.amount <= 0 or self.amount > MAX_CAMERA_AMOUNT:
            raise CameraExtractionError("Camera amount is outside the supported range.")

        currency_code = self.currency_code.upper().strip()
        if currency_code and not _CURRENCY_CODE_RE.fullmatch(currency_code):
            raise CameraExtractionError(
                "Camera currency code must be blank or three ASCII letters."
            )
        object.__setattr__(self, "currency_code", currency_code)


@dataclass(frozen=True, slots=True)
class CameraExtraction:
    candidates: tuple[CameraAmountCandidate, ...]
    provider_model: str
    provider_response_id: str | None = None

    def __post_init__(self) -> None:
        if not self.candidates:
            raise CameraNoAmountFound("No monetary amounts were found in this image.")
        if len(self.candidates) > MAX_CAMERA_CANDIDATES:
            raise CameraExtractionError("Camera extraction returned too many amount candidates.")
        if not self.provider_model.strip():
            raise CameraExtractionError("Camera extraction provider model is missing.")


class CameraAmountExtractor(Protocol):
    def extract(
        self,
        image: SanitizedCameraImage,
        *,
        expected_currency: str,
    ) -> CameraExtraction: ...


@dataclass(frozen=True, slots=True)
class CameraCandidateSnapshot:
    scope: str
    amount: Decimal
    currency_code: str
    kind: CameraCandidateKind
    confidence: CameraConfidence

    def __post_init__(self) -> None:
        if not self.scope.strip() or len(self.scope) > 120:
            raise CameraTokenError("Camera candidate scope is invalid.")
        try:
            CameraAmountCandidate(
                amount=self.amount,
                currency_code=self.currency_code,
                kind=self.kind,
                confidence=self.confidence,
            )
        except CameraExtractionError as exc:
            raise CameraTokenError(str(exc)) from exc


def sanitize_camera_image(raw: bytes, *, content_type: str) -> SanitizedCameraImage:
    """Decode and re-encode user media in memory, stripping metadata.

    Raw uploads are never persisted by this function. All accepted input is
    normalized to a bounded RGB JPEG before it can cross an external-provider
    boundary.
    """

    if not raw:
        raise CameraImageError("Choose an image to scan.")
    if len(raw) > MAX_CAMERA_UPLOAD_BYTES:
        raise CameraImageError("Image is too large. Use an image up to 8 MiB.")

    normalized_type = content_type.split(";", 1)[0].strip().lower()
    if normalized_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise CameraImageError("Use a JPEG, PNG or WebP image.")

    try:
        with catch_warnings():
            simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as image:
                if getattr(image, "n_frames", 1) != 1:
                    raise CameraImageError("Animated or multi-frame images are not supported.")
                width, height = image.size
                if width <= 0 or height <= 0 or width * height > MAX_CAMERA_PIXELS:
                    raise CameraImageError("Image dimensions are outside the supported range.")
                image.load()
                normalized = ImageOps.exif_transpose(image)
                normalized.thumbnail((MAX_CAMERA_EDGE, MAX_CAMERA_EDGE), Image.Resampling.LANCZOS)

                if normalized.mode in {"RGBA", "LA"}:
                    background = Image.new("RGB", normalized.size, "white")
                    alpha = normalized.getchannel("A")
                    background.paste(normalized.convert("RGB"), mask=alpha)
                    normalized = background
                elif normalized.mode != "RGB":
                    normalized = normalized.convert("RGB")

                output = io.BytesIO()
                normalized.save(
                    output,
                    format="JPEG",
                    quality=92,
                    optimize=True,
                    progressive=True,
                )
                encoded = output.getvalue()
                return SanitizedCameraImage(
                    data=encoded,
                    mime_type="image/jpeg",
                    width=normalized.width,
                    height=normalized.height,
                )
    except CameraImageError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise CameraImageError("Image dimensions are outside the supported range.") from exc
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise CameraImageError("The uploaded file is not a valid supported image.") from exc


def normalize_camera_provider_payload(
    payload: Mapping[str, Any],
    *,
    provider_model: str,
    provider_response_id: str | None,
) -> CameraExtraction:
    raw_candidates = payload.get("candidates")
    if not isinstance(raw_candidates, list):
        raise CameraExtractionError("Camera extraction response is missing candidates.")
    if len(raw_candidates) > MAX_CAMERA_CANDIDATES:
        raise CameraExtractionError("Camera extraction returned too many amount candidates.")

    candidates: list[CameraAmountCandidate] = []
    for raw_candidate in raw_candidates:
        if not isinstance(raw_candidate, Mapping):
            raise CameraExtractionError("Camera extraction candidate has an invalid shape.")

        raw_amount = raw_candidate.get("amount")
        raw_currency = raw_candidate.get("currency_code", "")
        raw_kind = raw_candidate.get("kind")
        raw_confidence = raw_candidate.get("confidence")
        if not isinstance(raw_amount, str) or not isinstance(raw_currency, str):
            raise CameraExtractionError("Camera extraction candidate amount/currency is invalid.")
        if not isinstance(raw_kind, str) or not isinstance(raw_confidence, str):
            raise CameraExtractionError("Camera extraction candidate metadata is invalid.")

        try:
            amount = Decimal(raw_amount)
            kind = CameraCandidateKind(raw_kind)
            confidence = CameraConfidence(raw_confidence)
        except (InvalidOperation, ValueError) as exc:
            raise CameraExtractionError(
                "Camera extraction candidate contains invalid values."
            ) from exc

        candidates.append(
            CameraAmountCandidate(
                amount=amount,
                currency_code=raw_currency,
                kind=kind,
                confidence=confidence,
            )
        )

    return CameraExtraction(
        candidates=tuple(candidates),
        provider_model=provider_model,
        provider_response_id=provider_response_id,
    )


@dataclass(frozen=True, slots=True)
class ConfirmedCameraAmountSnapshot:
    scope: str
    amount: Decimal
    currency_code: str

    def __post_init__(self) -> None:
        if not self.scope.strip() or len(self.scope) > 120:
            raise CameraTokenError("Confirmed camera amount scope is invalid.")
        try:
            CameraAmountCandidate(
                amount=self.amount,
                currency_code=self.currency_code,
                kind=CameraCandidateKind.OTHER,
                confidence=CameraConfidence.HIGH,
            )
        except CameraExtractionError as exc:
            raise CameraTokenError(str(exc)) from exc
        if not self.currency_code:
            raise CameraTokenError("Confirmed camera amount requires a currency code.")


def make_camera_candidate_token(
    candidate: CameraAmountCandidate,
    *,
    scope: str,
) -> str:
    snapshot = CameraCandidateSnapshot(
        scope=scope,
        amount=candidate.amount,
        currency_code=candidate.currency_code,
        kind=candidate.kind,
        confidence=candidate.confidence,
    )
    return signing.dumps(
        {
            "scope": snapshot.scope,
            "amount": format(snapshot.amount, "f"),
            "currency_code": snapshot.currency_code,
            "kind": snapshot.kind.value,
            "confidence": snapshot.confidence.value,
        },
        salt=_CAMERA_TOKEN_SALT,
        compress=True,
    )


def make_confirmed_camera_amount_token(
    *,
    scope: str,
    amount: Decimal,
    currency_code: str,
) -> str:
    snapshot = ConfirmedCameraAmountSnapshot(
        scope=scope,
        amount=amount,
        currency_code=currency_code.upper().strip(),
    )
    return signing.dumps(
        {
            "scope": snapshot.scope,
            "amount": format(snapshot.amount, "f"),
            "currency_code": snapshot.currency_code,
        },
        salt=_CAMERA_CONFIRMED_TOKEN_SALT,
        compress=True,
    )


def load_confirmed_camera_amount_token(
    token: str,
    *,
    expected_scope: str,
    max_age: int = CAMERA_CANDIDATE_TOKEN_MAX_AGE_SECONDS,
) -> ConfirmedCameraAmountSnapshot:
    if not token:
        raise CameraTokenError("Confirmed camera amount token is missing.")
    try:
        payload = signing.loads(
            token,
            salt=_CAMERA_CONFIRMED_TOKEN_SALT,
            max_age=max_age,
        )
    except signing.SignatureExpired as exc:
        raise CameraTokenError(
            "Confirmed camera amount has expired. Scan the image again."
        ) from exc
    except signing.BadSignature as exc:
        raise CameraTokenError("Confirmed camera amount token is invalid.") from exc

    if not isinstance(payload, dict) or payload.get("scope") != expected_scope:
        raise CameraTokenError("Confirmed camera amount does not belong to this context.")
    try:
        amount = Decimal(str(payload["amount"]))
        currency_code = str(payload["currency_code"])
    except (KeyError, InvalidOperation) as exc:
        raise CameraTokenError("Confirmed camera amount token payload is invalid.") from exc

    return ConfirmedCameraAmountSnapshot(
        scope=expected_scope,
        amount=amount,
        currency_code=currency_code,
    )


def load_camera_candidate_token(
    token: str,
    *,
    expected_scope: str,
    max_age: int = CAMERA_CANDIDATE_TOKEN_MAX_AGE_SECONDS,
) -> CameraCandidateSnapshot:
    if not token:
        raise CameraTokenError("Camera candidate token is missing.")
    try:
        payload = signing.loads(token, salt=_CAMERA_TOKEN_SALT, max_age=max_age)
    except signing.SignatureExpired as exc:
        raise CameraTokenError("Camera candidate has expired. Scan the image again.") from exc
    except signing.BadSignature as exc:
        raise CameraTokenError("Camera candidate token is invalid.") from exc

    if not isinstance(payload, dict):
        raise CameraTokenError("Camera candidate token payload is invalid.")
    scope = payload.get("scope")
    if scope != expected_scope:
        raise CameraTokenError("Camera candidate does not belong to this context.")

    try:
        amount = Decimal(str(payload["amount"]))
        currency_code = str(payload["currency_code"])
        kind = CameraCandidateKind(str(payload["kind"]))
        confidence = CameraConfidence(str(payload["confidence"]))
    except (KeyError, InvalidOperation, ValueError) as exc:
        raise CameraTokenError("Camera candidate token payload is invalid.") from exc

    return CameraCandidateSnapshot(
        scope=expected_scope,
        amount=amount,
        currency_code=currency_code,
        kind=kind,
        confidence=confidence,
    )
