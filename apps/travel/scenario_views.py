from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import DatabaseError
from django.http import HttpRequest, HttpResponse, QueryDict
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from apps.countries.models import City, Country, Currency
from apps.exchange.budget import BudgetAssumptions, available_budget_categories
from apps.exchange.budget_snapshot import (
    BudgetContextTokenError,
    TrustedBudgetContextSnapshot,
    load_budget_context_snapshot_token,
)
from apps.exchange.forms import BudgetInterpretationForm
from apps.exchange.money_context import MoneyContextState, build_money_context
from apps.travel.forms import SavedScenarioCreateForm
from apps.travel.models import (
    SavedScenario,
    SavedScenarioKind,
    SavedScenarioObservationKind,
)
from apps.travel.scenario_snapshot import (
    SavedScenarioDraft,
    SavedScenarioDraftTokenError,
    build_saved_scenario_draft_token,
    load_saved_scenario_draft_token,
)
from apps.travel.scenarios import (
    SavedScenarioError,
    SavedScenarioSpec,
    create_saved_scenario,
)

logger = logging.getLogger("cultural_currency.travel")


class SavedScenarioFlowError(ValueError):
    """Raised when trusted scenario handoff data can no longer be resolved."""


@dataclass(frozen=True, slots=True)
class ScenarioReference:
    source_currency: Currency
    destination_currency: Currency
    destination_country: Country
    destination_city: City | None


def _scenario_reference(snapshot: TrustedBudgetContextSnapshot) -> ScenarioReference:
    currencies = Currency.objects.in_bulk(
        {
            snapshot.conversion.quote.base_currency,
            snapshot.conversion.quote.quote_currency,
        },
        field_name="code",
    )
    source_currency = currencies.get(snapshot.conversion.quote.base_currency)
    destination_currency = currencies.get(snapshot.conversion.quote.quote_currency)
    if source_currency is None or destination_currency is None:
        raise SavedScenarioFlowError("Currency metadata for this saved plan is unavailable.")

    if not snapshot.destination_country_code:
        raise SavedScenarioFlowError("Saved travel plans require a destination country.")
    destination_country = (
        Country.objects.filter(
            iso2=snapshot.destination_country_code,
            is_active=True,
        )
        .only("id", "iso2", "name")
        .first()
    )
    if destination_country is None:
        raise SavedScenarioFlowError("Destination metadata for this saved plan is unavailable.")

    destination_city = None
    if snapshot.destination_city_slug:
        destination_city = (
            City.objects.filter(
                country=destination_country,
                slug=snapshot.destination_city_slug,
                is_active=True,
            )
            .only("id", "country_id", "slug", "name")
            .first()
        )
        if destination_city is None:
            raise SavedScenarioFlowError("Destination city for this saved plan is unavailable.")

    return ScenarioReference(
        source_currency=source_currency,
        destination_currency=destination_currency,
        destination_country=destination_country,
        destination_city=destination_city,
    )


def _prepare_error(
    request: HttpRequest,
    *,
    title: str,
    detail: str,
    status: int,
) -> HttpResponse:
    return render(
        request,
        "travel/scenario_prepare.html",
        {
            "scenario_error": {"title": title, "detail": detail},
            "scenario_form": None,
            "scenario_draft_token": "",
            "scenario_summary": None,
        },
        status=status,
    )


def _draft_summary(
    snapshot: TrustedBudgetContextSnapshot,
    reference: ScenarioReference,
    assumptions: BudgetAssumptions,
) -> dict[str, object]:
    destination_name = reference.destination_country.name
    if reference.destination_city is not None:
        destination_name = f"{reference.destination_city.name}, {destination_name}"

    return {
        "source_amount": format(snapshot.conversion.input_amount, "f"),
        "source_currency": reference.source_currency.code,
        "destination_amount": format(snapshot.conversion.output_amount, "f"),
        "destination_currency": reference.destination_currency.code,
        "destination_name": destination_name,
        "effective_date": snapshot.conversion.quote.effective_date,
        "duration_days": assumptions.duration_days,
        "travelers": assumptions.travelers,
        "categories": tuple(
            {
                "category": item.category.replace("_", " ").title(),
                "units": format(item.units_per_person_per_day, "f").rstrip("0").rstrip("."),
            }
            for item in assumptions.categories
        ),
    }


