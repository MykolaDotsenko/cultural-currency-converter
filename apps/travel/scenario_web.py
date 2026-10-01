from __future__ import annotations

import logging
from decimal import Decimal
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import DatabaseError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from apps.countries.models import City, Country, Currency
from apps.exchange.budget import BudgetAssumptions
from apps.exchange.budget_snapshot import (
    BudgetContextTokenError,
    load_budget_context_snapshot_token,
)
from apps.exchange.config import FxConfigurationError
from apps.exchange.domain import FxDomainError
from apps.exchange.forms import BudgetInterpretationForm
from apps.exchange.providers.base import FxProviderError
from apps.exchange.services import quote_conversion
from apps.exchange.web.gateways import build_latest_quote_gateway
from apps.travel.models import (
    SavedScenario,
    SavedScenarioKind,
    SavedScenarioObservationKind,
)
from apps.travel.scenario_comparison import (
    ScenarioRateDirection,
    compare_scenario_observations,
)
from apps.travel.scenarios import (
    SavedScenarioError,
    SavedScenarioSpec,
    create_saved_scenario,
    record_scenario_recheck,
)

logger = logging.getLogger("cultural_currency.travel")


def _decimal_input_text(value) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _scenario_converter_url(scenario: SavedScenario) -> str:
    params = {
        "convert": "1",
        "amount": _decimal_input_text(scenario.source_amount),
        "source_currency": scenario.source_currency.code,
        "destination_currency": scenario.destination_currency.code,
    }
    if scenario.source_country is not None:
        params["source_country"] = scenario.source_country.iso2
    if scenario.destination_country is not None:
        params["destination_country"] = scenario.destination_country.iso2
    return f"{reverse('converter')}?{urlencode(params)}"


def _signed_decimal_text(value: Decimal) -> str:
    text = _decimal_input_text(value)
    if value > 0:
        return f"+{text}"
    return text


def _scenario_rate_comparison_component(
    scenario: SavedScenario,
    *,
    initial_observation,
    latest_observation,
) -> dict[str, object] | None:
    if (
        initial_observation is None
        or latest_observation is None
        or initial_observation.pk == latest_observation.pk
    ):
        return None

    comparison = compare_scenario_observations(initial_observation, latest_observation)
    if comparison.direction is ScenarioRateDirection.HIGHER:
        difference_phrase = (
            f"{_decimal_input_text(abs(comparison.output_amount_difference))} "
            f"{scenario.destination_currency.code} more"
        )
    elif comparison.direction is ScenarioRateDirection.LOWER:
        difference_phrase = (
            f"{_decimal_input_text(abs(comparison.output_amount_difference))} "
            f"{scenario.destination_currency.code} less"
        )
    else:
        difference_phrase = f"no change in {scenario.destination_currency.code} output"

    return {
        "difference_phrase": difference_phrase,
        "rate_change_percent": _signed_decimal_text(comparison.rate_difference_percent),
        "initial_output": _decimal_input_text(initial_observation.output_amount),
        "latest_output": _decimal_input_text(latest_observation.output_amount),
        "initial_effective_date": initial_observation.effective_date,
        "latest_effective_date": latest_observation.effective_date,
        "changed": comparison.changed,
    }


def _scenario_default_title(
    *,
    destination_country: Country,
    destination_city: City | None,
) -> str:
    destination_name = (
        destination_city.name if destination_city is not None else destination_country.name
    )
    return f"{destination_name} budget"


@login_required
@require_POST
def save_budget_scenario(request: HttpRequest) -> HttpResponse:
    token = request.POST.get("budget_context_token", "")
    try:
        snapshot = load_budget_context_snapshot_token(token)
    except BudgetContextTokenError:
        messages.error(
            request,
            "This budget context is no longer valid. Run the conversion again before saving.",
        )
        return redirect("converter")

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
    except (Currency.DoesNotExist, Country.DoesNotExist, City.DoesNotExist):
        messages.error(
            request,
            "The saved destination metadata is no longer available. Run the conversion again.",
        )
        return redirect("converter")
    except DatabaseError:
        messages.error(
            request,
            "Saved scenarios are temporarily unavailable. Your conversion was not changed.",
        )
        return redirect("converter")

    # The signed snapshot already establishes the trusted conversion and
    # destination scope. Re-validate only the explicit user assumptions here;
    # saving must not depend on a second live local-price lookup.
    form = BudgetInterpretationForm(request.POST, category_options=())
    if not form.is_valid():
        messages.error(
            request,
            "The budget assumptions changed or are invalid. Interpret the budget again before saving.",
        )
        return redirect("converter")

    assumptions = form.cleaned_data.get("budget_assumptions")
    if not isinstance(assumptions, BudgetAssumptions):
        raise RuntimeError("Valid budget scenario form returned no BudgetAssumptions.")

    raw_title = str(request.POST.get("title", "")).strip()
    title = raw_title or _scenario_default_title(
        destination_country=destination_country,
        destination_city=destination_city,
    )

    spec = SavedScenarioSpec(
        kind=SavedScenarioKind.BUDGET,
        title=title,
        source_currency=source_currency,
        destination_currency=destination_currency,
        source_country=None,
        destination_country=destination_country,
        destination_city=destination_city,
        source_amount=snapshot.conversion.input_amount,
        duration_days=assumptions.duration_days,
        travelers=assumptions.travelers,
        budget_categories=assumptions.categories,
    )

    try:
        scenario = create_saved_scenario(
            request.user,
            spec=spec,
            conversion=snapshot.conversion,
        )
    except SavedScenarioError as exc:
        messages.error(request, f"Could not save this budget: {exc}")
        return redirect("converter")
    except DatabaseError:
        messages.error(
            request,
            "Saved scenarios are temporarily unavailable. Your conversion was not changed.",
        )
        return redirect("converter")

    messages.success(request, "Budget saved to your account.")
    return redirect("saved_scenario_detail", scenario_id=scenario.pk)


