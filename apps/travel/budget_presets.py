from __future__ import annotations

from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction

from apps.culture.models import TypicalPriceCategory
from apps.exchange.budget import (
    BudgetAssumptions,
    BudgetBasis,
    BudgetCategoryAssumption,
    BudgetInterpretationError,
)
from apps.travel.models import BudgetAssumptionPreset, BudgetAssumptionPresetItem

MAX_BUDGET_ASSUMPTION_PRESETS = 12


class BudgetAssumptionPresetError(ValueError):
    """Raised when reusable budget assumptions violate the preset contract."""


@dataclass(frozen=True, slots=True)
class BudgetPresetApplication:
    name: str
    assumptions: BudgetAssumptions
    skipped_categories: tuple[str, ...]


def budget_presets_for_user(user) -> tuple[BudgetAssumptionPreset, ...]:
    if not user.is_authenticated:
        return ()

    return tuple(
        BudgetAssumptionPreset.objects.filter(user=user)
        .prefetch_related("items")
        .order_by("name", "id")
    )


def budget_presets_for_categories(
    user,
    *,
    available_categories: set[str] | frozenset[str],
) -> tuple[BudgetAssumptionPreset, ...]:
    available = {str(category).strip().lower() for category in available_categories}
    allowed_categories = set(TypicalPriceCategory.values)
    if not available or not available.issubset(allowed_categories):
        raise BudgetAssumptionPresetError("Available budget categories are invalid.")

    return tuple(
        preset
        for preset in budget_presets_for_user(user)
        if any(item.category in available for item in preset.items.all())
    )


def budget_preset_for_user(user, *, preset_id: int) -> BudgetAssumptionPreset:
    if not user.is_authenticated:
        raise BudgetAssumptionPresetError("Authentication is required to use a budget preset.")

    try:
        return (
            BudgetAssumptionPreset.objects.filter(user=user)
            .prefetch_related("items")
            .get(pk=preset_id)
        )
    except BudgetAssumptionPreset.DoesNotExist as exc:
        raise BudgetAssumptionPresetError("This budget preset is no longer available.") from exc


def assumptions_from_budget_preset(
    user,
    *,
    preset_id: int,
    available_categories: set[str] | frozenset[str],
    basis: BudgetBasis,
) -> BudgetPresetApplication:
    if not isinstance(basis, BudgetBasis):
        raise BudgetAssumptionPresetError(
            "Budget preset basis must come from the current trusted budget context."
        )

    allowed_categories = set(TypicalPriceCategory.values)
    available = {str(category).strip().lower() for category in available_categories}
    if not available or not available.issubset(allowed_categories):
        raise BudgetAssumptionPresetError("Available budget categories are invalid.")

    preset = budget_preset_for_user(user, preset_id=preset_id)
    stored_items = tuple(preset.items.all())
    applicable_items = tuple(item for item in stored_items if item.category in available)
    skipped_categories = tuple(item.category for item in stored_items if item.category not in available)

    if not applicable_items:
        raise BudgetAssumptionPresetError(
            "None of this preset's basket items have current sourced price anchors "
            "at this destination."
        )

    try:
        assumptions = BudgetAssumptions(
            duration_days=preset.duration_days,
            travelers=preset.travelers,
            categories=tuple(
                BudgetCategoryAssumption(
                    category=item.category,
                    units_per_person_per_day=item.units_per_person_per_day,
                )
                for item in applicable_items
            ),
            basis=basis,
        )
    except BudgetInterpretationError as exc:
        raise BudgetAssumptionPresetError(str(exc)) from exc
    return BudgetPresetApplication(
        name=preset.name,
        assumptions=assumptions,
        skipped_categories=skipped_categories,
    )


def upsert_budget_preset(
    user,
    *,
    name: str,
    assumptions: BudgetAssumptions,
) -> BudgetAssumptionPreset:
    if not user.is_authenticated:
        raise BudgetAssumptionPresetError("Authentication is required to save a budget preset.")
    if not isinstance(assumptions, BudgetAssumptions):
        raise BudgetAssumptionPresetError("Budget preset assumptions are invalid.")

    normalized_name = " ".join(name.split())
    if not normalized_name:
        raise BudgetAssumptionPresetError("Enter a name for this budget preset.")
    if len(normalized_name) > 80:
        raise BudgetAssumptionPresetError("Budget preset name must be 80 characters or fewer.")

    allowed_categories = set(TypicalPriceCategory.values)
    if any(item.category not in allowed_categories for item in assumptions.categories):
        raise BudgetAssumptionPresetError("Budget preset contains an unsupported category.")

    user_model = get_user_model()
    with transaction.atomic():
        user_model.objects.select_for_update().get(pk=user.pk)
        preset = BudgetAssumptionPreset.objects.filter(
            user=user,
            name=normalized_name,
        ).first()
        if preset is None:
            if (
                BudgetAssumptionPreset.objects.filter(user=user).count()
                >= MAX_BUDGET_ASSUMPTION_PRESETS
            ):
                raise BudgetAssumptionPresetError(
                    f"You can save at most {MAX_BUDGET_ASSUMPTION_PRESETS} budget presets."
                )
            preset = BudgetAssumptionPreset(user=user, name=normalized_name)

        preset.duration_days = assumptions.duration_days
        preset.travelers = assumptions.travelers
        try:
            preset.full_clean()
        except ValidationError as exc:
            raise BudgetAssumptionPresetError(_validation_message(exc)) from exc
        preset.save()

        preset.items.all().delete()
        items = []
        for assumption in assumptions.categories:
            item = BudgetAssumptionPresetItem(
                preset=preset,
                category=assumption.category,
                units_per_person_per_day=assumption.units_per_person_per_day,
            )
            try:
                item.full_clean()
            except ValidationError as exc:
                raise BudgetAssumptionPresetError(_validation_message(exc)) from exc
            items.append(item)
        BudgetAssumptionPresetItem.objects.bulk_create(items)
        return preset


def delete_budget_preset(user, *, preset_id: int) -> bool:
    if not user.is_authenticated:
        raise BudgetAssumptionPresetError("Authentication is required to delete a budget preset.")

    deleted, _ = BudgetAssumptionPreset.objects.filter(pk=preset_id, user=user).delete()
    return bool(deleted)


def _validation_message(exc: ValidationError) -> str:
    if hasattr(exc, "message_dict"):
        for messages in exc.message_dict.values():
            if messages:
                return str(messages[0])
    if exc.messages:
        return str(exc.messages[0])
    return "Budget preset validation failed."
