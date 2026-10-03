from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from django.core import signing

from apps.exchange.payment_estimate import MAX_FX_MARKUP_PERCENT, PaymentEstimate
from apps.exchange.trusted_snapshot import TOKEN_MAX_AGE_SECONDS

_TOKEN_SALT = "exchange.payment-budget-handoff:v1"
_MAX_TOKEN_LENGTH = 16_384
_MAX_BUDGET_CONTEXT_TOKEN_LENGTH = 8_192
_MAX_DECIMAL_TEXT_LENGTH = 80


class PaymentBudgetHandoffTokenError(ValueError):
    """Raised when a signed Payment Estimate → Budget handoff cannot be trusted."""


@dataclass(frozen=True, slots=True)
class TrustedPaymentBudgetHandoff:
    budget_context_token: str
    fx_markup_percent: Decimal
    source_fixed_fee: Decimal
    destination_fixed_fee: Decimal


def build_payment_budget_handoff_token(
    *,
    budget_context_token: str,
    estimate: PaymentEstimate,
) -> str:
    token = _budget_context_token(budget_context_token)
    return signing.dumps(
        {
            "v": 1,
            "budget_context_token": token,
            "fx_markup_percent": format(estimate.fx_markup_percent, "f"),
            "source_fixed_fee": format(estimate.source_fixed_fee, "f"),
            "destination_fixed_fee": format(estimate.destination_fixed_fee, "f"),
        },
        salt=_TOKEN_SALT,
        compress=True,
    )


def load_payment_budget_handoff_token(
    token: str,
    *,
    max_age: int = TOKEN_MAX_AGE_SECONDS,
) -> TrustedPaymentBudgetHandoff:
    if not isinstance(token, str) or not token or len(token) > _MAX_TOKEN_LENGTH:
        raise PaymentBudgetHandoffTokenError("Payment-budget handoff token is missing or invalid.")

    try:
        payload = signing.loads(token, salt=_TOKEN_SALT, max_age=max_age)
    except signing.SignatureExpired as exc:
        raise PaymentBudgetHandoffTokenError("Payment-budget handoff token has expired.") from exc
    except signing.BadSignature as exc:
        raise PaymentBudgetHandoffTokenError("Payment-budget handoff token is invalid.") from exc

    if not isinstance(payload, dict) or payload.get("v") != 1:
        raise PaymentBudgetHandoffTokenError("Payment-budget handoff token version is unsupported.")

    expected_fields = {
        "v",
        "budget_context_token",
        "fx_markup_percent",
        "source_fixed_fee",
        "destination_fixed_fee",
    }
    if set(payload) != expected_fields:
        raise PaymentBudgetHandoffTokenError("Payment-budget handoff payload is invalid.")

    budget_context_token = _budget_context_token(payload["budget_context_token"])
    fx_markup_percent = _decimal(
        payload["fx_markup_percent"],
        field="FX markup",
        maximum=MAX_FX_MARKUP_PERCENT,
    )
    source_fixed_fee = _decimal(payload["source_fixed_fee"], field="source fixed fee")
    destination_fixed_fee = _decimal(
        payload["destination_fixed_fee"],
        field="destination fixed fee",
    )

    return TrustedPaymentBudgetHandoff(
        budget_context_token=budget_context_token,
        fx_markup_percent=fx_markup_percent,
        source_fixed_fee=source_fixed_fee,
        destination_fixed_fee=destination_fixed_fee,
    )


def _budget_context_token(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > _MAX_BUDGET_CONTEXT_TOKEN_LENGTH:
        raise PaymentBudgetHandoffTokenError("Budget context token is invalid.")
    return value


def _decimal(
    value: Any,
    *,
    field: str,
    maximum: Decimal | None = None,
) -> Decimal:
    if not isinstance(value, str) or not value or len(value) > _MAX_DECIMAL_TEXT_LENGTH:
        raise PaymentBudgetHandoffTokenError(f"Payment-budget {field} is invalid.")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise PaymentBudgetHandoffTokenError(f"Payment-budget {field} is invalid.") from exc
    if not parsed.is_finite() or parsed < 0:
        raise PaymentBudgetHandoffTokenError(f"Payment-budget {field} is invalid.")
    if maximum is not None and parsed > maximum:
        raise PaymentBudgetHandoffTokenError(f"Payment-budget {field} is out of range.")
    return parsed
