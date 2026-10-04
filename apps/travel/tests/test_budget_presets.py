from __future__ import annotations

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from apps.exchange.budget import BudgetAssumptions, BudgetBasis, BudgetCategoryAssumption
from apps.travel.budget_presets import (
    BudgetAssumptionPresetError,
    assumptions_from_budget_preset,
    budget_preset_for_user,
    budget_presets_for_user,
    delete_budget_preset,
    upsert_budget_preset,
)
from apps.travel.models import BudgetAssumptionPreset

User = get_user_model()


def _assumptions(
    *,
    duration_days: int = 5,
    travelers: int = 2,
    categories: tuple[BudgetCategoryAssumption, ...] | None = None,
    basis: BudgetBasis = BudgetBasis.REFERENCE_CONVERSION,
) -> BudgetAssumptions:
    return BudgetAssumptions(
        duration_days=duration_days,
        travelers=travelers,
        categories=categories
        or (
            BudgetCategoryAssumption(
                category="coffee",
                units_per_person_per_day=Decimal("1"),
            ),
            BudgetCategoryAssumption(
                category="casual_meal",
                units_per_person_per_day=Decimal("2"),
            ),
        ),
        basis=basis,
    )


@pytest.mark.django_db
def test_budget_preset_is_owner_scoped_input_only_and_updates_same_name():
    owner = User.objects.create_user(username="budget-preset-owner", password="StrongPass-482!")
    other = User.objects.create_user(username="budget-preset-other", password="StrongPass-482!")

    first = upsert_budget_preset(
        owner,
        name="  Weekend   city trip ",
        assumptions=_assumptions(),
    )
    updated = upsert_budget_preset(
        owner,
        name="Weekend city trip",
        assumptions=_assumptions(
            duration_days=3,
            travelers=1,
            categories=(
                BudgetCategoryAssumption(
                    category="coffee",
                    units_per_person_per_day=Decimal("1.5"),
                ),
                BudgetCategoryAssumption(
                    category="transit",
                    units_per_person_per_day=Decimal("4"),
                ),
            ),
            basis=BudgetBasis.PAYMENT_ESTIMATE,
        ),
    )

    assert updated.pk == first.pk
    assert updated.name == "Weekend city trip"
    assert updated.duration_days == 3
    assert updated.travelers == 1
    assert list(updated.items.values_list("category", "units_per_person_per_day")) == [
        ("coffee", Decimal("1.50")),
        ("transit", Decimal("4.00")),
    ]
    assert budget_presets_for_user(owner) == (updated,)
    assert budget_presets_for_user(other) == ()
    assert not hasattr(updated, "destination")
    assert not hasattr(updated, "rate")
    assert not hasattr(updated, "basis")


@pytest.mark.django_db
def test_budget_preset_lookup_and_delete_are_owner_scoped():
    owner = User.objects.create_user(username="preset-owner", password="StrongPass-482!")
    other = User.objects.create_user(username="preset-other", password="StrongPass-482!")
    preset = upsert_budget_preset(owner, name="City break", assumptions=_assumptions())

    assert budget_preset_for_user(owner, preset_id=preset.pk).pk == preset.pk
    with pytest.raises(BudgetAssumptionPresetError, match="no longer available"):
        budget_preset_for_user(other, preset_id=preset.pk)

    assert delete_budget_preset(other, preset_id=preset.pk) is False
    assert delete_budget_preset(owner, preset_id=preset.pk) is True
    assert delete_budget_preset(owner, preset_id=preset.pk) is False


@pytest.mark.django_db
def test_budget_preset_limit_allows_update_but_rejects_thirteenth_name():
    user = User.objects.create_user(username="preset-limit", password="StrongPass-482!")

    for index in range(12):
        upsert_budget_preset(
            user,
            name=f"Preset {index}",
            assumptions=_assumptions(duration_days=index + 1),
        )

    with pytest.raises(BudgetAssumptionPresetError, match="at most 12"):
        upsert_budget_preset(
            user,
            name="Preset 12",
            assumptions=_assumptions(),
        )

    updated = upsert_budget_preset(
        user,
        name="Preset 0",
        assumptions=_assumptions(duration_days=30),
    )
    assert updated.duration_days == 30
    assert BudgetAssumptionPreset.objects.filter(user=user).count() == 12


