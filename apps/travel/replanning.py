"""Atomic, owner-scoped versioned budget planning; original money is immutable."""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction

from apps.travel.models import SavedScenario, SavedScenarioKind, SavedScenarioPlanRevision

_MAX_REVISIONS = 20
_CENT = Decimal("0.01")
_MAX_UNITS = Decimal("100")


class ReplanningError(ValueError):
    pass


class ReplanningConflict(ReplanningError):
    pass


def _category_snapshot(items: tuple) -> list[dict[str, str]]:
    """Stable display-only history; no amounts, prices or user identity."""

    return [
        {
            "category": item.category,
            "units_per_person_per_day": format(item.units_per_person_per_day, ".2f"),
        }
        for item in items
    ]


@transaction.atomic
def replan_budget(
    *,
    owner_id: int,
    scenario_id: int,
    expected_version: str,
    travelers: int,
    duration_days: int | None,
    budget_item_changes: dict[int, Decimal] | None = None,
) -> bool:
    """Record a new planning revision only for explicit, validated changes."""

    if isinstance(travelers, bool) or not isinstance(travelers, int) or not 1 <= travelers <= 20:
        raise ReplanningError("Travelers must be between 1 and 20.")
    if duration_days is not None and (
        isinstance(duration_days, bool)
        or not isinstance(duration_days, int)
        or not 1 <= duration_days <= 365
    ):
        raise ReplanningError("Duration must be 1–365 days or left unspecified.")

    requested = budget_item_changes if budget_item_changes is not None else {}
    if not isinstance(requested, dict):
        raise ReplanningError("Budget category adjustments must be explicit.")
    if any(
        isinstance(key, bool)
        or not isinstance(key, int)
        or isinstance(value, bool)
        or not isinstance(value, Decimal)
        or not value.is_finite()
        or not _CENT <= value <= _MAX_UNITS
        or value != value.quantize(_CENT)
        for key, value in requested.items()
    ):
        raise ReplanningError("Category units must be 0.01–100 with at most two decimals.")

    scenario = (
        SavedScenario.objects.select_for_update().filter(pk=scenario_id, user_id=owner_id).first()
    )
    if scenario is None or scenario.kind != SavedScenarioKind.BUDGET:
        raise ReplanningError("This budget is unavailable.")
    if scenario.updated_at.isoformat() != expected_version:
        raise ReplanningConflict("The budget changed in another tab. Review the current plan.")

    items = tuple(scenario.budget_items.select_for_update().order_by("category", "pk"))
    known_ids = {item.pk for item in items}
    if not set(requested).issubset(known_ids):
        raise ReplanningError("A requested category is no longer part of this saved budget.")

    updates = [
        (item, requested[item.pk])
        for item in items
        if item.pk in requested and item.units_per_person_per_day != requested[item.pk]
    ]
    if scenario.travelers == travelers and scenario.duration_days == duration_days and not updates:
        return False

    newest = scenario.plan_revisions.order_by("-revision").first()
    next_revision = newest.revision + 1 if newest is not None else 1
    if next_revision > _MAX_REVISIONS:
        raise ReplanningError("This budget has reached its maximum planning revisions.")

    if newest is None:
        SavedScenarioPlanRevision.objects.create(
            scenario=scenario,
            revision=0,
            travelers=scenario.travelers,
            duration_days=scenario.duration_days,
            category_snapshot=_category_snapshot(items),
        )

    scenario.travelers = travelers
    scenario.duration_days = duration_days
    scenario.full_clean()
    scenario.save(update_fields=("travelers", "duration_days", "updated_at"))
    for item, value in updates:
        item.units_per_person_per_day = value
        item.full_clean()
        item.save(update_fields=("units_per_person_per_day", "updated_at"))

    SavedScenarioPlanRevision.objects.create(
        scenario=scenario,
        revision=next_revision,
        travelers=travelers,
        duration_days=duration_days,
        category_snapshot=_category_snapshot(items),
    )
    return True
