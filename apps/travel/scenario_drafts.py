from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from django.db import DatabaseError

from apps.countries.models import City, Country, Currency
from apps.exchange.budget import BudgetAssumptions
from apps.exchange.budget_snapshot import (
    BudgetContextTokenError,
    load_budget_context_snapshot_token,
)
from apps.exchange.forms import BudgetInterpretationForm
from apps.exchange.payment_budget_snapshot import (
    PaymentBudgetHandoffTokenError,
    load_payment_budget_handoff_token,
)
from apps.exchange.payment_estimate import PaymentEstimateError, estimate_payment_value
from apps.exchange.shopping_snapshot import (
    ShoppingContextTokenError,
    load_shopping_context_snapshot_token,
)
from apps.travel.forms import SavedScenarioPlanningForm
from apps.travel.models import SavedScenarioBudgetBasis, SavedScenarioKind
from apps.travel.scenarios import (
    SavedScenarioError,
    SavedScenarioSpec,
    validate_saved_scenario_spec,
)


class ScenarioDraftError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.user_message = message
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class ScenarioDraft:
    spec: SavedScenarioSpec
    conversion: Any


def build_budget_scenario_draft(data: Mapping[str, Any]) -> ScenarioDraft:
    submitted_budget_token = str(data.get("budget_context_token") or "")
    payment_budget_token = str(data.get("payment_budget_token") or "")
    payment_handoff = None
    token = submitted_budget_token

    if payment_budget_token:
        try:
            payment_handoff = load_payment_budget_handoff_token(payment_budget_token)
        except PaymentBudgetHandoffTokenError as exc:
            raise ScenarioDraftError(
                "invalid_payment_budget_handoff",
                "This payment-adjusted budget is no longer valid. Recalculate the payment estimate.",
            ) from exc
        if (
            submitted_budget_token
            and payment_handoff.budget_context_token != submitted_budget_token
        ):
            raise ScenarioDraftError(
                "payment_budget_context_mismatch",
                "The saved budget basis no longer matches this conversion. Reopen budget planning.",
            )
        token = payment_handoff.budget_context_token

    try:
        snapshot = load_budget_context_snapshot_token(token)
    except BudgetContextTokenError as exc:
        raise ScenarioDraftError(
            "invalid_budget_context",
            "This budget context is no longer valid. Run the conversion again before saving.",
        ) from exc

    try:
        source_currency = Currency.objects.get(code=snapshot.conversion.quote.base_currency)
        destination_currency = Currency.objects.get(code=snapshot.conversion.quote.quote_currency)
        destination_country = Country.objects.get(
            iso2=snapshot.destination_country_code,
            is_active=True,
        )
        destination_city = None
        if snapshot.destination_city_slug:
            destination_city = City.objects.get(
                country=destination_country,
                slug=snapshot.destination_city_slug,
                is_active=True,
            )
    except (Currency.DoesNotExist, Country.DoesNotExist, City.DoesNotExist) as exc:
        raise ScenarioDraftError(
            "destination_metadata_missing",
            "The saved destination metadata is no longer available. Run the conversion again.",
        ) from exc

    # Signed context establishes conversion/scope. Only explicit user assumptions
    # are parsed here; no second price-context or FX lookup is permitted.
    form = BudgetInterpretationForm(data, category_options=())
    if not form.is_valid():
        raise ScenarioDraftError(
            "invalid_budget_assumptions",
            "The budget assumptions changed or are invalid. Interpret the budget again before saving.",
        )
    assumptions = form.cleaned_data.get("budget_assumptions")
    if not isinstance(assumptions, BudgetAssumptions):
        raise RuntimeError("Valid budget scenario form returned no BudgetAssumptions.")

    planning_form = SavedScenarioPlanningForm(data)
    if not planning_form.is_valid():
        first_error = next(
            (str(message) for errors in planning_form.errors.values() for message in errors),
            "The saved trip details are invalid.",
        )
        raise ScenarioDraftError("invalid_trip_planning", f"Could not save trip timing: {first_error}")

    raw_title = str(planning_form.cleaned_data.get("title") or "")
    destination_name = (
        destination_city.name if destination_city is not None else destination_country.name
    )
    title = raw_title or f"{destination_name} budget"

    saved_budget_basis = SavedScenarioBudgetBasis.REFERENCE_CONVERSION
    planning_destination_amount = None
    fx_markup_percent = None
    source_fixed_fee = None
    destination_fixed_fee = None
    if payment_handoff is not None:
        try:
            estimate = estimate_payment_value(
                source_budget=snapshot.conversion.input_amount,
                reference_destination_amount=snapshot.conversion.output_amount,
                rate=snapshot.conversion.quote.rate,
                fx_markup_percent=payment_handoff.fx_markup_percent,
                source_fixed_fee=payment_handoff.source_fixed_fee,
                destination_fixed_fee=payment_handoff.destination_fixed_fee,
                destination_minor_units=destination_currency.minor_units,
            )
        except PaymentEstimateError as exc:
            raise ScenarioDraftError(
                "invalid_payment_assumptions",
                "These payment assumptions can no longer be saved safely. Recalculate the payment estimate.",
            ) from exc
        saved_budget_basis = SavedScenarioBudgetBasis.PAYMENT_ESTIMATE
        planning_destination_amount = estimate.estimated_destination_amount
        fx_markup_percent = estimate.fx_markup_percent
        source_fixed_fee = estimate.source_fixed_fee
        destination_fixed_fee = estimate.destination_fixed_fee

    spec = SavedScenarioSpec(
        kind=SavedScenarioKind.BUDGET,
        title=title,
        source_currency=source_currency,
        destination_currency=destination_currency,
        source_country=None,
        destination_country=destination_country,
        destination_city=destination_city,
        source_amount=snapshot.conversion.input_amount,
        budget_basis=saved_budget_basis,
        planning_destination_amount=planning_destination_amount,
        fx_markup_percent=fx_markup_percent,
        source_fixed_fee=source_fixed_fee,
        destination_fixed_fee=destination_fixed_fee,
        duration_days=assumptions.duration_days,
        travelers=assumptions.travelers,
        travel_start_date=planning_form.cleaned_data.get("travel_start_date"),
        travel_end_date=planning_form.cleaned_data.get("travel_end_date"),
        budget_categories=assumptions.categories,
    )
    try:
        validate_saved_scenario_spec(spec=spec, conversion=snapshot.conversion)
    except SavedScenarioError as exc:
        raise ScenarioDraftError("scenario_domain_rejected", str(exc)) from exc
    return ScenarioDraft(spec=spec, conversion=snapshot.conversion)


