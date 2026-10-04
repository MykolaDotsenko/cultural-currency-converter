from __future__ import annotations

import logging

from django.db import DatabaseError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils.cache import patch_vary_headers
from django.views.decorators.http import require_POST

from apps.accounts.forms import BudgetPresetNameForm
from apps.countries.models import Currency
from apps.culture.models import TypicalPriceCategory
from apps.exchange.budget import (
    BudgetAssumptions,
    BudgetBasis,
    BudgetInterpretationError,
    available_budget_categories,
    interpret_budget,
)
from apps.exchange.budget_presentation import build_budget_component
from apps.exchange.budget_snapshot import (
    BudgetContextTokenError,
    load_budget_context_snapshot_token,
)
from apps.exchange.forms import BudgetInterpretationForm
from apps.exchange.money_context import (
    MoneyContextState,
    apply_payment_assumptions,
    build_money_context,
)
from apps.exchange.payment_budget_snapshot import (
    PaymentBudgetHandoffTokenError,
    TrustedPaymentBudgetHandoff,
    load_payment_budget_handoff_token,
)
from apps.exchange.payment_estimate import PaymentEstimateAssumptions, PaymentEstimateError
from apps.exchange.web.common import is_htmx
from apps.travel.budget_presets import (
    BudgetAssumptionPresetError,
    budget_preset_for_user,
    budget_presets_for_user,
    upsert_budget_preset,
)

logger = logging.getLogger("cultural_currency.exchange")


