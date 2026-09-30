from __future__ import annotations

from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import DatabaseError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from apps.countries.models import City, Country, Currency
from apps.exchange.budget import BudgetAssumptions, available_budget_categories
from apps.exchange.budget_snapshot import (
    BudgetContextTokenError,
    load_budget_context_snapshot_token,
)
from apps.exchange.forms import BudgetInterpretationForm
from apps.exchange.money_context import MoneyContextState, build_money_context
from apps.travel.models import SavedScenario, SavedScenarioKind
from apps.travel.scenarios import (
    SavedScenarioError,
    SavedScenarioSpec,
    create_saved_scenario,
)


def _scenario_converter_url(scenario: SavedScenario) -> str:
    params = {
        "convert": "1",
        "amount": format(scenario.source_amount, "f").rstrip("0").rstrip(".") or "0",
        "source_currency": scenario.source_currency.code,
        "destination_currency": scenario.destination_currency.code,
    }
    if scenario.source_country is not None:
        params["source_country"] = scenario.source_country.iso2
    if scenario.destination_country is not None:
        params["destination_country"] = scenario.destination_country.iso2
    return f"{reverse('converter')}?{urlencode(params)}"


def _scenario_default_title(
    *,
    destination_country: Country,
    destination_city: City | None,
) -> str:
    destination_name = destination_city.name if destination_city is not None else destination_country.name
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

    money_context = build_money_context(
        conversion=snapshot.conversion,
        destination_country_code=destination_country.iso2,
        destination_city_slug=destination_city.slug if destination_city is not None else "",
        as_of=snapshot.as_of,
        price_limit=6,
    )
    if money_context.destination_state is MoneyContextState.DEGRADED:
        messages.error(
            request,
            "Current destination context could not be verified, so this budget was not saved.",
        )
        return redirect("converter")

    anchors = available_budget_categories(money_context)
    category_options = tuple((anchor.category, anchor.label) for anchor in anchors)
    if not category_options:
        messages.error(
            request,
            "There is not enough current local-price context to save this budget.",
        )
        return redirect("converter")

    form = BudgetInterpretationForm(request.POST, category_options=category_options)
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
    except (SavedScenarioError, DatabaseError) as exc:
        messages.error(request, f"Could not save this budget: {exc}")
        return redirect("converter")

    messages.success(request, "Budget saved to your account.")
    return redirect("saved_scenario_detail", scenario_id=scenario.pk)


@login_required
@require_GET
def saved_scenario_detail(request: HttpRequest, scenario_id: int) -> HttpResponse:
    scenario = get_object_or_404(
        SavedScenario.objects.select_related(
            "source_currency",
            "destination_currency",
            "source_country",
            "destination_country",
            "destination_city",
        ).prefetch_related("budget_items", "observations"),
        pk=scenario_id,
        user=request.user,
    )
    observations = tuple(scenario.observations.all())
    initial_observation = next(
        (item for item in reversed(observations) if item.kind == "initial"),
        None,
    )
    latest_observation = observations[0] if observations else None

    return render(
        request,
        "travel/saved_scenario_detail.html",
        {
            "scenario": scenario,
            "budget_items": tuple(scenario.budget_items.all()),
            "initial_observation": initial_observation,
            "latest_observation": latest_observation,
            "converter_url": _scenario_converter_url(scenario),
        },
    )


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
