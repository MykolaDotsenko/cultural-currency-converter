from __future__ import annotations

import logging
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation, localcontext
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import DatabaseError
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
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
from apps.travel.forms import SavedScenarioPlanningForm, SavedScenarioSpendForm
from apps.travel.models import (
    SavedScenario,
    SavedScenarioKind,
    SavedScenarioObservationKind,
    SavedScenarioSpendEntry,
)
from apps.travel.scenario_comparison import (
    ScenarioRateDirection,
    compare_scenario_observations,
)
from apps.travel.scenario_schedule import TripScheduleState, evaluate_trip_schedule
from apps.travel.scenarios import (
    SavedScenarioError,
    SavedScenarioSpec,
    create_saved_scenario,
    record_scenario_recheck,
    record_scenario_spend,
)
from apps.travel.trip_budget import (
    TripBudgetDayBasis,
    calculate_trip_budget_summary,
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
    if scenario.destination_city is not None:
        params["destination_city_slug"] = scenario.destination_city.slug
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


def _scenario_schedule_component(
    scenario: SavedScenario,
    *,
    as_of: date,
) -> dict[str, object] | None:
    try:
        schedule = evaluate_trip_schedule(
            start_date=scenario.travel_start_date,
            end_date=scenario.travel_end_date,
            as_of=as_of,
        )
    except ValueError:
        logger.warning(
            "saved_scenario_schedule_invalid",
            extra={"scenario_id": scenario.pk},
        )
        return None

    if schedule.state is TripScheduleState.UNSCHEDULED:
        return None

    if schedule.state is TripScheduleState.UPCOMING:
        days = schedule.days_until_start or 0
        headline = "Starts tomorrow" if days == 1 else f"Starts in {days} days"
        if days <= 7:
            detail = (
                "Departure is close. A reference-rate re-check can update the comparison "
                "without changing your original saved baseline."
            )
        elif days <= 30:
            detail = (
                "This trip is coming up. Re-check the reference rate whenever you want a "
                "new comparison against the original saved observation."
            )
        else:
            detail = (
                "The travel window is saved. Nothing refreshes automatically; the original "
                "FX observation remains your baseline until you choose to re-check."
            )
    elif schedule.state is TripScheduleState.ACTIVE:
        headline = "Travel window is active"
        detail = (
            "Use this plan as a reference during the saved travel window. Rate re-checks stay "
            "explicit and never overwrite the original observation."
        )
    elif schedule.state is TripScheduleState.STARTED:
        headline = "Trip start date reached"
        detail = (
            "No end date was saved, so the product does not assume whether travel is still active."
        )
    else:
        headline = "Travel window ended"
        detail = (
            "This scenario remains available as a planning record. Rates and local-price context "
            "are not silently refreshed after the trip."
        )

    return {
        "state": schedule.state,
        "headline": headline,
        "detail": detail,
        "start_date": schedule.start_date,
        "end_date": schedule.end_date,
        "days_until_start": schedule.days_until_start,
        "days_since_end": schedule.days_since_end,
    }


def _format_currency_amount(value: Decimal, *, minor_units: int) -> str:
    if not 0 <= minor_units <= 6:
        raise ValueError("Currency minor units must be between 0 and 6.")

    quantum = Decimal(1).scaleb(-minor_units)
    try:
        with localcontext() as context:
            context.prec = max(64, len(value.as_tuple().digits) + minor_units + 8)
            rounded = value.quantize(quantum, rounding=ROUND_HALF_EVEN)
    except InvalidOperation as exc:
        raise ValueError("Currency amount cannot be represented for display.") from exc
    return format(rounded, f".{minor_units}f") if minor_units else format(rounded, "f")


def _scenario_trip_budget_component(
    scenario: SavedScenario,
    *,
    initial_observation,
    spend_entries: tuple[SavedScenarioSpendEntry, ...],
    as_of: date,
) -> dict[str, object] | None:
    if scenario.kind != SavedScenarioKind.BUDGET or initial_observation is None:
        return None

    confirmed_spend = sum((entry.amount for entry in spend_entries), Decimal("0"))
    try:
        summary = calculate_trip_budget_summary(
            reference_budget=initial_observation.output_amount,
            confirmed_spend=confirmed_spend,
            duration_days=scenario.duration_days,
            travel_start_date=scenario.travel_start_date,
            travel_end_date=scenario.travel_end_date,
            as_of=as_of,
        )
    except ValueError:
        logger.warning(
            "saved_scenario_trip_budget_invalid",
            extra={"scenario_id": scenario.pk},
        )
        return None

    minor_units = scenario.destination_currency.minor_units
    day_label = ""
    if summary.day_basis is TripBudgetDayBasis.SCHEDULE:
        if scenario.travel_start_date is not None and as_of < scenario.travel_start_date:
            day_label = "per trip day"
        else:
            day_label = "per remaining trip day"
    elif summary.day_basis is TripBudgetDayBasis.PLAN:
        day_label = "per planned day"

    return {
        "reference_budget": _format_currency_amount(
            summary.reference_budget,
            minor_units=minor_units,
        ),
        "confirmed_spend": _format_currency_amount(
            summary.confirmed_spend,
            minor_units=minor_units,
        ),
        "remaining": _format_currency_amount(
            summary.remaining,
            minor_units=minor_units,
        ),
        "over_reference": _format_currency_amount(
            summary.over_reference,
            minor_units=minor_units,
        ),
        "is_over_reference": summary.is_over_reference,
        "days": summary.days,
        "day_label": day_label,
        "remaining_per_day": (
            _format_currency_amount(
                summary.remaining_per_day,
                minor_units=minor_units,
            )
            if summary.remaining_per_day is not None
            else None
        ),
    }


def _scenario_detail_context(
    scenario: SavedScenario,
    *,
    spend_form: SavedScenarioSpendForm | None = None,
) -> dict[str, object]:
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
    spend_entries = tuple(scenario.spend_entries.all())
    as_of = timezone.localdate()
    rate_comparison = _scenario_rate_comparison_component(
        scenario,
        initial_observation=initial_observation,
        latest_observation=latest_observation,
    )
    trip_schedule = _scenario_schedule_component(
        scenario,
        as_of=as_of,
    )
    trip_budget = _scenario_trip_budget_component(
        scenario,
        initial_observation=initial_observation,
        spend_entries=spend_entries,
        as_of=as_of,
    )
    if spend_form is None:
        spend_form = SavedScenarioSpendForm(
            destination_currency_code=scenario.destination_currency.code,
            destination_minor_units=scenario.destination_currency.minor_units,
        )

    return {
        "scenario": scenario,
        "budget_item_rows": budget_item_rows,
        "initial_observation": initial_observation,
        "latest_observation": latest_observation,
        "rate_comparison": rate_comparison,
        "trip_schedule": trip_schedule,
        "trip_budget": trip_budget,
        "spend_entries": spend_entries,
        "spend_form": spend_form,
        "converter_url": _scenario_converter_url(scenario),
    }


def _owned_scenario_for_detail(request: HttpRequest, scenario_id: int) -> SavedScenario:
    return get_object_or_404(
        SavedScenario.objects.select_related(
            "source_currency",
            "destination_currency",
            "source_country",
            "destination_country",
            "destination_city",
        ).prefetch_related("budget_items", "spend_entries"),
        pk=scenario_id,
        user=request.user,
    )


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

    planning_form = SavedScenarioPlanningForm(request.POST)
    if not planning_form.is_valid():
        first_error = next(
            (str(message) for errors in planning_form.errors.values() for message in errors),
            "The saved trip details are invalid.",
        )
        messages.error(request, f"Could not save trip timing: {first_error}")
        return redirect("converter")

    raw_title = str(planning_form.cleaned_data.get("title") or "")
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
        travel_start_date=planning_form.cleaned_data.get("travel_start_date"),
        travel_end_date=planning_form.cleaned_data.get("travel_end_date"),
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
    scenario = _owned_scenario_for_detail(request, scenario_id)
    return render(
        request,
        "travel/saved_scenario_detail.html",
        _scenario_detail_context(scenario),
    )


@login_required
@never_cache
@require_POST
def add_saved_scenario_spend(request: HttpRequest, scenario_id: int) -> HttpResponse:
    scenario = _owned_scenario_for_detail(request, scenario_id)
    if scenario.kind != SavedScenarioKind.BUDGET:
        raise Http404("Confirmed spend is available only for saved budget scenarios.")

    form = SavedScenarioSpendForm(
        request.POST,
        destination_currency_code=scenario.destination_currency.code,
        destination_minor_units=scenario.destination_currency.minor_units,
    )
    if not form.is_valid():
        return render(
            request,
            "travel/saved_scenario_detail.html",
            _scenario_detail_context(scenario, spend_form=form),
            status=422,
        )

    amount = form.cleaned_data.get("amount_decimal")
    if not isinstance(amount, Decimal):
        raise RuntimeError("Valid spend form returned no Decimal amount.")

    try:
        record_scenario_spend(scenario, amount=amount)
    except SavedScenarioError as exc:
        messages.error(request, f"Could not add confirmed spend: {exc}")
        return redirect("saved_scenario_detail", scenario_id=scenario.pk)
    except DatabaseError:
        logger.exception(
            "saved_scenario_spend_persistence_unavailable",
            extra={"scenario_id": scenario.pk},
        )
        messages.error(
            request,
            "Confirmed spend is temporarily unavailable. Your saved budget was not changed.",
        )
        return redirect("saved_scenario_detail", scenario_id=scenario.pk)

    messages.success(request, "Confirmed spend added to this saved budget.")
    return redirect("saved_scenario_detail", scenario_id=scenario.pk)


@login_required
@require_POST
def delete_saved_scenario_spend(
    request: HttpRequest,
    scenario_id: int,
    entry_id: int,
) -> HttpResponse:
    entry = get_object_or_404(
        SavedScenarioSpendEntry.objects.select_related("scenario"),
        pk=entry_id,
        scenario_id=scenario_id,
        scenario__user=request.user,
    )
    scenario = entry.scenario
    scenario_id_value = entry.scenario_id
    entry.delete()
    scenario.save(update_fields=("updated_at",))
    messages.success(request, "Confirmed spend entry removed.")
    return redirect("saved_scenario_detail", scenario_id=scenario_id_value)


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
