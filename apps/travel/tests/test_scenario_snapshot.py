from __future__ import annotations

from decimal import Decimal

import pytest

from apps.exchange.budget import BudgetAssumptions, BudgetBasis, BudgetCategoryAssumption
from apps.travel.scenario_snapshot import (
    SavedScenarioDraftTokenError,
    build_saved_scenario_draft_token,
    load_saved_scenario_draft_token,
)


def _assumptions(*, basis: BudgetBasis = BudgetBasis.REFERENCE_CONVERSION) -> BudgetAssumptions:
    return BudgetAssumptions(
        duration_days=5,
        travelers=2,
        categories=(
            BudgetCategoryAssumption(
                category="coffee",
                units_per_person_per_day=Decimal("1.5"),
            ),
            BudgetCategoryAssumption(
                category="casual_meal",
                units_per_person_per_day=Decimal("2"),
            ),
        ),
        basis=basis,
    )


def test_saved_scenario_draft_round_trips_exact_assumptions():
    token = build_saved_scenario_draft_token(
        budget_context_token="signed-budget-context",
        assumptions=_assumptions(),
    )

    draft = load_saved_scenario_draft_token(token)

    assert draft.budget_context_token == "signed-budget-context"
    assert draft.assumptions.duration_days == 5
    assert draft.assumptions.travelers == 2
    assert draft.assumptions.categories[0].category == "coffee"
    assert draft.assumptions.categories[0].units_per_person_per_day == Decimal("1.5")


def test_saved_scenario_draft_rejects_tampering():
    token = build_saved_scenario_draft_token(
        budget_context_token="signed-budget-context",
        assumptions=_assumptions(),
    )

    with pytest.raises(SavedScenarioDraftTokenError, match="invalid"):
        load_saved_scenario_draft_token(f"{token}tampered")


def test_saved_scenario_draft_rejects_non_reference_budget_basis():
    with pytest.raises(SavedScenarioDraftTokenError, match="reference-conversion"):
        build_saved_scenario_draft_token(
            budget_context_token="signed-budget-context",
            assumptions=_assumptions(basis=BudgetBasis.PAYMENT_ESTIMATE),
        )