def _validate_budget_handoff(
    token: str,
    data: QueryDict,
) -> tuple[TrustedBudgetContextSnapshot, ScenarioReference, BudgetAssumptions]:
    try:
        snapshot = load_budget_context_snapshot_token(token)
    except BudgetContextTokenError as exc:
        raise SavedScenarioFlowError(
            "This budget plan is no longer valid. Reopen it from the converter."
        ) from exc

    reference = _scenario_reference(snapshot)
    money_context = build_money_context(
        conversion=snapshot.conversion,
        destination_country_code=snapshot.destination_country_code,
        destination_city_slug=snapshot.destination_city_slug,
        as_of=snapshot.as_of,
        price_limit=6,
    )
    if money_context.destination_state is MoneyContextState.DEGRADED:
        raise SavedScenarioFlowError(
            "Current local-price context is temporarily unavailable. Try saving again later."
        )

    anchors = available_budget_categories(money_context)
    if not anchors:
        raise SavedScenarioFlowError(
            "There is not enough current sourced price context to save this budget plan."
        )

    category_options = tuple((anchor.category, anchor.label) for anchor in anchors)
    budget_form = BudgetInterpretationForm(data, category_options=category_options)
    if not budget_form.is_valid():
        raise SavedScenarioFlowError(
            "The budget assumptions are no longer valid. "
            "Reopen the budget interpretation and review them."
        )

    assumptions = budget_form.cleaned_data.get("budget_assumptions")
    if not isinstance(assumptions, BudgetAssumptions):
        raise RuntimeError("Valid budget form returned no BudgetAssumptions.")
    return snapshot, reference, assumptions


@login_required
@require_POST
def prepare_saved_scenario(request: HttpRequest) -> HttpResponse:
    token = request.POST.get("budget_context_token", "")
    try:
        snapshot, reference, assumptions = _validate_budget_handoff(token, request.POST)
        draft_token = build_saved_scenario_draft_token(
            budget_context_token=token,
            assumptions=assumptions,
        )
    except (SavedScenarioFlowError, SavedScenarioDraftTokenError) as exc:
        return _prepare_error(
            request,
            title="This plan could not be prepared for saving.",
            detail=str(exc),
            status=422,
        )
    except DatabaseError as exc:
        logger.warning(
            "saved_scenario_prepare_database_unavailable",
            extra={"error_code": exc.__class__.__name__},
        )
        return _prepare_error(
            request,
            title="Saved plans are temporarily unavailable.",
            detail="Your conversion remains valid. Try saving this plan again in a moment.",
            status=503,
        )

    initial_title = (
        f"{reference.destination_city.name} trip"
        if reference.destination_city is not None
        else f"{reference.destination_country.name} trip"
    )
    form = SavedScenarioCreateForm(
        initial={
            "kind": SavedScenarioKind.TRIP,
            "title": initial_title,
        }
    )
    return render(
        request,
        "travel/scenario_prepare.html",
        {
            "scenario_error": None,
            "scenario_form": form,
            "scenario_draft_token": draft_token,
            "scenario_summary": _draft_summary(snapshot, reference, assumptions),
        },
    )


def _render_create_form(
    request: HttpRequest,
    *,
    draft_token: str,
    draft: SavedScenarioDraft,
    snapshot: TrustedBudgetContextSnapshot,
    reference: ScenarioReference,
    form: SavedScenarioCreateForm,
    status: int,
) -> HttpResponse:
    return render(
        request,
        "travel/scenario_prepare.html",
        {
            "scenario_error": None,
            "scenario_form": form,
            "scenario_draft_token": draft_token,
            "scenario_summary": _draft_summary(snapshot, reference, draft.assumptions),
        },
        status=status,
    )


