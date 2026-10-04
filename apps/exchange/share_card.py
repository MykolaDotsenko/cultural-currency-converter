from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from django.core import signing
from django.utils import timezone

from apps.exchange.result_summary import SmartResultSummary, SmartResultSummaryKind
from apps.exchange.trusted_snapshot import (
    TrustedConversionSnapshot,
    TrustedSnapshotTokenError,
    build_trusted_conversion_snapshot_token,
    load_trusted_conversion_snapshot_token,
)

_SHARE_CARD_SALT = "exchange.share-card:v1"
SHARE_CARD_MAX_AGE_SECONDS = 30 * 24 * 60 * 60
_MAX_TOKEN_LENGTH = 12_288
_MAX_COUNTRY_NAME_LENGTH = 120
_MAX_SUMMARY_TEXT_LENGTH = 1_000
_MAX_EVIDENCE_LABEL_LENGTH = 320


class ShareCardTokenError(ValueError):
    """Raised when a public share-card snapshot cannot be trusted."""


@dataclass(frozen=True, slots=True)
class ShareCardSnapshot:
    conversion: TrustedConversionSnapshot
    source_country_code: str
    source_country_name: str
    destination_country_code: str
    destination_country_name: str
    source_minor_units: int
    destination_minor_units: int
    summary_kind: SmartResultSummaryKind
    summary_text: str
    summary_evidence_label: str
    created_at: datetime


def build_share_card_token(
    *,
    conversion_result,
    source_country_code: str = "",
    source_country_name: str = "",
    destination_country_code: str = "",
    destination_country_name: str = "",
    source_minor_units: int,
    destination_minor_units: int,
    summary: SmartResultSummary,
) -> str:
    source_code = _country_code(source_country_code)
    destination_code = _country_code(destination_country_code)
    source_name = _bounded_text(
        source_country_name,
        label="Source country name",
        maximum=_MAX_COUNTRY_NAME_LENGTH,
        allow_empty=True,
    )
    destination_name = _bounded_text(
        destination_country_name,
        label="Destination country name",
        maximum=_MAX_COUNTRY_NAME_LENGTH,
        allow_empty=True,
    )
    source_units = _minor_units(source_minor_units)
    destination_units = _minor_units(destination_minor_units)
    if not isinstance(summary, SmartResultSummary):
        raise ShareCardTokenError("Share-card summary must be a trusted deterministic summary.")
    summary_text = _bounded_text(
        summary.text,
        label="Summary text",
        maximum=_MAX_SUMMARY_TEXT_LENGTH,
        allow_empty=False,
    )
    evidence_label = _bounded_text(
        summary.evidence_label,
        label="Summary evidence",
        maximum=_MAX_EVIDENCE_LABEL_LENGTH,
        allow_empty=True,
    )

    payload = {
        "v": 1,
        "conversion_token": build_trusted_conversion_snapshot_token(conversion_result),
        "source_country_code": source_code,
        "source_country_name": source_name,
        "destination_country_code": destination_code,
        "destination_country_name": destination_name,
        "source_minor_units": source_units,
        "destination_minor_units": destination_units,
        "summary_kind": summary.kind.value,
        "summary_text": summary_text,
        "summary_evidence_label": evidence_label,
        "created_at": timezone.now().isoformat(),
    }
    return signing.dumps(payload, salt=_SHARE_CARD_SALT, compress=True)


