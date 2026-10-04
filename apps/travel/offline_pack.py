from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, DecimalException, localcontext
from enum import StrEnum
from typing import Protocol

from django.db import DatabaseError
from django.utils import timezone

from apps.culture.services import DestinationContext
from apps.culture.services import build_destination_context as build_destination_context_default
from apps.travel.models import (
    SavedScenario,
    SavedScenarioKind,
    SavedScenarioObservation,
    SavedScenarioObservationKind,
    SavedScenarioSpendEntry,
)
from apps.travel.trip_budget import (
    TripBudgetSummary,
    calculate_trip_budget_summary,
    resolve_trip_budget_reference,
)

logger = logging.getLogger("cultural_currency.travel")

OFFLINE_DESTINATION_PACK_VERSION = 1


def offline_destination_pack_revision(
    scenario: SavedScenario,
    *,
    observations: tuple[SavedScenarioObservation, ...] | None = None,
    spend_entries: tuple[SavedScenarioSpendEntry, ...] | None = None,
) -> str:
    """Return an opaque revision for saved financial state used by an offline pack.

    Reviewed destination context intentionally is not folded into this revision:
    its own generated/as-of dates remain visible freshness evidence. This token
    answers only whether account-owned saved trip state changed.
    """

    selected_observations = (
        observations if observations is not None else tuple(scenario.observations.all())
    )
    selected_spend = spend_entries if spend_entries is not None else tuple(scenario.spend_entries.all())

    payload = {
        "schema_version": OFFLINE_DESTINATION_PACK_VERSION,
        "scenario": {
            "id": scenario.pk,
            "kind": scenario.kind,
            "title": scenario.title,
            "source_currency_id": scenario.source_currency_id,
            "destination_currency_id": scenario.destination_currency_id,
            "source_country_id": scenario.source_country_id,
            "destination_country_id": scenario.destination_country_id,
            "destination_city_id": scenario.destination_city_id,
            "source_amount": str(scenario.source_amount),
            "budget_basis": scenario.budget_basis,
            "planning_destination_amount": (
                str(scenario.planning_destination_amount)
                if scenario.planning_destination_amount is not None
                else None
            ),
            "fx_markup_percent": (
                str(scenario.fx_markup_percent) if scenario.fx_markup_percent is not None else None
            ),
            "source_fixed_fee": (
                str(scenario.source_fixed_fee) if scenario.source_fixed_fee is not None else None
            ),
            "destination_fixed_fee": (
                str(scenario.destination_fixed_fee)
                if scenario.destination_fixed_fee is not None
                else None
            ),
            "duration_days": scenario.duration_days,
            "travelers": scenario.travelers,
            "travel_start_date": (
                scenario.travel_start_date.isoformat() if scenario.travel_start_date else None
            ),
            "travel_end_date": (
                scenario.travel_end_date.isoformat() if scenario.travel_end_date else None
            ),
        },
        "observations": [
            {
                "id": item.pk,
                "kind": item.kind,
                "input_amount": str(item.input_amount),
                "output_amount": str(item.output_amount),
                "rate": str(item.rate),
                "effective_date": item.effective_date.isoformat(),
                "fetched_at": item.fetched_at.isoformat(),
                "provider_keys": tuple(str(key) for key in item.provider_keys),
                "stale": item.stale,
                "recorded_at": item.recorded_at.isoformat(),
            }
            for item in sorted(selected_observations, key=lambda value: value.pk or 0)
        ],
        "spend_entries": [
            {
                "id": item.pk,
                "amount": str(item.amount),
                "source": item.source,
                "recorded_at": item.recorded_at.isoformat(),
            }
            for item in sorted(selected_spend, key=lambda value: value.pk or 0)
        ],
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:32]


class OfflineDestinationPackError(ValueError):
    """Raised when a saved scenario cannot produce a trustworthy offline pack."""


class OfflineDestinationContextState(StrEnum):
    AVAILABLE = "available"
    EMPTY = "empty"
    DEGRADED = "degraded"


class OfflineDestinationContextBuilder(Protocol):
    def __call__(
        self,
        *,
        country_code: str,
        converted_amount: Decimal,
        quote_currency: str,
        as_of: date,
        price_limit: int,
        city_slug: str,
    ) -> DestinationContext | None: ...


@dataclass(frozen=True, slots=True)
class OfflineFxReference:
    source_amount: Decimal
    destination_amount: Decimal
    source_currency: str
    destination_currency: str
    rate: Decimal
    effective_date: date
    fetched_at: datetime
    provider_keys: tuple[str, ...]
    stale_when_saved: bool


@dataclass(frozen=True, slots=True)
class OfflineDestinationPack:
    schema_version: int
    generated_at: datetime
    context_as_of: date
    scenario_id: int
    scenario_title: str
    destination_country_code: str
    destination_country_name: str
    destination_city_slug: str
    destination_city_name: str
    travel_start_date: date | None
    travel_end_date: date | None
    duration_days: int | None
    travelers: int
    budget_basis: str
    planning_destination_amount: Decimal | None
    fx_markup_percent: Decimal | None
    source_fixed_fee: Decimal | None
    destination_fixed_fee: Decimal | None
    fx_reference: OfflineFxReference
    trip_budget: TripBudgetSummary
    destination_context: DestinationContext | None
    destination_context_state: OfflineDestinationContextState

    @property
    def destination_label(self) -> str:
        if self.destination_city_name:
            return f"{self.destination_city_name}, {self.destination_country_name}"
        return self.destination_country_name


