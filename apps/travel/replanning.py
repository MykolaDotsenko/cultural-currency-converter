"""Atomic owner-scoped re-planning of budget duration and traveler count.

Never changes the trusted FX baseline, payment assumptions, recorded spend
or separately maintained local price/context evidence.
"""

from __future__ import annotations

from django.db import transaction

from apps.travel.models import SavedScenario, SavedScenarioKind, SavedScenarioPlanRevision

_MAX_REVISIONS = 20


class ReplanningError(ValueError):
    pass


class ReplanningConflict(ReplanningError):
    pass


@transaction.atomic
def replan_budget(
    *,
    owner_id: int,
    scenario_id: int,
    expected_version: str,
    travelers: int,
    duration_days: int | None,
) -> bool:
    """Return whether anything changed. Lock and check the submitted version."""

    if isinstance(travelers, bool) or not isinstance(travelers, int) or not 1 <= travelers <= 20:
        raise ReplanningError("Travelers must be between 1 and 20.")
    if duration_days is not None and (
        isinstance(duration_days, bool)
        or not isinstance(duration_days, int)
        or not 1 <= duration_days <= 365
    ):
        raise ReplanningError("Duration must be 1–365 days or left unspecified.")

    scenario = SavedScenario.objects.select_for_update().filter(
        pk=scenario_id,
        user_id=owner_id,
    ).first()
    if scenario is None or scenario.kind != SavedScenarioKind.BUDGET:
        raise ReplanningError("This budget is unavailable.")
    if scenario.updated_at.isoformat() != expected_version:
        raise ReplanningConflict("The budget changed in another tab. Review the current plan.")

    if scenario.travelers == travelers and scenario.duration_days == duration_days:
        return False

    newest = scenario.plan_revisions.order_by("-revision").first()
    if newest is None:
        SavedScenarioPlanRevision.objects.create(
            scenario=scenario,
            revision=0,
            travelers=scenario.travelers,
            duration_days=scenario.duration_days,
        )
        next_revision = 1
    else:
        next_revision = newest.revision + 1
    if next_revision > _MAX_REVISIONS:
        raise ReplanningError("This budget has reached its maximum planning revisions.")

    scenario.travelers = travelers
    scenario.duration_days = duration_days
    scenario.full_clean()
    scenario.save(update_fields=("travelers", "duration_days", "updated_at"))
    SavedScenarioPlanRevision.objects.create(
        scenario=scenario,
        revision=next_revision,
        travelers=travelers,
        duration_days=duration_days,
    )
    return True