def load_share_card_token(
    token: str,
    *,
    max_age: int = SHARE_CARD_MAX_AGE_SECONDS,
) -> ShareCardSnapshot:
    if not isinstance(token, str) or not token or len(token) > _MAX_TOKEN_LENGTH:
        raise ShareCardTokenError("Share card is missing or invalid.")

    try:
        payload = signing.loads(token, salt=_SHARE_CARD_SALT, max_age=max_age)
    except signing.SignatureExpired as exc:
        raise ShareCardTokenError("Share card has expired.") from exc
    except signing.BadSignature as exc:
        raise ShareCardTokenError("Share card is invalid.") from exc

    if not isinstance(payload, dict) or payload.get("v") != 1:
        raise ShareCardTokenError("Share card version is unsupported.")

    try:
        conversion_token = payload["conversion_token"]
        source_country_code = _country_code(payload["source_country_code"])
        source_country_name = _bounded_text(
            payload["source_country_name"],
            label="Source country name",
            maximum=_MAX_COUNTRY_NAME_LENGTH,
            allow_empty=True,
        )
        destination_country_code = _country_code(payload["destination_country_code"])
        destination_country_name = _bounded_text(
            payload["destination_country_name"],
            label="Destination country name",
            maximum=_MAX_COUNTRY_NAME_LENGTH,
            allow_empty=True,
        )
        source_minor_units = _minor_units(payload["source_minor_units"])
        destination_minor_units = _minor_units(payload["destination_minor_units"])
        summary_kind = SmartResultSummaryKind(payload["summary_kind"])
        summary_text = _bounded_text(
            payload["summary_text"],
            label="Summary text",
            maximum=_MAX_SUMMARY_TEXT_LENGTH,
            allow_empty=False,
        )
        summary_evidence_label = _bounded_text(
            payload["summary_evidence_label"],
            label="Summary evidence",
            maximum=_MAX_EVIDENCE_LABEL_LENGTH,
            allow_empty=True,
        )
        created_at = datetime.fromisoformat(payload["created_at"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ShareCardTokenError("Share card payload is invalid.") from exc

    if created_at.tzinfo is None:
        raise ShareCardTokenError("Share card timestamp must be timezone-aware.")

    try:
        conversion = load_trusted_conversion_snapshot_token(
            conversion_token,
            max_age=max_age,
        )
    except TrustedSnapshotTokenError as exc:
        raise ShareCardTokenError("Share card conversion snapshot is invalid.") from exc

    return ShareCardSnapshot(
        conversion=conversion,
        source_country_code=source_country_code,
        source_country_name=source_country_name,
        destination_country_code=destination_country_code,
        destination_country_name=destination_country_name,
        source_minor_units=source_minor_units,
        destination_minor_units=destination_minor_units,
        summary_kind=summary_kind,
        summary_text=summary_text,
        summary_evidence_label=summary_evidence_label,
        created_at=created_at,
    )


def share_card_component(snapshot: ShareCardSnapshot) -> dict[str, object]:
    conversion = snapshot.conversion
    same_currency = conversion.base_currency == conversion.quote_currency

    if conversion.historical:
        status = "Historical exact 1:1" if same_currency else "Historical reference"
        trust_note = (
            "This is an exact historical identity conversion. It does not describe historical "
            "purchasing power."
            if same_currency
            else (
                "This is a historical FX reference observation, not a measure of historical "
                "purchasing power."
            )
        )
    elif same_currency:
        status = "Exact 1:1"
        trust_note = (
            "Both sides use the same currency, so this snapshot required no exchange-rate lookup."
        )
    elif conversion.stale:
        status = "Cached reference"
        trust_note = (
            "Fresh provider data was unavailable when this snapshot was created, so the card "
            "preserves a labelled cached reference observation."
        )
    else:
        status = "Reference rate"
        trust_note = (
            "This is a reference conversion snapshot, not an executable bank, card or merchant quote."
        )

    providers = (
        "No provider lookup"
        if same_currency
        else (
            ", ".join(key.upper() for key in conversion.provider_keys)
            or "Provider attribution unavailable"
        )
    )

    return {
        "input_amount": _money_text(conversion.input_amount, snapshot.source_minor_units),
        "input_currency": conversion.base_currency,
        "output_amount": _money_text(
            conversion.output_amount,
            snapshot.destination_minor_units,
        ),
        "output_currency": conversion.quote_currency,
        "rate": _decimal_text(conversion.rate),
        "rate_line": f"1 {conversion.base_currency} = {_decimal_text(conversion.rate)} {conversion.quote_currency}",
        "same_currency": same_currency,
        "historical": conversion.historical,
        "stale": conversion.stale,
        "status": status,
        "trust_note": trust_note,
        "requested_date": conversion.requested_date,
        "effective_date": conversion.effective_date,
        "providers": providers,
        "source_country_code": snapshot.source_country_code,
        "source_country_name": snapshot.source_country_name,
        "destination_country_code": snapshot.destination_country_code,
        "destination_country_name": snapshot.destination_country_name,
        "summary_kind": snapshot.summary_kind.value,
        "summary_text": snapshot.summary_text,
        "summary_evidence_label": snapshot.summary_evidence_label,
        "created_at": snapshot.created_at,
    }


def _country_code(value: Any) -> str:
    if not isinstance(value, str):
        raise ShareCardTokenError("Share-card country code must be text.")
    code = value.upper().strip()
    if code and (len(code) != 2 or not code.isascii() or not code.isalpha()):
        raise ShareCardTokenError("Share-card country code must be two ASCII letters.")
    return code


def _bounded_text(
    value: Any,
    *,
    label: str,
    maximum: int,
    allow_empty: bool,
) -> str:
    if not isinstance(value, str):
        raise ShareCardTokenError(f"{label} must be text.")
    text = " ".join(value.split())
    if not text and not allow_empty:
        raise ShareCardTokenError(f"{label} cannot be empty.")
    if len(text) > maximum:
        raise ShareCardTokenError(f"{label} exceeds the supported length.")
    return text


def _minor_units(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 6:
        raise ShareCardTokenError("Share-card currency precision is invalid.")
    return value


def _money_text(value: Decimal, minor_units: int) -> str:
    return f"{value:.{minor_units}f}"


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"