def build_shopping_scenario_draft(data: Mapping[str, Any]) -> ScenarioDraft:
    token = str(data.get("shopping_context_token") or "")
    try:
        snapshot = load_shopping_context_snapshot_token(token)
    except ShoppingContextTokenError as exc:
        raise ScenarioDraftError(
            "invalid_shopping_context",
            "This Shopping estimate is no longer valid. Recalculate it before saving.",
        ) from exc

    try:
        currencies = Currency.objects.in_bulk(
            [
                snapshot.conversion.quote.base_currency,
                snapshot.conversion.quote.quote_currency,
            ],
            field_name="code",
        )
        source_currency = currencies[snapshot.conversion.quote.base_currency]
        destination_currency = currencies[snapshot.conversion.quote.quote_currency]
        source_country = None
        if snapshot.purchase_country_code:
            source_country = Country.objects.get(
                iso2=snapshot.purchase_country_code,
                is_active=True,
            )
    except (KeyError, Country.DoesNotExist) as exc:
        raise ScenarioDraftError(
            "shopping_metadata_missing",
            "The Shopping currency or country metadata is no longer available. Recalculate it.",
        ) from exc

    raw_title = str(data.get("title") or "").strip()
    if len(raw_title) > 120:
        raise ScenarioDraftError(
            "invalid_shopping_title",
            "Shopping scenario title must be 120 characters or fewer.",
        )
    title = raw_title or (
        f"{source_country.name} purchase"
        if source_country is not None
        else f"{source_currency.code} purchase"
    )

    spec = SavedScenarioSpec(
        kind=SavedScenarioKind.SHOPPING,
        title=title,
        source_currency=source_currency,
        destination_currency=destination_currency,
        source_country=source_country,
        source_amount=snapshot.conversion.input_amount,
        shopping_assumptions=snapshot.assumptions,
    )
    try:
        validate_saved_scenario_spec(spec=spec, conversion=snapshot.conversion)
    except SavedScenarioError as exc:
        raise ScenarioDraftError("scenario_domain_rejected", str(exc)) from exc
    return ScenarioDraft(spec=spec, conversion=snapshot.conversion)


def draft_database_error_message() -> str:
    return "Saved scenarios are temporarily unavailable. Your calculated result was not changed."


__all__ = [
    "DatabaseError",
    "ScenarioDraft",
    "ScenarioDraftError",
    "build_budget_scenario_draft",
    "build_shopping_scenario_draft",
    "draft_database_error_message",
]
