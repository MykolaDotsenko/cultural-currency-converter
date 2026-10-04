from __future__ import annotations

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from apps.exchange.budget import BudgetCategoryAssumption
from apps.exchange.budget_presets import (
    BudgetPresetError,
    budget_preset_for_user,
    budget_presets_for_user,
    delete_budget_preset,
    preset_post_values,
    upsert_budget_preset,
)

User = get_user_model()


def _categories(
    *,
    coffee: str = "1.00",
    meal: str = "2.00",
) -> tuple[BudgetCategoryAssumption, ...]:
    return (
        BudgetCategoryAssumption("coffee", Decimal(coffee)),
        BudgetCategoryAssumption("casual_meal", Decimal(meal)),
    )


@pytest.mark.django_db
def test_budget_preset_upsert_is_owner_scoped_and_replaces_same_name():
    owner = User.objects.create_user(username="preset-owner", password="StrongPass-482!")
    other = User.objects.create_user(username="preset-other", password="StrongPass-482!")

    first = upsert_budget_preset(
        owner,
        name="  Weekend   city  ",
        duration_days=3,
        travelers=2,
        categories=_categories(),
    )
    updated = upsert_budget_preset(
        owner,
        name="Weekend city",
        duration_days=4,
        travelers=1,
        categories=_categories(coffee="2.00", meal="1.00"),
    )

    assert updated.pk == first.pk
    assert updated.name == "Weekend city"
    assert updated.duration_days == 4
    assert updated.travelers == 1
    assert tuple(updated.items.values_list("category", "units_per_person_per_day")) == (
        ("casual_meal", Decimal("1.00")),
        ("coffee", Decimal("2.00")),
    )
    assert budget_presets_for_user(other) == ()
    assert budget_preset_for_user(owner, preset_id=updated.pk).pk == updated.pk

    with pytest.raises(BudgetPresetError, match="no longer available"):
        budget_preset_for_user(other, preset_id=updated.pk)


@pytest.mark.django_db
def test_budget_preset_post_values_are_destination_independent_form_assumptions():
    owner = User.objects.create_user(username="preset-values", password="StrongPass-482!")
    preset = upsert_budget_preset(
        owner,
        name="Solo week",
        duration_days=7,
        travelers=1,
        categories=(
            BudgetCategoryAssumption("coffee", Decimal("1.50")),
            BudgetCategoryAssumption("transit", Decimal("3.00")),
        ),
    )

    assert preset_post_values(preset) == {
        "duration_days": "7",
        "travelers": "1",
        "units_coffee": "1.5",
        "units_transit": "3",
    }


@pytest.mark.django_db
def test_budget_preset_delete_is_owner_scoped():
    owner = User.objects.create_user(username="preset-delete-owner", password="StrongPass-482!")
    other = User.objects.create_user(username="preset-delete-other", password="StrongPass-482!")
    preset = upsert_budget_preset(
        owner,
        name="Delete me",
        duration_days=2,
        travelers=1,
        categories=_categories(),
    )

    assert delete_budget_preset(other, preset_id=preset.pk) is False
    assert delete_budget_preset(owner, preset_id=preset.pk) is True
    assert delete_budget_preset(owner, preset_id=preset.pk) is False


@pytest.mark.django_db
def test_budget_preset_limit_allows_update_but_rejects_thirteenth():
    owner = User.objects.create_user(username="preset-limit", password="StrongPass-482!")
    for index in range(12):
        upsert_budget_preset(
            owner,
            name=f"Preset {index}",
            duration_days=3,
            travelers=1,
            categories=_categories(),
        )

    with pytest.raises(BudgetPresetError, match="at most 12"):
        upsert_budget_preset(
            owner,
            name="Preset 13",
            duration_days=3,
            travelers=1,
            categories=_categories(),
        )

    updated = upsert_budget_preset(
        owner,
        name="Preset 0",
        duration_days=5,
        travelers=2,
        categories=_categories(coffee="2.00"),
    )
    assert updated.duration_days == 5
    assert updated.travelers == 2


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("duration_days", "travelers", "categories", "message"),
    [
        (0, 1, _categories(), "between 1 and 365"),
        (3, 0, _categories(), "between 1 and 20"),
        (3, 1, (), "between 1 and 8"),
    ],
)
def test_budget_preset_reuses_budget_domain_validation(
    duration_days,
    travelers,
    categories,
    message,
):
    owner = User.objects.create_user(
        username=f"preset-invalid-{duration_days}-{travelers}-{len(categories)}",
        password="StrongPass-482!",
    )

    with pytest.raises(BudgetPresetError, match=message):
        upsert_budget_preset(
            owner,
            name="Invalid",
            duration_days=duration_days,
            travelers=travelers,
            categories=categories,
        )


@pytest.mark.django_db
def test_budget_preset_invalid_replacement_rolls_back_existing_child_graph():
    owner = User.objects.create_user(
        username="preset-rollback",
        password="StrongPass-482!",
    )
    preset = upsert_budget_preset(
        owner,
        name="Stable basket",
        duration_days=4,
        travelers=2,
        categories=_categories(coffee="1.50", casual_meal="2.00"),
    )
    before = tuple(preset.items.values_list("category", "units_per_person_per_day"))

    with pytest.raises(BudgetPresetError):
        upsert_budget_preset(
            owner,
            name="Stable basket",
            duration_days=7,
            travelers=1,
            categories=(
                BudgetCategoryAssumption(
                    "not_a_canonical_category",
                    Decimal("1.00"),
                ),
            ),
        )

    preset.refresh_from_db()
    assert preset.duration_days == 4
    assert preset.travelers == 2
    assert tuple(preset.items.values_list("category", "units_per_person_per_day")) == before
