from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any, Protocol
from uuid import UUID, uuid4

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction

from apps.countries.models import City, Country, CountryCurrency, Currency
from apps.exchange.budget import BudgetCategoryAssumption
from apps.exchange.domain import (
    MAX_PROVIDER_KEYS,
    ConversionResult,
    FxDomainError,
    normalize_provider_keys,
)
from apps.exchange.payment_estimate import PaymentEstimateError, estimate_payment_value
from apps.travel.models import (
    SavedScenario,
    SavedScenarioBudgetBasis,
    SavedScenarioBudgetItem,
    SavedScenarioKind,
    SavedScenarioObservation,
    SavedScenarioSpendEntry,
    SavedScenarioSpendSource,
)

MAX_ACCOUNT_SCENARIOS = 50
MAX_SCENARIO_OBSERVATIONS = 100
MAX_SCENARIO_SPEND_ENTRIES = 100
MAX_SCENARIO_SPEND_AMOUNT = Decimal("1000000000")


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
    budget_basis: SavedScenarioBudgetBasis = SavedScenarioBudgetBasis.REFERENCE_CONVERSION
    planning_destination_amount: Decimal | None = None
    fx_markup_percent: Decimal | None = None
    source_fixed_fee: Decimal | None = None
    destination_fixed_fee: Decimal | None = None


def create_saved_scenario(
    user: ScenarioOwner,
    *,
    spec: SavedScenarioSpec,
    conversion: ConversionResult,
) -> SavedScenario:
    """Create one user-owned scenario with an immutable initial FX observation."""

    if not user.is_authenticated or user.pk is None:
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
    _validate_budget_basis(spec, conversion=conversion)
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
            budget_basis=spec.budget_basis,
            planning_destination_amount=spec.planning_destination_amount,
            fx_markup_percent=spec.fx_markup_percent,
            source_fixed_fee=spec.source_fixed_fee,
            destination_fixed_fee=spec.destination_fixed_fee,
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
            kind="initial",
            provider_keys=provider_keys,
        )

    return scenario


def record_scenario_spend(
    scenario: SavedScenario,
    *,
    amount: Decimal,
    source: str | None = None,
    submission_key: UUID | None = None,
) -> SavedScenarioSpendEntry:
    """Persist one confirmed destination-currency spend entry.

    Spend entries intentionally contain only amount/source/timestamp. Receipt
    media, merchant identity and free-text purchase details are out of scope.
    """

    if not isinstance(amount, Decimal) or not amount.is_finite() or amount <= 0:
        raise SavedScenarioError("Confirmed spend must be a finite amount greater than zero.")
    if amount > MAX_SCENARIO_SPEND_AMOUNT:
        raise SavedScenarioError("Confirmed spend must be no greater than 1,000,000,000.")
    normalized_source = source or "manual"
    if normalized_source not in SavedScenarioSpendSource.values:
        raise SavedScenarioError("Confirmed spend source is invalid.")
    normalized_submission_key = submission_key or uuid4()

    with transaction.atomic():
        locked = (
            SavedScenario.objects.select_for_update()
            .select_related("destination_currency")
            .get(pk=scenario.pk)
        )
        if locked.kind != SavedScenarioKind.BUDGET:
            raise SavedScenarioError("Confirmed spend requires a saved budget scenario.")

        existing = locked.spend_entries.filter(submission_key=normalized_submission_key).first()
        if existing is not None:
            if existing.amount != amount or existing.source != normalized_source:
                raise SavedScenarioError(
                    "Confirmed spend submission key is already bound to a different entry."
                )
            return existing

        _validate_spend_amount(
            amount,
            minor_units=locked.destination_currency.minor_units,
        )
        if locked.spend_entries.count() >= MAX_SCENARIO_SPEND_ENTRIES:
            raise SavedScenarioError(
                f"A saved scenario may store at most {MAX_SCENARIO_SPEND_ENTRIES} spend entries."
            )

        entry = SavedScenarioSpendEntry(
            scenario=locked,
            submission_key=normalized_submission_key,
            amount=amount,
            source=normalized_source,
        )
        try:
            entry.full_clean()
        except ValidationError as exc:
            raise SavedScenarioError(_validation_message(exc)) from exc
        entry.save()
        locked.save(update_fields=("updated_at",))
        return entry


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
        latest = locked.observations.order_by("-recorded_at", "-id").first()
        if latest is not None and _observation_matches_conversion(
            latest,
            conversion=conversion,
            provider_keys=provider_keys,
        ):
            return latest

        if locked.observations.count() >= MAX_SCENARIO_OBSERVATIONS:
            raise SavedScenarioError(
                f"A saved scenario may store at most {MAX_SCENARIO_OBSERVATIONS} FX observations."
            )

        return _create_observation(
            locked,
            conversion=conversion,
            kind="recheck",
            provider_keys=provider_keys,
        )


