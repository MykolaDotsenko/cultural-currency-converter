from __future__ import annotations

import logging
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal, DecimalException, InvalidOperation, localcontext
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist
from django.db import DatabaseError, transaction
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from apps.culture.presentation import build_destination_context_component
from apps.culture.services import build_destination_context
from apps.exchange.config import FxConfigurationError
from apps.exchange.domain import FxDomainError
from apps.exchange.providers.base import FxProviderError
from apps.exchange.services import quote_conversion
from apps.exchange.shopping import SHOPPING_UNKNOWN_COSTS, shopping_home_costs
from apps.exchange.web.gateways import build_latest_quote_gateway
from apps.travel.forms import SavedScenarioSpendForm
from apps.travel.models import (
    SavedScenario,
    SavedScenarioBudgetBasis,
    SavedScenarioKind,
    SavedScenarioObservationKind,
    SavedScenarioSpendEntry,
    ScenarioNotificationCadence,
    ScenarioNotificationType,
)
from apps.travel.notification_preferences import notification_preferences_for_scenario
from apps.travel.offline_snapshot import build_offline_snapshot_revision
from apps.travel.scenario_comparison import (
    ScenarioRateDirection,
    compare_scenario_observations,
)
from apps.travel.scenario_drafts import (
    ScenarioDraftError,
    build_budget_scenario_draft,
    build_shopping_scenario_draft,
)
from apps.travel.scenario_schedule import TripScheduleState, evaluate_trip_schedule
from apps.travel.scenarios import (
    SavedScenarioError,
    create_saved_scenario,
    record_scenario_recheck,
    record_scenario_spend,
)
from apps.travel.share_snapshot import ScenarioShareTokenError, build_scenario_share_token
from apps.travel.trip_budget import (
    TripBudgetDayBasis,
    calculate_trip_budget_summary,
    resolve_trip_budget_reference,
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


def _scenario_reopen_url(scenario: SavedScenario) -> str:
    if scenario.kind != SavedScenarioKind.SHOPPING:
        return _scenario_converter_url(scenario)

    try:
        shopping = scenario.shopping_assumptions
    except ObjectDoesNotExist:
        return reverse("shopping_calculation")

    params = {
        "purchase_country": scenario.source_country.iso2 if scenario.source_country else "",
        "purchase_currency": scenario.source_currency.code,
        "home_currency": scenario.destination_currency.code,
        "item_price": _decimal_input_text(shopping.item_price),
        "shipping": _decimal_input_text(shopping.shipping),
        "known_fees": _decimal_input_text(shopping.known_fees),
        "fx_markup_percent": _decimal_input_text(shopping.fx_markup_percent),
    }
    return f"{reverse('shopping_calculation')}?{urlencode(params)}"


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


def _scenario_shopping_component(
    scenario: SavedScenario,
    *,
    initial_observation,
) -> dict[str, object] | None:
    if scenario.kind != SavedScenarioKind.SHOPPING or initial_observation is None:
        return None

    try:
        shopping = scenario.shopping_assumptions
    except ObjectDoesNotExist:
        logger.warning(
            "saved_shopping_scenario_payload_missing",
            extra={"scenario_id": scenario.pk},
        )
        return None

    try:
        reference, estimated, markup_cost = shopping_home_costs(
            reference_home_cost=initial_observation.output_amount,
            fx_markup_percent=shopping.fx_markup_percent,
            home_minor_units=scenario.destination_currency.minor_units,
        )
    except ValueError:
        logger.warning(
            "saved_shopping_scenario_payload_invalid",
            extra={"scenario_id": scenario.pk},
        )
        return None

    source_minor_units = scenario.source_currency.minor_units
    destination_minor_units = scenario.destination_currency.minor_units
    return {
        "item_price": _format_currency_amount(
            shopping.item_price,
            minor_units=source_minor_units,
        ),
        "shipping": _format_currency_amount(
            shopping.shipping,
            minor_units=source_minor_units,
        ),
        "known_fees": _format_currency_amount(
            shopping.known_fees,
            minor_units=source_minor_units,
        ),
        "purchase_total": _format_currency_amount(
            scenario.source_amount,
            minor_units=source_minor_units,
        ),
        "fx_markup_percent": _decimal_input_text(shopping.fx_markup_percent),
        "reference_home_cost": _format_currency_amount(
            reference,
            minor_units=destination_minor_units,
        ),
        "estimated_home_cost": _format_currency_amount(
            estimated,
            minor_units=destination_minor_units,
        ),
        "fx_markup_cost": _format_currency_amount(
            markup_cost,
            minor_units=destination_minor_units,
        ),
        "unknown_costs": SHOPPING_UNKNOWN_COSTS,
    }


def _scenario_trip_budget_component(
    scenario: SavedScenario,
    *,
    initial_observation,
    spend_entries: tuple[SavedScenarioSpendEntry, ...],
    as_of: date,
) -> dict[str, object] | None:
    if scenario.kind != SavedScenarioKind.BUDGET or initial_observation is None:
        return None

    with localcontext() as context:
        context.prec = 64
        confirmed_spend = sum((entry.amount for entry in spend_entries), Decimal("0"))
    try:
        reference_budget = resolve_trip_budget_reference(
            budget_basis=scenario.budget_basis,
            initial_destination_amount=initial_observation.output_amount,
            planning_destination_amount=scenario.planning_destination_amount,
        )
        summary = calculate_trip_budget_summary(
            reference_budget=reference_budget,
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
        "basis": scenario.budget_basis,
        "basis_label": (
            "Payment-adjusted saved baseline"
            if scenario.budget_basis == SavedScenarioBudgetBasis.PAYMENT_ESTIMATE
            else "Saved FX reference baseline"
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
        "has_remaining_per_day": summary.remaining_per_day is not None,
        "remaining_per_day": (
            _format_currency_amount(
                summary.remaining_per_day,
                minor_units=minor_units,
            )
            if summary.remaining_per_day is not None
            else None
        ),
    }


def _scenario_local_context(
    scenario: SavedScenario,
    *,
    observation,
    as_of: date,
) -> dict[str, object]:
    """Build current reviewed destination context only after explicit user request."""

    if (
        scenario.kind != SavedScenarioKind.BUDGET
        or scenario.destination_country is None
        or observation is None
    ):
        return {
            "state": "empty",
            "component": None,
            "message": (
                "Current local context needs a saved budget destination and trusted FX observation."
            ),
        }

    try:
        context = build_destination_context(
            country_code=scenario.destination_country.iso2,
            converted_amount=observation.output_amount,
            quote_currency=scenario.destination_currency.code,
            as_of=as_of,
            price_limit=3,
            city_slug=(
                scenario.destination_city.slug if scenario.destination_city is not None else ""
            ),
        )
    except (DatabaseError, DecimalException, ValueError) as exc:
        logger.warning(
            "saved_scenario_local_context_unavailable",
            extra={
                "scenario_id": scenario.pk,
                "error_code": exc.__class__.__name__,
            },
        )
        return {
            "state": "degraded",
            "component": None,
            "message": (
                "Current reviewed local money context is temporarily unavailable. "
                "Your saved scenario and FX observations were not changed."
            ),
        }

    if context is None or not context.has_content:
        return {
            "state": "empty",
            "component": None,
            "message": (
                "No current reviewed price or payment context is available for this saved "
                "destination yet."
            ),
        }

    return {
        "state": "available",
        "component": build_destination_context_component(
            context,
            historical=False,
            show_explore_nav=False,
        ),
        "message": "",
        "amount": _format_currency_amount(
            observation.output_amount,
            minor_units=scenario.destination_currency.minor_units,
        ),
        "currency": scenario.destination_currency.code,
        "observation_effective_date": observation.effective_date,
        "as_of": as_of,
    }


def _scenario_detail_context(
    scenario: SavedScenario,
    *,
    spend_form: SavedScenarioSpendForm | None = None,
    local_context_requested: bool = False,
) -> dict[str, object]:
    initial_observation = (
        scenario.observations.filter(kind=SavedScenarioObservationKind.INITIAL)
        .order_by("recorded_at", "id")
        .first()
    )
    latest_observation = scenario.observations.order_by("-recorded_at", "-id").first()
    observation_history = tuple(scenario.observations.order_by("-recorded_at", "-id"))
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
    shopping = _scenario_shopping_component(
        scenario,
        initial_observation=initial_observation,
    )
    share_url = ""
    if latest_observation is not None:
        try:
            share_token = build_scenario_share_token(scenario, latest_observation)
        except ScenarioShareTokenError:
            logger.warning(
                "saved_scenario_share_snapshot_unavailable",
                extra={"scenario_id": scenario.pk},
            )
        else:
            share_url = f"{reverse('share_scenario_card')}?{urlencode({'snapshot': share_token})}"

    local_context = (
        _scenario_local_context(
            scenario,
            observation=latest_observation or initial_observation,
            as_of=as_of,
        )
        if local_context_requested
        else None
    )
    if spend_form is None:
        spend_form = SavedScenarioSpendForm(
            destination_currency_code=scenario.destination_currency.code,
            destination_minor_units=scenario.destination_currency.minor_units,
        )

    saved_notification_preferences = {
        preference.notification_type: preference
        for preference in notification_preferences_for_scenario(
            scenario.user,
            scenario_id=scenario.pk,
        )
    }
    notification_specs = (
        (
            ScenarioNotificationType.PRE_TRIP,
            "Pre-trip reminder",
            "Prompt me to reopen and re-check this saved trip when departure is close.",
            ScenarioNotificationCadence.ONCE,
            scenario.travel_start_date is not None,
        ),
        (
            ScenarioNotificationType.CONTEXT_FRESHNESS,
            "Context & offline freshness",
            "Remind me before travel when the stored trip reference is old enough to re-check.",
            ScenarioNotificationCadence.WEEKLY,
            scenario.kind == SavedScenarioKind.BUDGET and scenario.destination_country is not None,
        ),
        (
            ScenarioNotificationType.RATE_ALERT,
            "Scenario rate alert",
            "Tell me when the current reference rate moves beyond my explicit threshold.",
            ScenarioNotificationCadence.DAILY,
            initial_observation is not None,
        ),
    )
    notification_rows = []
    for notification_type, label, help_text, default_cadence, available in notification_specs:
        preference = saved_notification_preferences.get(notification_type)
        notification_rows.append(
            {
                "notification_type": notification_type,
                "label": label,
                "help_text": help_text,
                "available": available,
                "preference": preference,
                "enabled": bool(preference and preference.enabled),
                "timezone": (preference.timezone if preference is not None else settings.TIME_ZONE),
                "cadence": (preference.cadence if preference is not None else default_cadence),
                "threshold": (
                    preference.rate_change_threshold_percent
                    if preference is not None
                    and preference.rate_change_threshold_percent is not None
                    else "2.0"
                ),
            }
        )

    return {
        "scenario": scenario,
        "budget_item_rows": budget_item_rows,
        "initial_observation": initial_observation,
        "latest_observation": latest_observation,
        "observation_history": observation_history,
        "observation_history_count": len(observation_history),
        "rate_comparison": rate_comparison,
        "trip_schedule": trip_schedule,
        "trip_budget": trip_budget,
        "shopping": shopping,
        "local_context_requested": local_context_requested,
        "local_context": local_context,
        "local_context_url": (
            f"{reverse('saved_scenario_detail', args=(scenario.pk,))}"
            "?local_context=1#scenario-local-context-title"
        ),
        "local_context_hide_url": (
            f"{reverse('saved_scenario_detail', args=(scenario.pk,))}#scenario-local-context-title"
        ),
        "offline_snapshot_url": reverse("offline_trip_snapshot", args=(scenario.pk,)),
        "offline_snapshot_revision": (
            build_offline_snapshot_revision(scenario) if trip_budget is not None else ""
        ),
        "spend_entries": spend_entries,
        "spend_form": spend_form,
        "converter_url": _scenario_converter_url(scenario),
        "reopen_url": _scenario_reopen_url(scenario),
        "share_url": share_url,
        "camera_extraction_available": (
            scenario.kind == SavedScenarioKind.BUDGET
            and bool(settings.AI_CAMERA_EXTRACTION_ENABLED)
        ),
        "notification_rows": tuple(notification_rows),
    }


def _owned_scenario_for_detail(request: HttpRequest, scenario_id: int) -> SavedScenario:
    return get_object_or_404(
        SavedScenario.objects.select_related(
            "user",
            "source_currency",
            "destination_currency",
            "source_country",
            "destination_country",
            "destination_city",
        )
        .select_related("shopping_assumptions")
        .prefetch_related(
            "budget_items",
            "spend_entries",
            "observations",
        ),
        pk=scenario_id,
        user=request.user,
    )


@login_required
@require_POST
def save_budget_scenario(request: HttpRequest) -> HttpResponse:
    try:
        draft = build_budget_scenario_draft(request.POST)
    except ScenarioDraftError as exc:
        logger.warning(
            "saved_budget_scenario_rejected",
            extra={"error_code": exc.code},
        )
        messages.error(request, exc.user_message)
        return redirect("converter")
    except DatabaseError as exc:
        logger.warning(
            "saved_budget_scenario_rejected",
            extra={
                "error_code": "draft_database_unavailable",
                "detail_code": exc.__class__.__name__,
            },
        )
        messages.error(
            request,
            "Saved scenarios are temporarily unavailable. Your conversion was not changed.",
        )
        return redirect("converter")

    try:
        scenario = create_saved_scenario(
            request.user,
            spec=draft.spec,
            conversion=draft.conversion,
        )
    except SavedScenarioError as exc:
        logger.warning(
            "saved_budget_scenario_rejected",
            extra={"error_code": "scenario_domain_rejected", "detail_code": str(exc)},
        )
        messages.error(request, f"Could not save this budget: {exc}")
        return redirect("converter")
    except DatabaseError as exc:
        logger.warning(
            "saved_budget_scenario_rejected",
            extra={
                "error_code": "scenario_database_unavailable",
                "detail_code": exc.__class__.__name__,
            },
        )
        messages.error(
            request,
            "Saved scenarios are temporarily unavailable. Your conversion was not changed.",
        )
        return redirect("converter")

    messages.success(request, "Budget saved to your account.")
    return redirect("saved_scenario_detail", scenario_id=scenario.pk)


@login_required
@require_POST
def save_shopping_scenario(request: HttpRequest) -> HttpResponse:
    try:
        draft = build_shopping_scenario_draft(request.POST)
    except ScenarioDraftError as exc:
        logger.warning(
            "saved_shopping_scenario_rejected",
            extra={"error_code": exc.code},
        )
        messages.error(request, exc.user_message)
        return redirect("shopping_calculation")
    except DatabaseError:
        logger.exception("saved_shopping_scenario_draft_unavailable")
        messages.error(
            request,
            "Saved scenarios are temporarily unavailable. Your Shopping estimate was not changed.",
        )
        return redirect("shopping_calculation")

    try:
        scenario = create_saved_scenario(
            request.user,
            spec=draft.spec,
            conversion=draft.conversion,
        )
    except SavedScenarioError as exc:
        messages.error(request, f"Could not save Shopping estimate: {exc}")
        return redirect("shopping_calculation")
    except DatabaseError:
        logger.exception("saved_shopping_scenario_persistence_unavailable")
        messages.error(
            request,
            "The Shopping estimate could not be saved. Your calculated result was not changed.",
        )
        return redirect("shopping_calculation")

    messages.success(request, "Shopping estimate saved to your account.")
    return redirect("saved_scenario_detail", scenario_id=scenario.pk)


@login_required
@never_cache
@require_GET
def saved_scenario_detail(request: HttpRequest, scenario_id: int) -> HttpResponse:
    scenario = _owned_scenario_for_detail(request, scenario_id)
    return render(
        request,
        "travel/saved_scenario_detail.html",
        _scenario_detail_context(
            scenario,
            local_context_requested=request.GET.get("local_context") == "1",
        ),
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
    submission_key = form.cleaned_data.get("submission_key")
    if not isinstance(amount, Decimal):
        raise RuntimeError("Valid spend form returned no Decimal amount.")
    if submission_key is None:
        raise RuntimeError("Valid spend form returned no submission key.")

    try:
        record_scenario_spend(
            scenario,
            amount=amount,
            submission_key=submission_key,
        )
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
    with transaction.atomic():
        scenario = get_object_or_404(
            SavedScenario.objects.select_for_update(),
            pk=scenario_id,
            user=request.user,
        )
        entry = get_object_or_404(
            SavedScenarioSpendEntry.objects.select_for_update(),
            pk=entry_id,
            scenario=scenario,
        )
        scenario_id_value = scenario.pk
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