def build_offline_destination_pack(
    scenario: SavedScenario,
    *,
    as_of: date | None = None,
    generated_at: datetime | None = None,
    destination_context_builder: OfflineDestinationContextBuilder | None = None,
) -> OfflineDestinationPack:
    """Create a self-contained snapshot from saved/account-owned state and reviewed context.

    No live FX call is made. The newest already-stored scenario observation is
    labelled as a stored reference, while Trip Budget Remaining stays anchored
    to the immutable initial observation.
    """

    if scenario.pk is None:
        raise OfflineDestinationPackError("Saved scenario must exist before an offline pack.")
    if scenario.kind != SavedScenarioKind.BUDGET:
        raise OfflineDestinationPackError(
            "Offline packs currently require a saved budget scenario."
        )
    if scenario.destination_country_id is None:
        raise OfflineDestinationPackError("Offline packs require a destination country.")

    selected_date = as_of or timezone.localdate()
    created_at = generated_at or timezone.now()

    initial = (
        scenario.observations.filter(kind=SavedScenarioObservationKind.INITIAL)
        .order_by("recorded_at", "id")
        .first()
    )
    latest = scenario.observations.order_by("-recorded_at", "-id").first()
    if initial is None or latest is None:
        raise OfflineDestinationPackError(
            "Offline packs require the saved scenario's trusted FX observation."
        )

    spend_entries = tuple(scenario.spend_entries.all())
    trip_budget = _trip_budget_summary(
        scenario,
        initial=initial,
        spend_entries=spend_entries,
        as_of=selected_date,
    )

    builder = destination_context_builder or build_destination_context_default
    destination_context: DestinationContext | None
    try:
        destination_context = builder(
            country_code=scenario.destination_country.iso2,
            converted_amount=latest.output_amount,
            quote_currency=scenario.destination_currency.code,
            as_of=selected_date,
            price_limit=6,
            city_slug=scenario.destination_city.slug
            if scenario.destination_city is not None
            else "",
        )
    except (DatabaseError, DecimalException, ValueError) as exc:
        logger.warning(
            "offline_destination_context_unavailable",
            extra={
                "scenario_id": scenario.pk,
                "error_code": exc.__class__.__name__,
            },
        )
        destination_context = None
        destination_state = OfflineDestinationContextState.DEGRADED
    else:
        destination_state = (
            OfflineDestinationContextState.AVAILABLE
            if destination_context is not None and destination_context.has_content
            else OfflineDestinationContextState.EMPTY
        )

    return OfflineDestinationPack(
        schema_version=OFFLINE_DESTINATION_PACK_VERSION,
        generated_at=created_at,
        context_as_of=selected_date,
        scenario_id=scenario.pk,
        scenario_title=scenario.title.strip() or scenario.get_kind_display(),
        destination_country_code=scenario.destination_country.iso2,
        destination_country_name=scenario.destination_country.name,
        destination_city_slug=(
            scenario.destination_city.slug if scenario.destination_city is not None else ""
        ),
        destination_city_name=(
            scenario.destination_city.name if scenario.destination_city is not None else ""
        ),
        travel_start_date=scenario.travel_start_date,
        travel_end_date=scenario.travel_end_date,
        duration_days=scenario.duration_days,
        travelers=scenario.travelers,
        budget_basis=scenario.budget_basis,
        planning_destination_amount=scenario.planning_destination_amount,
        fx_markup_percent=scenario.fx_markup_percent,
        source_fixed_fee=scenario.source_fixed_fee,
        destination_fixed_fee=scenario.destination_fixed_fee,
        fx_reference=_fx_reference(scenario, latest),
        trip_budget=trip_budget,
        destination_context=destination_context,
        destination_context_state=destination_state,
    )


def _fx_reference(
    scenario: SavedScenario,
    observation: SavedScenarioObservation,
) -> OfflineFxReference:
    return OfflineFxReference(
        source_amount=observation.input_amount,
        destination_amount=observation.output_amount,
        source_currency=scenario.source_currency.code,
        destination_currency=scenario.destination_currency.code,
        rate=observation.rate,
        effective_date=observation.effective_date,
        fetched_at=observation.fetched_at,
        provider_keys=tuple(str(key) for key in observation.provider_keys),
        stale_when_saved=observation.stale,
    )


def _trip_budget_summary(
    scenario: SavedScenario,
    *,
    initial: SavedScenarioObservation,
    spend_entries: tuple[SavedScenarioSpendEntry, ...],
    as_of: date,
) -> TripBudgetSummary:
    with localcontext() as context:
        context.prec = 64
        confirmed_spend = sum((entry.amount for entry in spend_entries), Decimal("0"))

    try:
        reference_budget = resolve_trip_budget_reference(
            budget_basis=scenario.budget_basis,
            initial_destination_amount=initial.output_amount,
            planning_destination_amount=scenario.planning_destination_amount,
        )
        return calculate_trip_budget_summary(
            reference_budget=reference_budget,
            confirmed_spend=confirmed_spend,
            duration_days=scenario.duration_days,
            travel_start_date=scenario.travel_start_date,
            travel_end_date=scenario.travel_end_date,
            as_of=as_of,
        )
    except ValueError as exc:
        raise OfflineDestinationPackError(
            "Saved trip budget state is not valid for an offline pack."
        ) from exc