@pytest.mark.django_db
def test_budget_preset_requires_authentication():
    class Anonymous:
        is_authenticated = False

    with pytest.raises(BudgetAssumptionPresetError, match="Authentication"):
        upsert_budget_preset(
            Anonymous(),
            name="Anonymous",
            assumptions=_assumptions(),
        )


@pytest.mark.django_db
def test_budget_preset_application_uses_current_basis_and_only_available_categories():
    user = User.objects.create_user(username="preset-apply", password="StrongPass-482!")
    preset = upsert_budget_preset(
        user,
        name="Mixed basket",
        assumptions=_assumptions(
            duration_days=4,
            travelers=3,
            categories=(
                BudgetCategoryAssumption(
                    category="coffee",
                    units_per_person_per_day=Decimal("1.25"),
                ),
                BudgetCategoryAssumption(
                    category="transit",
                    units_per_person_per_day=Decimal("2.50"),
                ),
            ),
            basis=BudgetBasis.REFERENCE_CONVERSION,
        ),
    )

    application = assumptions_from_budget_preset(
        user,
        preset_id=preset.pk,
        available_categories={"coffee", "casual_meal"},
        basis=BudgetBasis.PAYMENT_ESTIMATE,
    )

    assert application.name == "Mixed basket"
    assert application.assumptions.duration_days == 4
    assert application.assumptions.travelers == 3
    assert application.assumptions.basis is BudgetBasis.PAYMENT_ESTIMATE
    assert application.assumptions.categories == (
        BudgetCategoryAssumption(
            category="coffee",
            units_per_person_per_day=Decimal("1.25"),
        ),
    )
    assert application.skipped_categories == ("transit",)


@pytest.mark.django_db
def test_budget_preset_application_rejects_destination_without_category_overlap():
    user = User.objects.create_user(username="preset-no-overlap-service", password="StrongPass-482!")
    preset = upsert_budget_preset(
        user,
        name="Transit only",
        assumptions=_assumptions(
            categories=(
                BudgetCategoryAssumption(
                    category="transit",
                    units_per_person_per_day=Decimal("2"),
                ),
            ),
        ),
    )

    with pytest.raises(BudgetAssumptionPresetError, match="None of this preset"):
        assumptions_from_budget_preset(
            user,
            preset_id=preset.pk,
            available_categories={"coffee"},
            basis=BudgetBasis.REFERENCE_CONVERSION,
        )


@pytest.mark.django_db
def test_budget_preset_rejects_unsupported_category_and_excess_precision():
    user = User.objects.create_user(username="preset-invalid", password="StrongPass-482!")

    with pytest.raises(BudgetAssumptionPresetError, match="unsupported category"):
        upsert_budget_preset(
            user,
            name="Unsupported",
            assumptions=_assumptions(
                categories=(
                    BudgetCategoryAssumption(
                        category="hotel",
                        units_per_person_per_day=Decimal("1"),
                    ),
                )
            ),
        )

    with pytest.raises(BudgetAssumptionPresetError, match="decimal places"):
        upsert_budget_preset(
            user,
            name="Too precise",
            assumptions=_assumptions(
                categories=(
                    BudgetCategoryAssumption(
                        category="coffee",
                        units_per_person_per_day=Decimal("1.001"),
                    ),
                )
            ),
        )

    assert BudgetAssumptionPreset.objects.filter(user=user).count() == 0


@pytest.mark.django_db
def test_budget_preset_listing_filters_to_current_categories():
    user = User.objects.create_user(username="preset-filter", password="StrongPass-482!")
    coffee = upsert_budget_preset(
        user,
        name="Coffee plan",
        assumptions=_assumptions(
            categories=(
                BudgetCategoryAssumption(
                    category="coffee",
                    units_per_person_per_day=Decimal("1"),
                ),
            ),
        ),
    )
    upsert_budget_preset(
        user,
        name="Transit plan",
        assumptions=_assumptions(
            categories=(
                BudgetCategoryAssumption(
                    category="transit",
                    units_per_person_per_day=Decimal("2"),
                ),
            ),
        ),
    )

    from apps.travel.budget_presets import budget_presets_for_categories

    assert budget_presets_for_categories(
        user,
        available_categories={"coffee", "casual_meal"},
    ) == (coffee,)
