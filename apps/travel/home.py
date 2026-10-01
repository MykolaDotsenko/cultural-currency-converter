from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, DecimalException, localcontext
from typing import Any, Protocol
from urllib.parse import urlencode

from django.db import DatabaseError
from django.db.models import Sum
from django.urls import reverse
from django.utils import timezone

from apps.culture.services import DestinationContext, build_destination_context
from apps.travel.models import (
    SavedScenario,
    SavedScenarioKind,
    SavedScenarioObservation,
    SavedScenarioObservationKind,
)
from apps.travel.scenario_comparison import (
    ScenarioObservationComparison,
    ScenarioRateDirection,
    compare_scenario_observations,
)
from apps.travel.scenario_schedule import (
    TripSchedule,
    TripScheduleState,
    evaluate_trip_schedule,
)
from apps.travel.trip_budget import TripBudgetSummary, calculate_trip_budget_summary

logger = logging.getLogger("cultural_currency.travel")


class ScenarioOwner(Protocol):
    pk: Any

    @property
    def is_authenticated(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class ReturningTripHome:
    """Compact continuity state for the converter home page.

    All monetary values come from already-saved trusted observations. Building
    this surface must never trigger a live FX request.
    """

    scenario: SavedScenario
    schedule: TripSchedule
    initial_observation: SavedScenarioObservation | None
    latest_observation: SavedScenarioObservation | None
    rate_comparison: ScenarioObservationComparison | None
    trip_budget: TripBudgetSummary | None
    destination_context: DestinationContext | None
    detail_url: str
    converter_url: str
    camera_url: str
    offline_pack_url: str

    @property
    def destination_label(self) -> str:
        if self.scenario.destination_city is not None:
            return f"{self.scenario.destination_city.name}, {self.scenario.destination_country.name}"
        if self.scenario.destination_country is not None:
            return self.scenario.destination_country.name
        return self.scenario.destination_currency.code

    @property
    def kicker(self) -> str:
        if self.schedule.state is TripScheduleState.ACTIVE:
            return "Active trip"
        if self.schedule.state is TripScheduleState.STARTED:
            return "Trip started"
        return "Upcoming trip"

    @property
    def timing_label(self) -> str:
        if self.schedule.state is TripScheduleState.ACTIVE:
            if self.schedule.end_date is None:
                return "Your saved travel window is active."
            return f"Travel window active through {self.schedule.end_date:%-d %b %Y}."
        if self.schedule.state is TripScheduleState.STARTED:
            return "Your saved start date has arrived; no end date is stored."
        days = self.schedule.days_until_start or 0
        if days == 1:
            return "Starts tomorrow."
        return f"Starts in {days} days."

    @property
    def primary_action_label(self) -> str:
        if self.schedule.state in {TripScheduleState.ACTIVE, TripScheduleState.STARTED}:
            return "Check trip budget"
        if (self.schedule.days_until_start or 9999) <= 7:
            return "Re-check trip"
        return "Open trip"

    @property
    def latest_price_observed_at(self) -> date | None:
        if self.destination_context is None or not self.destination_context.prices:
            return None
        return max(item.observed_at for item in self.destination_context.prices)

    @property
    def payment_verified_at(self) -> date | None:
        if self.destination_context is None or self.destination_context.payment is None:
            return None
        return self.destination_context.payment.verified_at.date()

    @property
    def rate_change_phrase(self) -> str:
        comparison = self.rate_comparison
        if comparison is None:
            return ""
        currency = self.scenario.destination_currency.code
        difference = _decimal_text(abs(comparison.output_amount_difference))
        if comparison.direction is ScenarioRateDirection.HIGHER:
            return f"{difference} {currency} more than the saved baseline"
        if comparison.direction is ScenarioRateDirection.LOWER:
            return f"{difference} {currency} less than the saved baseline"
        return f"No change in {currency} output from the saved baseline"


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _scenario_converter_url(scenario: SavedScenario) -> str:
    params = {
        "convert": "1",
        "amount": _decimal_text(scenario.source_amount),
        "source_currency": scenario.source_currency.code,
        "destination_currency": scenario.destination_currency.code,
    }
    if scenario.source_country is not None:
        params["source_country"] = scenario.source_country.iso2
    if scenario.destination_country is not None:
        params["destination_country"] = scenario.destination_country.iso2
    if scenario.destination_city is not None:
        params["destination_city_slug"] = scenario.destination_city.slug
    return f"{reverse('converter')}?{urlencode(params)}"


def _candidate_priority(
    scenario: SavedScenario,
    *,
    as_of: date,
) -> tuple[int, int, int] | None:
    try:
        schedule = evaluate_trip_schedule(
            start_date=scenario.travel_start_date,
            end_date=scenario.travel_end_date,
            as_of=as_of,
        )
    except ValueError:
        logger.warning(
            "returning_trip_home_schedule_invalid",
            extra={"scenario_id": scenario.pk},
        )
        return None

    start_ordinal = scenario.travel_start_date.toordinal() if scenario.travel_start_date else 0
    scenario_id = scenario.pk or 0
    if schedule.state is TripScheduleState.ACTIVE:
        return 0, -start_ordinal, -scenario_id
    if schedule.state is TripScheduleState.STARTED:
        return 1, -start_ordinal, -scenario_id
    if schedule.state is TripScheduleState.UPCOMING:
        return 2, start_ordinal, scenario_id
    return None


def _focus_scenario(owner: ScenarioOwner, *, as_of: date) -> SavedScenario | None:
    candidates = (
        SavedScenario.objects.filter(
            user_id=owner.pk,
            kind__in=(SavedScenarioKind.TRIP, SavedScenarioKind.BUDGET),
            travel_start_date__isnull=False,
        )
        .select_related(
            "source_currency",
            "destination_currency",
            "source_country",
            "destination_country",
            "destination_city",
        )
        .order_by("travel_start_date", "id")[:50]
    )

    ranked: list[tuple[tuple[int, int, int], SavedScenario]] = []
    for scenario in candidates:
        priority = _candidate_priority(scenario, as_of=as_of)
        if priority is not None:
            ranked.append((priority, scenario))
    if not ranked:
        return None
    ranked.sort(key=lambda item: item[0])
    return ranked[0][1]


def _observations(
    scenario: SavedScenario,
) -> tuple[SavedScenarioObservation | None, SavedScenarioObservation | None]:
    initial = (
        scenario.observations.filter(kind=SavedScenarioObservationKind.INITIAL)
        .order_by("recorded_at", "id")
        .first()
    )
    latest = scenario.observations.order_by("-recorded_at", "-id").first()
    return initial, latest


def _trip_budget(
    scenario: SavedScenario,
    *,
    initial: SavedScenarioObservation | None,
    as_of: date,
) -> TripBudgetSummary | None:
    if scenario.kind != SavedScenarioKind.BUDGET or initial is None:
        return None

    confirmed_spend = scenario.spend_entries.aggregate(total=Sum("amount"))["total"] or Decimal("0")
    try:
        with localcontext() as context:
            context.prec = 64
            confirmed_spend = Decimal(confirmed_spend)
        return calculate_trip_budget_summary(
            reference_budget=initial.output_amount,
            confirmed_spend=confirmed_spend,
            duration_days=scenario.duration_days,
            travel_start_date=scenario.travel_start_date,
            travel_end_date=scenario.travel_end_date,
            as_of=as_of,
        )
    except (DecimalException, ValueError):
        logger.warning(
            "returning_trip_home_budget_invalid",
            extra={"scenario_id": scenario.pk},
        )
        return None


def _current_destination_context(
    scenario: SavedScenario,
    *,
    latest: SavedScenarioObservation | None,
    as_of: date,
) -> DestinationContext | None:
    if scenario.destination_country is None or latest is None:
        return None
    try:
        return build_destination_context(
            country_code=scenario.destination_country.iso2,
            converted_amount=latest.output_amount,
            quote_currency=scenario.destination_currency.code,
            as_of=as_of,
            price_limit=3,
            city_slug=scenario.destination_city.slug if scenario.destination_city is not None else "",
        )
    except (DatabaseError, DecimalException, ValueError) as exc:
        logger.warning(
            "returning_trip_home_context_unavailable",
            extra={
                "scenario_id": scenario.pk,
                "error_code": exc.__class__.__name__,
            },
        )
        return None


def build_returning_trip_home(
    owner: ScenarioOwner,
    *,
    as_of: date | None = None,
    camera_enabled: bool = False,
) -> ReturningTripHome | None:
    """Build the one saved trip that deserves continuity on the converter home.

    The query is owner-scoped and provider-free. Ended/unscheduled scenarios
    deliberately do not displace the normal converter-first home.
    """

    if not owner.is_authenticated or owner.pk is None:
        return None

    selected_date = as_of or timezone.localdate()
    scenario = _focus_scenario(owner, as_of=selected_date)
    if scenario is None:
        return None

    schedule = evaluate_trip_schedule(
        start_date=scenario.travel_start_date,
        end_date=scenario.travel_end_date,
        as_of=selected_date,
    )
    initial, latest = _observations(scenario)

    comparison = None
    if initial is not None and latest is not None and initial.pk != latest.pk:
        try:
            comparison = compare_scenario_observations(initial, latest)
        except ValueError:
            logger.warning(
                "returning_trip_home_rate_comparison_invalid",
                extra={"scenario_id": scenario.pk},
            )

    trip_budget = _trip_budget(scenario, initial=initial, as_of=selected_date)
    destination_context = _current_destination_context(
        scenario,
        latest=latest or initial,
        as_of=selected_date,
    )

    return ReturningTripHome(
        scenario=scenario,
        schedule=schedule,
        initial_observation=initial,
        latest_observation=latest,
        rate_comparison=comparison,
        trip_budget=trip_budget,
        destination_context=destination_context,
        detail_url=reverse("saved_scenario_detail", args=(scenario.pk,)),
        converter_url=_scenario_converter_url(scenario),
        camera_url=(
            reverse("camera_scan_saved_scenario", args=(scenario.pk,))
            if camera_enabled and scenario.kind == SavedScenarioKind.BUDGET
            else ""
        ),
        offline_pack_url=(
            reverse("download_offline_destination_pack", args=(scenario.pk,))
            if scenario.kind == SavedScenarioKind.BUDGET
            else ""
        ),
    )