@login_required
@never_cache
@require_GET
def saved_scenario_detail(request: HttpRequest, scenario_id: int) -> HttpResponse:
    scenario = get_object_or_404(
        SavedScenario.objects.select_related(
            "source_currency",
            "destination_currency",
            "source_country",
            "destination_country",
            "destination_city",
        ).prefetch_related("budget_items"),
        pk=scenario_id,
        user=request.user,
    )
    initial_observation = (
        scenario.observations.filter(kind=SavedScenarioObservationKind.INITIAL)
        .order_by("recorded_at", "id")
        .first()
    )
    latest_observation = scenario.observations.order_by("-recorded_at", "-id").first()

    budget_item_rows = tuple(
        {
            "item": item,
            "label": item.category.replace("_", " ").title(),
        }
        for item in scenario.budget_items.all()
    )
    rate_comparison = _scenario_rate_comparison_component(
        scenario,
        initial_observation=initial_observation,
        latest_observation=latest_observation,
    )

    return render(
        request,
        "travel/saved_scenario_detail.html",
        {
            "scenario": scenario,
            "budget_item_rows": budget_item_rows,
            "initial_observation": initial_observation,
            "latest_observation": latest_observation,
            "rate_comparison": rate_comparison,
            "converter_url": _scenario_converter_url(scenario),
        },
    )


@login_required
@require_POST
def recheck_saved_scenario(request: HttpRequest, scenario_id: int) -> HttpResponse:
    scenario = get_object_or_404(
        SavedScenario.objects.select_related(
            "source_currency",
            "destination_currency",
        ),
        pk=scenario_id,
        user=request.user,
    )
    latest_before = scenario.observations.order_by("-recorded_at", "-id").first()

    try:
        gateway = build_latest_quote_gateway()
        conversion = quote_conversion(
            amount=scenario.source_amount,
            base_currency=scenario.source_currency.code,
            quote_currency=scenario.destination_currency.code,
            quote_minor_units=scenario.destination_currency.minor_units,
            gateway=gateway,
        )
    except FxConfigurationError:
        logger.exception(
            "saved_scenario_recheck_fx_configuration_error",
            extra={"scenario_id": scenario.pk},
        )
        messages.error(
            request,
            "The latest reference rate is temporarily unavailable. Your saved observation was not changed.",
        )
        return redirect("saved_scenario_detail", scenario_id=scenario.pk)
    except (FxProviderError, FxDomainError) as exc:
        logger.warning(
            "saved_scenario_recheck_fx_unavailable",
            extra={
                "scenario_id": scenario.pk,
                "error_code": exc.__class__.__name__,
            },
        )
        messages.error(
            request,
            "The latest reference rate is temporarily unavailable. Your saved observation was not changed.",
        )
        return redirect("saved_scenario_detail", scenario_id=scenario.pk)

    try:
        observation = record_scenario_recheck(scenario, conversion=conversion)
    except SavedScenarioError as exc:
        messages.error(request, f"Could not re-check this scenario: {exc}")
        return redirect("saved_scenario_detail", scenario_id=scenario.pk)
    except DatabaseError:
        logger.exception(
            "saved_scenario_recheck_persistence_unavailable",
            extra={"scenario_id": scenario.pk},
        )
        messages.error(
            request,
            "The latest rate was retrieved, but the re-check could not be saved. Your existing observations were not changed.",
        )
        return redirect("saved_scenario_detail", scenario_id=scenario.pk)

    if latest_before is not None and observation.pk == latest_before.pk:
        messages.info(
            request,
            "The latest available reference matches the most recent stored observation.",
        )
    else:
        messages.success(
            request,
            "Reference rate re-checked. The original saved observation remains unchanged.",
        )
    return redirect("saved_scenario_detail", scenario_id=scenario.pk)


@login_required
@require_POST
def delete_saved_scenario(request: HttpRequest, scenario_id: int) -> HttpResponse:
    scenario = get_object_or_404(
        SavedScenario,
        pk=scenario_id,
        user=request.user,
    )
    scenario.delete()
    messages.success(request, "Saved scenario removed from your account.")
    return redirect("saved_state")
