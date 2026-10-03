from __future__ import annotations

import logging

from django.db import DatabaseError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils.cache import patch_vary_headers
from django.views.decorators.http import require_POST

from apps.countries.models import Currency
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
                    handoff_only = payment_handoff is not None and not any(
                        key in request.POST
                        for key in (
                            "duration_days",
                            "travelers",
                            "units_coffee",
                            "units_casual_meal",
                            "units_transit",
                            "units_groceries",
                            "units_other",
                        )
                    )
                    form = BudgetInterpretationForm(
                        None if handoff_only else request.POST,
                        category_options=category_options,
                        basis=basis,
                    )
                    interpretation = None
                    assumptions = None
                    if not handoff_only:
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

                    component = build_budget_component(
                        money_context,
                        destination_minor_units=destination_currency.minor_units,
                        form=form,
                        token=token,
                        interpretation=interpretation,
                        assumptions=assumptions if interpretation is not None else None,
                        payment_handoff_token=payment_handoff_token,
                    )

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
