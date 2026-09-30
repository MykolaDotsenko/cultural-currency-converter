from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from django.core import signing

from apps.exchange.budget import (
    BudgetAssumptions,
    BudgetBasis,
    BudgetCategoryAssumption,
    BudgetInterpretationError,
)
from apps.exchange.trusted_snapshot import TOKEN_MAX_AGE_SECONDS

_TOKEN_SALT = "travel.saved-scenario-draft:v1"
_MAX_TOKEN_LENGTH = 24_576
_MAX_BUDGET_CONTEXT_TOKEN_LENGTH = 12_288


class SavedScenarioDraftTokenError(ValueError):
    """Raised when a signed saved-scenario draft cannot be trusted."""


@dataclass(frozen=True, slots=True)
class SavedScenarioDraft:
    budget_context_token: str
    assumptions: BudgetAssumptions


def build_saved_scenario_draft_token(
    *,
    budget_context_token: str,
    assumptions: BudgetAssumptions,
) -> str:
    if not isinstance(budget_context_token, str) or not budget_context_token:
        raise SavedScenarioDraftTokenError("Budget context token is missing or invalid.")
    if len(budget_context_token) > _MAX_BUDGET_CONTEXT_TOKEN_LENGTH:
        raise SavedScenarioDraftTokenError("Budget context token is too large.")
    if assumptions.basis is not BudgetBasis.REFERENCE_CONVERSION:
        raise SavedScenarioDraftTokenError(
            "Saved budget scenarios currently require the reference-conversion basis."
        )

    payload = {
        "v": 1,
        "budget_context_token": budget_context_token,
        "duration_days": assumptions.duration_days,
        "travelers": assumptions.travelers,
        "basis": assumptions.basis.value,
        "categories": [
            {
                "category": item.category,
                "units_per_person_per_day": format(
                    item.units_per_person_per_day,
                    "f",
                ),
            }
            for item in assumptions.categories
        ],
    }
    token = signing.dumps(payload, salt=_TOKEN_SALT, compress=True)
    if len(token) > _MAX_TOKEN_LENGTH:
        raise SavedScenarioDraftTokenError("Saved scenario draft is too large.")
    return token


def load_saved_scenario_draft_token(
    token: str,
    *,
    max_age: int = TOKEN_MAX_AGE_SECONDS,
) -> SavedScenarioDraft:
    if not isinstance(token, str) or not token or len(token) > _MAX_TOKEN_LENGTH:
        raise SavedScenarioDraftTokenError("Saved scenario draft token is missing or invalid.")

    try:
        payload = signing.loads(token, salt=_TOKEN_SALT, max_age=max_age)
    except signing.SignatureExpired as exc:
        raise SavedScenarioDraftTokenError("Saved scenario draft token has expired.") from exc
    except signing.BadSignature as exc:
        raise SavedScenarioDraftTokenError("Saved scenario draft token is invalid.") from exc

    if not isinstance(payload, dict) or payload.get("v") != 1:
        raise SavedScenarioDraftTokenError("Saved scenario draft version is unsupported.")

    try:
        budget_context_token = _text(payload["budget_context_token"])
        duration_days = _strict_int(payload["duration_days"])
        travelers = _strict_int(payload["travelers"])
        basis = BudgetBasis(payload["basis"])
        raw_categories = payload["categories"]
    except (KeyError, TypeError, ValueError) as exc:
        raise SavedScenarioDraftTokenError("Saved scenario draft payload is invalid.") from exc

    if not budget_context_token or len(budget_context_token) > _MAX_BUDGET_CONTEXT_TOKEN_LENGTH:
        raise SavedScenarioDraftTokenError("Saved scenario budget context is invalid.")
    if not isinstance(raw_categories, list):
        raise SavedScenarioDraftTokenError("Saved scenario budget categories are invalid.")

    categories: list[BudgetCategoryAssumption] = []
    try:
        for raw in raw_categories:
            if not isinstance(raw, dict) or set(raw) != {
                "category",
                "units_per_person_per_day",
            }:
                raise ValueError
            category = _text(raw["category"])
            units = _decimal(raw["units_per_person_per_day"])
            categories.append(
                BudgetCategoryAssumption(
                    category=category,
                    units_per_person_per_day=units,
                )
            )
        assumptions = BudgetAssumptions(
            duration_days=duration_days,
            travelers=travelers,
            categories=tuple(categories),
            basis=basis,
        )
    except (BudgetInterpretationError, InvalidOperation, TypeError, ValueError) as exc:
        raise SavedScenarioDraftTokenError("Saved scenario budget assumptions are invalid.") from exc

    if assumptions.basis is not BudgetBasis.REFERENCE_CONVERSION:
        raise SavedScenarioDraftTokenError(
            "Saved budget scenarios currently require the reference-conversion basis."
        )

    return SavedScenarioDraft(
        budget_context_token=budget_context_token,
        assumptions=assumptions,
    )


def _text(value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError
    return value.strip()


def _strict_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError
    return value


def _decimal(value: Any) -> Decimal:
    if not isinstance(value, str):
        raise TypeError
    decimal = Decimal(value)
    if not decimal.is_finite():
        raise ValueError
    return decimal