def _observation_matches_conversion(
    observation: SavedScenarioObservation,
    *,
    conversion: ConversionResult,
    provider_keys: list[str],
) -> bool:
    """Return whether a provider observation is already represented by the latest row."""

    return (
        observation.input_amount == conversion.input_amount
        and observation.output_amount == conversion.output_amount
        and observation.rate == conversion.quote.rate
        and observation.effective_date == conversion.quote.effective_date
        and observation.provider_keys == provider_keys
        and observation.stale is conversion.stale
    )


def _create_observation(
    scenario: SavedScenario,
    *,
    conversion: ConversionResult,
    kind: str,
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
    is_valid = (
        CountryCurrency.objects.current()
        .filter(
            country=country,
            currency=currency,
        )
        .exists()
    )
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



def _validate_budget_basis(
    spec: SavedScenarioSpec,
    *,
    conversion: ConversionResult,
) -> None:
    if not isinstance(spec.budget_basis, SavedScenarioBudgetBasis):
        raise SavedScenarioError("Scenario budget basis is invalid.")

    payment_fields = (
        spec.planning_destination_amount,
        spec.fx_markup_percent,
        spec.source_fixed_fee,
        spec.destination_fixed_fee,
    )
    if spec.budget_basis is SavedScenarioBudgetBasis.REFERENCE_CONVERSION:
        if any(value is not None for value in payment_fields):
            raise SavedScenarioError(
                "Reference-conversion scenarios cannot carry payment-estimate assumptions."
            )
        return

    if spec.kind is not SavedScenarioKind.BUDGET:
        raise SavedScenarioError("Payment-adjusted planning is supported only for budget scenarios.")
    if any(value is None for value in payment_fields):
        raise SavedScenarioError("Payment-adjusted scenarios require complete payment assumptions.")

    planning_amount = spec.planning_destination_amount
    markup = spec.fx_markup_percent
    source_fee = spec.source_fixed_fee
    destination_fee = spec.destination_fixed_fee
    if not all(
        isinstance(value, Decimal) and value.is_finite()
        for value in (planning_amount, markup, source_fee, destination_fee)
    ):
        raise SavedScenarioError("Payment-adjusted scenario values must be finite decimals.")
    assert planning_amount is not None
    assert markup is not None
    assert source_fee is not None
    assert destination_fee is not None
    try:
        expected = estimate_payment_value(
            source_budget=conversion.input_amount,
            reference_destination_amount=conversion.output_amount,
            rate=conversion.quote.rate,
            fx_markup_percent=markup,
            source_fixed_fee=source_fee,
            destination_fixed_fee=destination_fee,
            destination_minor_units=spec.destination_currency.minor_units,
        )
    except PaymentEstimateError as exc:
        raise SavedScenarioError(
            "Saved payment assumptions do not produce a valid planning amount."
        ) from exc

    if planning_amount != expected.estimated_destination_amount:
        raise SavedScenarioError(
            "Payment-adjusted planning amount must match the deterministic payment estimate."
        )


def _validate_spend_amount(amount: Decimal, *, minor_units: int) -> None:
    if not 0 <= minor_units <= 6:
        raise SavedScenarioError("Destination currency minor-unit metadata is unsupported.")

    quantum = Decimal(1).scaleb(-minor_units)
    try:
        with localcontext() as context:
            context.prec = max(64, len(amount.as_tuple().digits) + minor_units + 8)
            normalized = amount.quantize(quantum)
    except InvalidOperation as exc:
        raise SavedScenarioError(
            "Confirmed spend cannot be represented in the destination currency."
        ) from exc

    if normalized != amount:
        place_label = "decimal place" if minor_units == 1 else "decimal places"
        raise SavedScenarioError(
            f"Confirmed spend supports at most {minor_units} {place_label} "
            "for the destination currency."
        )


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
    try:
        return list(normalize_provider_keys(values))
    except FxDomainError as exc:
        raise SavedScenarioError("Conversion provider attribution is invalid.") from exc


def _validation_message(exc: ValidationError) -> str:
    if hasattr(exc, "message_dict"):
        return "; ".join(message for messages in exc.message_dict.values() for message in messages)
    return "; ".join(exc.messages)