@require_POST
def budget_interpretation_view(request: HttpRequest) -> HttpResponse:
    submitted_budget_token = str(request.POST.get("budget_context_token") or "")
    payment_handoff_token = str(request.POST.get("payment_budget_token") or "")
    payment_handoff: TrustedPaymentBudgetHandoff | None = None
    basis = BudgetBasis.REFERENCE_CONVERSION
    token = submitted_budget_token
    component = None
    budget_error = None
    response_status = 200

    if payment_handoff_token:
        try:
            payment_handoff = load_payment_budget_handoff_token(payment_handoff_token)
        except PaymentBudgetHandoffTokenError as exc:
            logger.warning(
                "payment_budget_handoff_rejected",
                extra={"error_code": str(exc)},
            )
            response_status = 422
            budget_error = {
                "title": "This payment-adjusted budget request is no longer valid.",
                "detail": "Recalculate the payment estimate, then reopen budget planning.",
            }
        else:
            basis = BudgetBasis.PAYMENT_ESTIMATE
            token = payment_handoff.budget_context_token

    snapshot = None
    if budget_error is None:
        try:
            snapshot = load_budget_context_snapshot_token(token)
        except BudgetContextTokenError as exc:
            logger.warning(
                "budget_context_snapshot_rejected",
                extra={"error_code": str(exc)},
            )
            response_status = 422
            budget_error = {
                "title": "This budget request is no longer valid.",
                "detail": "Run the conversion again, then reopen the budget interpretation.",
            }

    destination_currency = None
    if budget_error is None and snapshot is not None:
        try:
            destination_currency = (
                Currency.objects.only("code", "minor_units")
                .filter(code=snapshot.conversion.quote.quote_currency)
                .first()
            )
        except DatabaseError as exc:
            logger.warning(
                "budget_currency_metadata_unavailable",
                extra={"error_code": exc.__class__.__name__},
            )
            response_status = 503
            budget_error = {
                "title": "Budget interpretation is temporarily unavailable.",
                "detail": "Your reference conversion remains valid. Try the budget view again.",
            }

    if budget_error is None and destination_currency is None:
        response_status = 422
        budget_error = {
            "title": "Currency precision metadata is unavailable.",
            "detail": "Run the conversion again after reference data is restored.",
        }

    if budget_error is None and snapshot is not None and destination_currency is not None:
        money_context = build_money_context(
            conversion=snapshot.conversion,
            destination_country_code=snapshot.destination_country_code,
            destination_city_slug=snapshot.destination_city_slug,
            as_of=snapshot.as_of,
            price_limit=6,
        )

        if money_context.destination_state is MoneyContextState.DEGRADED:
            response_status = 503
            budget_error = {
                "title": "Local budget context is temporarily unavailable.",
                "detail": (
                    "The signed reference conversion is still valid. "
                    "Current sourced local-price context could not be loaded."
                ),
            }
        else:
            if payment_handoff is not None:
                try:
                    money_context = apply_payment_assumptions(
                        money_context,
                        assumptions=PaymentEstimateAssumptions(
                            fx_markup_percent=payment_handoff.fx_markup_percent,
                            source_fixed_fee=payment_handoff.source_fixed_fee,
                            destination_fixed_fee=payment_handoff.destination_fixed_fee,
                        ),
                        destination_minor_units=destination_currency.minor_units,
                    )
                except PaymentEstimateError as exc:
                    logger.warning(
                        "payment_budget_assumptions_rejected",
                        extra={"error_code": exc.__class__.__name__},
                    )
                    response_status = 422
                    budget_error = {
                        "title": "These payment assumptions can no longer be applied safely.",
                        "detail": "Recalculate the payment estimate before continuing to budget.",
                    }

            if budget_error is None:
                anchors = available_budget_categories(money_context)
                if not anchors:
                    response_status = 422
                    budget_error = {
                        "title": "There is not enough current local-price context yet.",
                        "detail": (
                            "Budget interpretation needs at least one sourced price anchor "
                            "at the selected destination scope."
                        ),
                    }
                else:
                    category_options = tuple((anchor.category, anchor.label) for anchor in anchors)
                    available_categories = {category for category, _label in category_options}
                    budget_presets = ()
                    preset_notice = None
                    preset_error = None
                    selected_preset_name = ""
                    skipped_preset_categories: tuple[str, ...] = ()
                    posted_data = request.POST
                    requested_preset_id = str(request.POST.get("budget_preset_id") or "").strip()

                    if request.user.is_authenticated:
                        try:
                            budget_presets = budget_presets_for_user(request.user)
                        except DatabaseError as exc:
                            logger.warning(
                                "budget_preset_lookup_failed",
                                extra={"error_code": exc.__class__.__name__},
                            )
                            if requested_preset_id:
                                response_status = 503
                                preset_error = (
                                    "Saved budget presets are temporarily unavailable. "
                                    "Enter assumptions manually."
                                )

                    if requested_preset_id and preset_error is None:
                        if not request.user.is_authenticated:
                            response_status = 403
                            preset_error = "Sign in before applying a saved budget preset."
                        else:
                            try:
                                preset = budget_preset_for_user(
                                    request.user,
                                    preset_id=int(requested_preset_id),
                                )
                            except (TypeError, ValueError, BudgetAssumptionPresetError):
                                response_status = 422
                                preset_error = "That budget preset is no longer available."
                            except DatabaseError as exc:
                                logger.warning(
                                    "budget_preset_apply_failed",
                                    extra={"error_code": exc.__class__.__name__},
                                )
                                response_status = 503
                                preset_error = (
                                    "Saved budget presets are temporarily unavailable. "
                                    "Enter assumptions manually."
                                )
                            else:
                                posted_data = request.POST.copy()
                                posted_data["duration_days"] = str(preset.duration_days)
                                posted_data["travelers"] = str(preset.travelers)
                                for category in TypicalPriceCategory.values:
                                    posted_data.pop(
                                        BudgetInterpretationForm.units_field_name(category),
                                        None,
                                    )

                                applied_categories = []
                                skipped_categories = []
                                for item in preset.items.all():
                                    if item.category in available_categories:
                                        posted_data[
                                            BudgetInterpretationForm.units_field_name(item.category)
                                        ] = format(item.units_per_person_per_day, "f")
                                        applied_categories.append(item.category)
                                    else:
                                        skipped_categories.append(item.category)

                                if not applied_categories:
                                    response_status = 422
                                    preset_error = (
                                        "None of this preset's basket items have current sourced "
                                        "price anchors at this destination."
                                    )
                                else:
                                    labels = dict(TypicalPriceCategory.choices)
                                    skipped_preset_categories = tuple(
                                        labels.get(category, category)
                                        for category in skipped_categories
                                    )
                                    selected_preset_name = preset.name
                                    preset_notice = f'Applied budget preset "{preset.name}".'

                    budget_input_keys = (
                        "duration_days",
                        "travelers",
                        "units_coffee",
                        "units_casual_meal",
                        "units_transit",
                        "units_groceries",
                        "units_other",
                    )
                    handoff_only = (
                        payment_handoff is not None
                        and not requested_preset_id
                        and not any(key in request.POST for key in budget_input_keys)
                    )
                    form = BudgetInterpretationForm(
                        None if handoff_only else posted_data,
                        category_options=category_options,
                        basis=basis,
                    )
                    interpretation = None
                    assumptions = None
                    if preset_error is None and not handoff_only:
                        if form.is_valid():
                            assumptions = form.cleaned_data.get("budget_assumptions")
                            if not isinstance(assumptions, BudgetAssumptions):
                                raise RuntimeError(
                                    "Valid budget form returned no BudgetAssumptions."
                                )
                            try:
                                interpretation = interpret_budget(
                                    money_context,
                                    assumptions=assumptions,
                                    destination_minor_units=destination_currency.minor_units,
                                )
                            except BudgetInterpretationError as exc:
                                form.add_error(None, str(exc))
                                response_status = 422
                        else:
                            response_status = 422

                    if (
                        interpretation is not None
                        and assumptions is not None
                        and request.POST.get("budget_action") == "save_preset"
                    ):
                        name_form = BudgetPresetNameForm(request.POST)
                        if not request.user.is_authenticated:
                            response_status = 403
                            preset_error = "Sign in before saving a budget preset."
                        elif not name_form.is_valid():
                            response_status = 422
                            preset_error = name_form.errors["preset_name"][0]
                        else:
                            try:
                                saved_preset = upsert_budget_preset(
                                    request.user,
                                    name=name_form.cleaned_data["preset_name"],
                                    assumptions=assumptions,
                                )
                                budget_presets = budget_presets_for_user(request.user)
                            except BudgetAssumptionPresetError as exc:
                                response_status = 422
                                preset_error = str(exc)
                            except DatabaseError as exc:
                                logger.warning(
                                    "budget_preset_save_failed",
                                    extra={"error_code": exc.__class__.__name__},
                                )
                                response_status = 503
                                preset_error = (
                                    "This budget interpretation is still valid, but the preset "
                                    "could not be saved."
                                )
                            else:
                                preset_notice = f'Saved budget preset "{saved_preset.name}".'
                                selected_preset_name = saved_preset.name

                    component = build_budget_component(
                        money_context,
                        destination_minor_units=destination_currency.minor_units,
                        form=form,
                        token=token,
                        interpretation=interpretation,
                        assumptions=assumptions if interpretation is not None else None,
                        payment_handoff_token=payment_handoff_token,
                    )
                    if component is not None:
                        component["budget_presets"] = budget_presets
                        component["preset_notice"] = preset_notice
                        component["preset_error"] = preset_error
                        component["preset_name_value"] = str(
                            request.POST.get("preset_name") or ""
                        )
                        component["selected_preset_name"] = selected_preset_name
                        component["skipped_preset_categories"] = skipped_preset_categories

    context = {
        "budget_interpretation": component,
        "budget_interpretation_error": budget_error,
    }
    fragment = is_htmx(request)
    template = (
        "components/converter/budget_interpretation.html"
        if fragment
        else "pages/budget_interpretation.html"
    )
    response = render(request, template, context, status=response_status)
    patch_vary_headers(response, ["HX-Request"])
    return response
