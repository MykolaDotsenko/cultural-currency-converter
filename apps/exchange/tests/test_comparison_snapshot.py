from __future__ import annotations

from decimal import Decimal

import pytest

from apps.exchange.budget import (
    BudgetAssumptions,
    BudgetBasis,
    BudgetCategoryAssumption,
    BudgetInterpretationError,
)
from apps.exchange.comparison_snapshot import (
    SavedComparisonTokenError,
    build_saved_comparison_token,
    load_saved_comparison_token,
)


def _assumptions() -> BudgetAssumptions:
    return BudgetAssumptions(
        duration_days=5,
        travelers=2,
        categories=(
            BudgetCategoryAssumption(
                category="coffee",
                units_per_person_per_day=Decimal("1"),
            ),
            BudgetCategoryAssumption(
                category="casual_meal",
                units_per_person_per_day=Decimal("2"),
            ),
            BudgetCategoryAssumption(
                category="transit",
                units_per_person_per_day=Decimal("2.5"),
            ),
        ),
        basis=BudgetBasis.REFERENCE_CONVERSION,
    )


def test_saved_comparison_token_round_trips_only_canonical_inputs():
    token = build_saved_comparison_token(
        source_amount=Decimal("500.00"),
        source_currency_code="eur",
        left_destination="JP:tokyo",
        right_destination="NO",
        assumptions=_assumptions(),
    )

    snapshot = load_saved_comparison_token(token)

    assert snapshot.source_amount == Decimal("500.00")
    assert snapshot.source_currency_code == "EUR"
    assert snapshot.left_destination == "JP:tokyo"
    assert snapshot.right_destination == "NO"
    assert snapshot.assumptions.duration_days == 5
    assert snapshot.assumptions.travelers == 2
    assert [
        (item.category, item.units_per_person_per_day)
        for item in snapshot.assumptions.categories
    ] == [
        ("coffee", Decimal("1")),
        ("casual_meal", Decimal("2")),
        ("transit", Decimal("2.5")),
    ]


def test_saved_comparison_token_rejects_tampering():
    token = build_saved_comparison_token(
        source_amount=Decimal("500"),
        source_currency_code="EUR",
        left_destination="JP:tokyo",
        right_destination="NO",
        assumptions=_assumptions(),
    )

    with pytest.raises(SavedComparisonTokenError, match="invalid"):
        load_saved_comparison_token(f"{token[:-1]}x")


def test_saved_comparison_token_rejects_same_scope():
    with pytest.raises(ValueError, match="different scopes"):
        build_saved_comparison_token(
            source_amount=Decimal("500"),
            source_currency_code="EUR",
            left_destination="JP:tokyo",
            right_destination="JP:tokyo",
            assumptions=_assumptions(),
        )


def test_saved_comparison_token_rejects_non_reference_budget_basis():
    assumptions = BudgetAssumptions(
        duration_days=5,
        travelers=2,
        categories=_assumptions().categories,
        basis=BudgetBasis.PAYMENT_ESTIMATE,
    )

    with pytest.raises(BudgetInterpretationError, match="reference-conversion"):
        build_saved_comparison_token(
            source_amount=Decimal("500"),
            source_currency_code="EUR",
            left_destination="JP:tokyo",
            right_destination="NO",
            assumptions=assumptions,
        )
