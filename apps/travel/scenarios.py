from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Protocol

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction

from apps.countries.models import City, Country, CountryCurrency, Currency
from apps.exchange.budget import BudgetCategoryAssumption
from apps.exchange.domain import ConversionResult
from apps.travel.models import (
    SavedScenario,
    SavedScenarioBudgetItem,
    SavedScenarioKind,
    SavedScenarioObservation,
    SavedScenarioObservationKind,
)

MAX_ACCOUNT_SCENARIOS = 50
MAX_PROVIDER_KEYS = 8
MAX_PROVIDER_KEY_LENGTH = 80


class SavedScenarioError(ValueError):
    """Raised when a saved-scenario request violates the domain contract."""


class ScenarioOwner(Protocol):
    pk: Any

    @property
    def is_authenticated(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class SavedScenarioSpec:
    kind: SavedScenarioKind
    source_currency: Currency
    destination_currency: Currency
    source_amount: Decimal
    source_country: Country | None = None
    destination_country: Country | None = None
    destination_city: City | None = None
    title: str = ""
    duration_days: int | None = None
    travelers: int = 1
    travel_start_date: date | None = None
    travel_end_date: date | None = None
    budget_categories: tuple[BudgetCategoryAssumption, ...] = ()


def create_saved_scenario(
    user: ScenarioOwner,
    *,
    spec: SavedScenarioSpec,
    conversion: ConversionResult,
) -> SavedScenario:
    """Create one user-owned scenario with an immutable initial FX observation."""

    if not user.is_authenticated:
        raise SavedScenarioError("Authentication is required to save a scenario.")
    if not isinstance(spec.kind, SavedScenarioKind):
        raise SavedScenarioError("Scenario kind must be a SavedScenarioKind value.")
    if conversion.quote.historical:
        raise SavedScenarioError("Saved travel scenarios require a current conversion.")
    if conversion.quote.base_currency != spec.source_currency.code:
        raise SavedScenarioError("Scenario source currency does not match the conversion.")
    if conversion.quote.quote_currency != spec.destination_currency.code:
        raise SavedScenarioError("Scenario destination currency does not match the conversion.")
    if conversion.input_amount != spec.source_amount:
        raise SavedScenarioError("Scenario source amount does not match the conversion input.")

    _validate_country_currency(spec.source_country, spec.source_currency, field_name="source")
    _validate_country_currency(
        spec.destination_country,
        spec.destination_currency,
        field_name="destination",
    )
    _validate_city(spec.destination_city, spec.destination_country)
    _validate_budget_categories(spec.budget_categories)
    provider_keys = _provider_keys(conversion.quote.provider_keys)

    user_model = get_user_model()
    with transaction.atomic():
        user_model.objects.select_for_update().get(pk=user.pk)
        if SavedScenario.objects.filter(user=user).count() >= MAX_ACCOUNT_SCENARIOS:
            raise SavedScenarioError(
                f"An account may store at most {MAX_ACCOUNT_SCENARIOS} saved scenarios."
            )

        scenario = SavedScenario(
            user=user,
            kind=spec.kind,
            title=spec.title.strip(),
            source_currency=spec.source_currency,
            destination_currency=spec.destination_currency,
            source_country=spec.source_country,
            destination_country=spec.destination_country,
            destination_city=spec.destination_city,
            source_amount=spec.source_amount,
            duration_days=spec.duration_days,
            travelers=spec.travelers,
            travel_start_date=spec.travel_start_date,
            travel_end_date=spec.travel_end_date,
        )
        try:
            scenario.full_clean()
        except ValidationError as exc:
            raise SavedScenarioError(_validation_message(exc)) from exc
        scenario.save()

        items = [
            SavedScenarioBudgetItem(
                scenario=scenario,
                category=item.category,
                units_per_person_per_day=item.units_per_person_per_day,
            )
            for item in spec.budget_categories
        ]
        for item in items:
            try:
                item.full_clean()
            except ValidationError as exc:
                raise SavedScenarioError(_validation_message(exc)) from exc
        if items:
            SavedScenarioBudgetItem.objects.bulk_create(items)

        _create_observation(
            scenario,
            conversion=conversion,
            kind=SavedScenarioObservationKind.INITIAL,
            provider_keys=provider_keys,
        )

    return scenario


def record_scenario_recheck(
    scenario: SavedScenario,
    *,
    conversion: ConversionResult,
) -> SavedScenarioObservation:
    """Persist a new immutable current FX observation for one scenario."""

    if conversion.quote.historical:
        raise SavedScenarioError("Scenario re-checks require a current conversion.")
    if conversion.quote.base_currency != scenario.source_currency.code:
        raise SavedScenarioError("Re-check source currency does not match the scenario.")
    if conversion.quote.quote_currency != scenario.destination_currency.code:
        raise SavedScenarioError("Re-check destination currency does not match the scenario.")
    if conversion.input_amount != scenario.source_amount:
        raise SavedScenarioError("Re-check amount does not match the scenario.")
    provider_keys = _provider_keys(conversion.quote.provider_keys)

    with transaction.atomic():
        locked = SavedScenario.objects.select_for_update().get(pk=scenario.pk)
        return _create_observation(
            locked,
            conversion=conversion,
            kind=SavedScenarioObservationKind.RECHECK,
            provider_keys=provider_keys,
        )


def _create_observation(
    scenario: SavedScenario,
    *,
    conversion: ConversionResult,
    kind: SavedScenarioObservationKind,
    provider_keys: list[str],
) -> SavedScenarioObservation:
    observation = SavedScenarioObservation(
        scenario=scenario,
        kind=kind,
        input_amount=conversion.input_amount,
        output_amount=conversion.output_amount,
        rate=conversion.quote.rate,
        effective_date=conversion.quote.effective_date,
        fetched_at=conversion.quote.fetched_at,
        provider_keys=provider_keys,
        stale=conversion.stale,
    )
    try:
        observation.full_clean()
    except ValidationError as exc:
        raise SavedScenarioError(_validation_message(exc)) from exc
    observation.save()
    return observation


def _validate_country_currency(
    country: Country | None,
    currency: Currency,
    *,
    field_name: str,
) -> None:
    if country is None:
        return
    is_valid = CountryCurrency.objects.current().filter(
        country=country,
        currency=currency,
    ).exists()
    if not is_valid:
        raise SavedScenarioError(
            f"{currency.code} is not the current {field_name} currency context for {country.iso2}."
        )


def _validate_city(city: City | None, country: Country | None) -> None:
    if city is None:
        return
    if country is None or city.country_id != country.pk:
        raise SavedScenarioError("Destination city must belong to the destination country.")
    if not city.is_active:
        raise SavedScenarioError("Destination city must be active when a scenario is created.")


def _validate_budget_categories(items: Iterable[BudgetCategoryAssumption]) -> None:
    materialized = tuple(items)
    if len(materialized) > 8:
        raise SavedScenarioError("A saved scenario may contain at most 8 budget categories.")
    names = [item.category for item in materialized]
    if len(names) != len(set(names)):
        raise SavedScenarioError("Saved scenario budget categories must be unique.")


def _provider_keys(values: tuple[str, ...]) -> list[str]:
    if len(values) > MAX_PROVIDER_KEYS:
        raise SavedScenarioError("Conversion provider attribution is too large to persist.")
    normalized: list[str] = []
    for value in values:
        if not isinstance(value, str):
            raise SavedScenarioError("Conversion provider attribution is invalid.")
        key = value.strip()
        if not key or len(key) > MAX_PROVIDER_KEY_LENGTH:
            raise SavedScenarioError("Conversion provider attribution is invalid.")
        normalized.append(key)
    return normalized


def _validation_message(exc: ValidationError) -> str:
    if hasattr(exc, "message_dict"):
        return "; ".join(
            message
            for messages in exc.message_dict.values()
            for message in messages
        )
    return "; ".join(exc.messages)