@login_required
@require_POST
def create_saved_scenario_view(request: HttpRequest) -> HttpResponse:
    draft_token = request.POST.get("scenario_draft_token", "")
    try:
        draft = load_saved_scenario_draft_token(draft_token)
        snapshot = load_budget_context_snapshot_token(draft.budget_context_token)
        reference = _scenario_reference(snapshot)
    except (SavedScenarioDraftTokenError, BudgetContextTokenError, SavedScenarioFlowError) as exc:
        return _prepare_error(
            request,
            title="This saved-plan request is no longer valid.",
            detail=str(exc),
            status=422,
        )
    except DatabaseError as exc:
        logger.warning(
            "saved_scenario_create_database_unavailable",
            extra={"error_code": exc.__class__.__name__},
        )
        return _prepare_error(
            request,
            title="Saved plans are temporarily unavailable.",
            detail="No plan was saved. Try again in a moment.",
            status=503,
        )

    form = SavedScenarioCreateForm(request.POST)
    if not form.is_valid():
        return _render_create_form(
            request,
            draft_token=draft_token,
            draft=draft,
            snapshot=snapshot,
            reference=reference,
            form=form,
            status=422,
        )

    try:
        kind = SavedScenarioKind(form.cleaned_data["kind"])
        spec = SavedScenarioSpec(
            kind=kind,
            title=form.cleaned_data["title"],
            source_currency=reference.source_currency,
            destination_currency=reference.destination_currency,
            source_country=None,
            destination_country=reference.destination_country,
            destination_city=reference.destination_city,
            source_amount=snapshot.conversion.input_amount,
            duration_days=draft.assumptions.duration_days,
            travelers=draft.assumptions.travelers,
            travel_start_date=form.cleaned_data.get("travel_start_date"),
            travel_end_date=form.cleaned_data.get("travel_end_date"),
            budget_categories=draft.assumptions.categories,
        )
        scenario = create_saved_scenario(
            request.user,
            spec=spec,
            conversion=snapshot.conversion,
        )
    except SavedScenarioError as exc:
        form.add_error(None, str(exc))
        return _render_create_form(
            request,
            draft_token=draft_token,
            draft=draft,
            snapshot=snapshot,
            reference=reference,
            form=form,
            status=422,
        )
    except DatabaseError as exc:
        logger.warning(
            "saved_scenario_create_database_write_failed",
            extra={"error_code": exc.__class__.__name__},
        )
        return _prepare_error(
            request,
            title="Saved plans are temporarily unavailable.",
            detail="No plan was saved. Try again in a moment.",
            status=503,
        )

    messages.success(request, "Plan saved to your account.")
    return redirect("saved_scenario_detail", scenario_id=scenario.pk)


def _decimal_url_text(value) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _scenario_converter_url(scenario: SavedScenario) -> str:
    params = {
        "convert": "1",
        "amount": _decimal_url_text(scenario.source_amount),
        "source_currency": scenario.source_currency.code,
        "destination_currency": scenario.destination_currency.code,
    }
    if scenario.source_country is not None:
        params["source_country"] = scenario.source_country.iso2
    if scenario.destination_country is not None:
        params["destination_country"] = scenario.destination_country.iso2
    return f"{reverse('converter')}?{urlencode(params)}"


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
    observations = list(scenario.observations.all())
    initial_observation = next(
        (
            item
            for item in reversed(observations)
            if item.kind == SavedScenarioObservationKind.INITIAL
        ),
        None,
    )
    latest_observation = observations[0] if observations else None

    budget_rows = tuple(
        {
            "item": item,
            "label": item.category.replace("_", " ").title(),
        }
        for item in scenario.budget_items.all()
    )
    has_later_observation = (
        initial_observation is not None
        and latest_observation is not None
        and latest_observation.pk != initial_observation.pk
    )

    return render(
        request,
        "travel/scenario_detail.html",
        {
            "scenario": scenario,
            "initial_observation": initial_observation,
            "latest_observation": latest_observation,
            "has_later_observation": has_later_observation,
            "budget_rows": budget_rows,
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
    messages.success(request, "Saved plan removed from your account.")
    return redirect("saved_state")
