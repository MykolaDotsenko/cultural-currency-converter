from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Prefetch

from apps.accounts.models import BudgetPreset, BudgetPresetItem
from apps.exchange.budget import (
    BudgetAssumptions,
    BudgetBasis,
    BudgetCategoryAssumption,
    BudgetInterpretationError,
)

MAX_BUDGET_PRESETS = 12


class BudgetPresetError(ValueError):
    """Raised when reusable budget assumptions violate the preset contract."""


def budget_presets_for_user(user) -> tuple[BudgetPreset, ...]:
    if not user.is_authenticated:
        return ()

    return tuple(
        BudgetPreset.objects.filter(user=user)
        .prefetch_related(
            Prefetch(
                "items",
                queryset=BudgetPresetItem.objects.order_by("category", "id"),
            )
        )
        .order_by("name", "id")
    )


def budget_preset_for_user(user, *, preset_id: int) -> BudgetPreset:
    if not user.is_authenticated:
        raise BudgetPresetError("Authentication is required to use a saved budget preset.")

    try:
        return (
            BudgetPreset.objects.filter(pk=preset_id, user=user)
            .prefetch_related(
                Prefetch(
                    "items",
                    queryset=BudgetPresetItem.objects.order_by("category", "id"),
                )
            )
            .get()
        )
    except BudgetPreset.DoesNotExist as exc:
        raise BudgetPresetError("This saved budget preset is no longer available.") from exc


def upsert_budget_preset(
    user,
    *,
    name: str,
    duration_days: int,
    travelers: int,
    categories: Iterable[BudgetCategoryAssumption],
) -> BudgetPreset:
    if not user.is_authenticated:
        raise BudgetPresetError("Authentication is required to save a budget preset.")

    normalized_name = " ".join(name.split())
    if not normalized_name:
        raise BudgetPresetError("Enter a name for this budget preset.")
    if len(normalized_name) > 80:
        raise BudgetPresetError("Budget preset name must be 80 characters or fewer.")

    try:
        assumptions = BudgetAssumptions(
            duration_days=duration_days,
            travelers=travelers,
            categories=tuple(categories),
            basis=BudgetBasis.REFERENCE_CONVERSION,
        )
    except BudgetInterpretationError as exc:
        raise BudgetPresetError(str(exc)) from exc

    user_model = get_user_model()
    with transaction.atomic():
        user_model.objects.select_for_update().get(pk=user.pk)
        preset = BudgetPreset.objects.filter(user=user, name=normalized_name).first()
        if preset is None:
            if BudgetPreset.objects.filter(user=user).count() >= MAX_BUDGET_PRESETS:
                raise BudgetPresetError(
                    f"You can save at most {MAX_BUDGET_PRESETS} budget presets."
                )
            preset = BudgetPreset(user=user, name=normalized_name)

        preset.duration_days = assumptions.duration_days
        preset.travelers = assumptions.travelers
        try:
            preset.full_clean()
        except ValidationError as exc:
            raise BudgetPresetError(_validation_message(exc)) from exc
        preset.save()

        replacement_items = [
            BudgetPresetItem(
                preset=preset,
                category=item.category,
                units_per_person_per_day=item.units_per_person_per_day,
            )
            for item in assumptions.categories
        ]
        for item in replacement_items:
            try:
                item.full_clean(validate_unique=False)
            except ValidationError as exc:
                raise BudgetPresetError(_validation_message(exc)) from exc

        preset.items.all().delete()
        BudgetPresetItem.objects.bulk_create(replacement_items)

        return budget_preset_for_user(user, preset_id=preset.pk)


def delete_budget_preset(user, *, preset_id: int) -> bool:
    if not user.is_authenticated:
        raise BudgetPresetError("Authentication is required to delete a budget preset.")

    deleted, _ = BudgetPreset.objects.filter(pk=preset_id, user=user).delete()
    return bool(deleted)


def preset_post_values(preset: BudgetPreset) -> dict[str, str]:
    values = {
        "duration_days": str(preset.duration_days),
        "travelers": str(preset.travelers),
    }
    for item in preset.items.all():
        values[f"units_{item.category}"] = _decimal_text(item.units_per_person_per_day)
    return values


def preset_categories(preset: BudgetPreset) -> tuple[BudgetCategoryAssumption, ...]:
    return tuple(
        BudgetCategoryAssumption(
            category=item.category,
            units_per_person_per_day=item.units_per_person_per_day,
        )
        for item in preset.items.all()
    )


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _validation_message(exc: ValidationError) -> str:
    if hasattr(exc, "message_dict"):
        for messages in exc.message_dict.values():
            if messages:
                return str(messages[0])
    if exc.messages:
        return str(exc.messages[0])
    return "Budget preset validation failed."
