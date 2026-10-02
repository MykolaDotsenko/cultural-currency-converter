from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from django.core import signing

from apps.exchange.budget import (
    BudgetAssumptions,
    BudgetBasis,
    BudgetCategoryAssumption,
    BudgetInterpretationError,
)
from apps.exchange.trusted_snapshot import TOKEN_MAX_AGE_SECONDS

_TOKEN_SALT = "exchange.saved-comparison:v1"
_MAX_TOKEN_LENGTH = 8192
_MAX_AMOUNT = Decimal("1000000000")
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_DESTINATION_RE = re.compile(r"^[A-Z]{2}(?::[a-z0-9]+(?:-[a-z0-9]+)*)?$")


class SavedComparisonTokenError(ValueError):
    """Raised when a saved-comparison input token cannot be trusted."""


@dataclass(frozen=True, slots=True)
class SavedComparisonInput:
    source_amount: Decimal
    source_currency_code: str
    left_destination: str
    right_destination: str
    assumptions: BudgetAssumptions


def build_saved_comparison_token(
    *,
    source_amount: Decimal,
    source_currency_code: str,
    left_destination: str,
    right_destination: str,
    assumptions: BudgetAssumptions,
) -> str:
    validated = _validate_input(
        source_amount=source_amount,
        source_currency_code=source_currency_code,
        left_destination=left_destination,
        right_destination=right_destination,
        assumptions=assumptions,
    )
    payload = {
        "v": 1,
        "source_amount": format(validated.source_amount, "f"),
        "source_currency": validated.source_currency_code,
        "left_destination": validated.left_destination,
        "right_destination": validated.right_destination,
        "duration_days": validated.assumptions.duration_days,
        "travelers": validated.assumptions.travelers,
        "categories": [
            [item.category, format(item.units_per_person_per_day, "f")]
            for item in validated.assumptions.categories
        ],
    }
    return signing.dumps(payload, salt=_TOKEN_SALT, compress=True)


def load_saved_comparison_token(
    token: str,
    *,
    max_age: int = TOKEN_MAX_AGE_SECONDS,
) -> SavedComparisonInput:
    if not isinstance(token, str) or not token or len(token) > _MAX_TOKEN_LENGTH:
        raise SavedComparisonTokenError("Saved comparison token is missing or invalid.")

    try:
        payload = signing.loads(token, salt=_TOKEN_SALT, max_age=max_age)
    except signing.SignatureExpired as exc:
        raise SavedComparisonTokenError("Saved comparison token has expired.") from exc
    except signing.BadSignature as exc:
        raise SavedComparisonTokenError("Saved comparison token is invalid.") from exc

    if not isinstance(payload, dict) or payload.get("v") != 1:
        raise SavedComparisonTokenError("Saved comparison token version is unsupported.")

    try:
        source_amount = Decimal(str(payload["source_amount"]))
        source_currency = str(payload["source_currency"])
        left_destination = str(payload["left_destination"])
        right_destination = str(payload["right_destination"])
        duration_days = payload["duration_days"]
        travelers = payload["travelers"]
        raw_categories = payload["categories"]
    except (KeyError, TypeError, InvalidOperation) as exc:
        raise SavedComparisonTokenError("Saved comparison token payload is invalid.") from exc

    if not isinstance(raw_categories, list):
        raise SavedComparisonTokenError("Saved comparison categories are invalid.")

    categories: list[BudgetCategoryAssumption] = []
    try:
        for item in raw_categories:
            if not isinstance(item, list) or len(item) != 2:
                raise ValueError
            category, raw_units = item
            categories.append(
                BudgetCategoryAssumption(
                    category=str(category),
                    units_per_person_per_day=Decimal(str(raw_units)),
                )
            )
        assumptions = BudgetAssumptions(
            duration_days=duration_days,
            travelers=travelers,
            categories=tuple(categories),
            basis=BudgetBasis.REFERENCE_CONVERSION,
        )
    except (BudgetInterpretationError, InvalidOperation, TypeError, ValueError) as exc:
        raise SavedComparisonTokenError("Saved comparison assumptions are invalid.") from exc

    try:
        return _validate_input(
            source_amount=source_amount,
            source_currency_code=source_currency,
            left_destination=left_destination,
            right_destination=right_destination,
            assumptions=assumptions,
        )
    except (BudgetInterpretationError, ValueError) as exc:
        raise SavedComparisonTokenError("Saved comparison semantics are invalid.") from exc


def _validate_input(
    *,
    source_amount: Decimal,
    source_currency_code: str,
    left_destination: str,
    right_destination: str,
    assumptions: BudgetAssumptions,
) -> SavedComparisonInput:
    if not isinstance(source_amount, Decimal) or not source_amount.is_finite():
        raise ValueError("Saved comparison amount must be a finite Decimal.")
    if not Decimal("0") <= source_amount <= _MAX_AMOUNT:
        raise ValueError("Saved comparison amount is outside the supported range.")

    source_currency = source_currency_code.strip().upper()
    if not _CURRENCY_RE.fullmatch(source_currency):
        raise ValueError("Saved comparison source currency is invalid.")

    left = left_destination.strip()
    right = right_destination.strip()
    if not _DESTINATION_RE.fullmatch(left) or not _DESTINATION_RE.fullmatch(right):
        raise ValueError("Saved comparison destination identity is invalid.")
    if left == right:
        raise ValueError("Saved comparison destinations must be different scopes.")
    if assumptions.basis is not BudgetBasis.REFERENCE_CONVERSION:
        raise BudgetInterpretationError(
            "Saved comparison requires the reference-conversion budget basis."
        )

    return SavedComparisonInput(
        source_amount=source_amount,
        source_currency_code=source_currency,
        left_destination=left,
        right_destination=right,
        assumptions=assumptions,
    )
