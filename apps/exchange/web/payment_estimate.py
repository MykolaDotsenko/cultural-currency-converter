from __future__ import annotations

import logging

from django.db import DatabaseError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils.cache import patch_vary_headers
from django.utils.formats import date_format
from django.views.decorators.http import require_POST

from apps.accounts.forms import PaymentFeeProfileNameForm
from apps.countries.models import Currency
from apps.exchange.budget_snapshot import (
    BudgetContextTokenError,
    TrustedBudgetContextSnapshot,
    load_budget_context_snapshot_token,
)
from apps.exchange.fee_profiles import (
    PaymentFeeProfileError,
    fee_profile_for_pair,
    fee_profiles_for_pair,
    upsert_payment_fee_profile,
)
from apps.exchange.forms import PaymentEstimateForm
from apps.exchange.payment_budget_snapshot import build_payment_budget_handoff_token
from apps.exchange.payment_estimate import (
    PaymentEstimateAssumptions,
    PaymentEstimateError,
    estimate_payment_value,
)
from apps.exchange.trusted_snapshot import (
    TrustedConversionSnapshot,
    TrustedSnapshotTokenError,
    load_trusted_conversion_snapshot_token,
)
from apps.exchange.web.common import is_htmx

logger = logging.getLogger("cultural_currency.exchange")


def _money_text(value, *, minor_units: int) -> str:
    return f"{value:.{minor_units}f}"


def _matching_budget_context(
    snapshot: TrustedConversionSnapshot,
    budget: TrustedBudgetContextSnapshot,
) -> bool:
    conversion = budget.conversion
    quote = conversion.quote
    return (
        conversion.input_amount == snapshot.input_amount
        and conversion.output_amount == snapshot.output_amount
        and quote.base_currency == snapshot.base_currency
        and quote.quote_currency == snapshot.quote_currency
        and quote.rate == snapshot.rate
        and quote.requested_date == snapshot.requested_date
        and quote.effective_date == snapshot.effective_date
        and quote.historical == snapshot.historical
        and quote.observation_granularity == snapshot.observation_granularity
        and quote.provider_keys == snapshot.provider_keys
        and conversion.stale == snapshot.stale
    )


@require_POST
def payment_estimate_view(request: HttpRequest) -> HttpResponse:
    token = request.POST.get("payment_estimate_token", "")
    submitted_budget_context_token = str(request.POST.get("budget_context_token") or "")
    trusted_budget_context_token = ""
    estimate = None
    estimate_error = None
    form = None
    component = None
    response_status = 200

    try:
        snapshot = load_trusted_conversion_snapshot_token(token)
    except TrustedSnapshotTokenError as exc:
        logger.warning(
            "payment_estimate_snapshot_rejected",
            extra={
                "error_code": str(exc),
            },
        )
        response_status = 422
        estimate_error = {
            "title": "This payment estimate request is no longer valid.",
            "detail": "Run the conversion again, then reopen the payment estimate.",
        }
    else:
        if submitted_budget_context_token:
            try:
                budget_snapshot = load_budget_context_snapshot_token(submitted_budget_context_token)
            except BudgetContextTokenError as exc:
                logger.warning(
                    "payment_estimate_budget_context_rejected",
                    extra={"error_code": str(exc)},
                )
            else:
                if _matching_budget_context(snapshot, budget_snapshot):
                    trusted_budget_context_token = submitted_budget_context_token
                else:
                    logger.warning(
                        "payment_estimate_budget_context_mismatch",
                        extra={"error_code": "conversion_mismatch"},
                    )

        if snapshot.historical:
            response_status = 422
            estimate_error = {
                "title": "Payment estimates use current reference conversions only.",
                "detail": (
                    "Historical FX does not establish historical card, ATM or merchant fees. "
                    "Run a current conversion to estimate explicit payment assumptions."
                ),
            }
        elif snapshot.base_currency == snapshot.quote_currency:
            response_status = 422
            estimate_error = {
                "title": "No FX payment estimate is needed for an exact 1:1 conversion.",
                "detail": "Choose two different currencies to estimate FX markup or fixed fees.",
            }
        else:
            try:
                currencies = Currency.objects.in_bulk(
                    [snapshot.base_currency, snapshot.quote_currency],
                    field_name="code",
                )
            except DatabaseError as exc:
                logger.warning(
                    "Payment estimate currency metadata lookup failed",
                    extra={"error_code": exc.__class__.__name__},
                )
                response_status = 503
                estimate_error = {
                    "title": "Payment estimate is temporarily unavailable.",
                    "detail": (
                        "Your reference conversion remains valid. "
                        "Try the fee estimate again in a moment."
                    ),
                }
                currencies = {}

            source_currency = currencies.get(snapshot.base_currency)
            destination_currency = currencies.get(snapshot.quote_currency)
            if estimate_error is None and (source_currency is None or destination_currency is None):
                response_status = 422
                estimate_error = {
                    "title": "Currency precision metadata is unavailable.",
                    "detail": "Run the conversion again after reference data is restored.",
                }
            elif estimate_error is None:
                fee_profiles = ()
                profile_notice = None
                profile_error = None
                selected_profile_name = ""
                posted_data = request.POST
                requested_profile_id = str(request.POST.get("fee_profile_id") or "").strip()

                if request.user.is_authenticated:
                    try:
                        fee_profiles = fee_profiles_for_pair(
                            request.user,
                            source_currency_code=source_currency.code,
                            destination_currency_code=destination_currency.code,
                        )
                    except DatabaseError as exc:
                        logger.warning(
                            "Payment fee profile lookup failed",
                            extra={"error_code": exc.__class__.__name__},
                        )
                        if requested_profile_id:
                            response_status = 503
                            profile_error = (
                                "Saved fee profiles are temporarily unavailable. "
                                "Enter assumptions manually."
                            )

                if requested_profile_id and profile_error is None:
                    try:
                        profile_id = int(requested_profile_id)
                        profile = fee_profile_for_pair(
                            request.user,
                            profile_id=profile_id,
                            source_currency_code=source_currency.code,
                            destination_currency_code=destination_currency.code,
                        )
                    except (TypeError, ValueError, PaymentFeeProfileError):
                        response_status = 422
                        profile_error = (
                            "That saved fee profile is unavailable for this currency pair."
                        )
                    except DatabaseError as exc:
                        logger.warning(
                            "Payment fee profile apply failed",
                            extra={"error_code": exc.__class__.__name__},
                        )
                        response_status = 503
                        profile_error = (
                            "Saved fee profiles are temporarily unavailable. "
                            "Enter assumptions manually."
                        )
                    else:
                        posted_data = request.POST.copy()
                        posted_data["fx_markup_percent"] = format(
                            profile.fx_markup_percent,
                            "f",
                        )
                        posted_data["source_fixed_fee"] = format(
                            profile.source_fixed_fee,
                            "f",
                        )
                        posted_data["destination_fixed_fee"] = format(
                            profile.destination_fixed_fee,
                            "f",
                        )
                        selected_profile_name = profile.name

                form = PaymentEstimateForm(
                    posted_data,
                    source_currency_code=source_currency.code,
                    destination_currency_code=destination_currency.code,
                    source_minor_units=source_currency.minor_units,
                    destination_minor_units=destination_currency.minor_units,
                )
                if profile_error is None and form.is_valid():
                    assumptions = PaymentEstimateAssumptions(
                        fx_markup_percent=form.cleaned_data["fx_markup_percent"],
                        source_fixed_fee=form.cleaned_data["source_fixed_fee_decimal"],
                        destination_fixed_fee=form.cleaned_data[
                            "destination_fixed_fee_decimal"
                        ],
                    )
                    try:
                        estimate = estimate_payment_value(
                            source_budget=snapshot.input_amount,
                            reference_destination_amount=snapshot.output_amount,
                            rate=snapshot.rate,
                            fx_markup_percent=assumptions.fx_markup_percent,
                            source_fixed_fee=assumptions.source_fixed_fee,
                            destination_fixed_fee=assumptions.destination_fixed_fee,
                            destination_minor_units=destination_currency.minor_units,
                        )
                    except PaymentEstimateError as exc:
                        form.add_error(None, str(exc))
                        response_status = 422
                    else:
                        if request.POST.get("payment_action") == "save_profile":
                            name_form = PaymentFeeProfileNameForm(request.POST)
                            if not request.user.is_authenticated:
                                response_status = 403
                                profile_error = "Sign in before saving a payment fee profile."
                            elif not name_form.is_valid():
                                response_status = 422
                                profile_error = name_form.errors["name"][0]
                            else:
                                try:
                                    saved_profile = upsert_payment_fee_profile(
                                        request.user,
                                        name=name_form.cleaned_data["name"],
                                        source_currency=source_currency,
                                        destination_currency=destination_currency,
                                        assumptions=assumptions,
                                    )
                                    fee_profiles = fee_profiles_for_pair(
                                        request.user,
                                        source_currency_code=source_currency.code,
                                        destination_currency_code=destination_currency.code,
                                    )
                                except PaymentFeeProfileError as exc:
                                    response_status = 422
                                    profile_error = str(exc)
                                except DatabaseError as exc:
                                    logger.warning(
                                        "Payment fee profile save failed",
                                        extra={"error_code": exc.__class__.__name__},
                                    )
                                    response_status = 503
                                    profile_error = (
                                        "This estimate is still valid, but the fee profile "
                                        "could not be saved."
                                    )
                                else:
                                    profile_notice = f'Saved fee profile "{saved_profile.name}".'
                                    selected_profile_name = saved_profile.name

                        component = {
                            "token": token,
                            "budget_context_token": trusted_budget_context_token,
                            "budget_handoff_token": (
                                build_payment_budget_handoff_token(
                                    budget_context_token=trusted_budget_context_token,
                                    estimate=estimate,
                                )
                                if trusted_budget_context_token
                                else ""
                            ),
                            "form": form,
                            "fee_profiles": fee_profiles,
                            "profile_notice": profile_notice,
                            "profile_error": profile_error,
                            "profile_name_value": str(request.POST.get("profile_name") or ""),
                            "selected_profile_name": selected_profile_name,
                            "source_currency": source_currency.code,
                            "destination_currency": destination_currency.code,
                            "reference_amount": _money_text(
                                estimate.reference_destination_amount,
                                minor_units=destination_currency.minor_units,
                            ),
                            "estimated_amount": _money_text(
                                estimate.estimated_destination_amount,
                                minor_units=destination_currency.minor_units,
                            ),
                            "difference_amount": _money_text(
                                estimate.destination_value_lost,
                                minor_units=destination_currency.minor_units,
                            ),
                            "source_budget": _money_text(
                                estimate.source_budget,
                                minor_units=source_currency.minor_units,
                            ),
                            "effective_source_amount": _money_text(
                                estimate.effective_source_amount,
                                minor_units=source_currency.minor_units,
                            ),
                            "fx_markup_percent": format(estimate.fx_markup_percent, "f"),
                            "source_fixed_fee": _money_text(
                                estimate.source_fixed_fee,
                                minor_units=source_currency.minor_units,
                            ),
                            "destination_fixed_fee": _money_text(
                                estimate.destination_fixed_fee,
                                minor_units=destination_currency.minor_units,
                            ),
                            "effective_date": date_format(snapshot.effective_date, "j M Y"),
                            "provider": (
                                ", ".join(key.upper() for key in snapshot.provider_keys)
                                or "Provider attribution unavailable"
                            ),
                            "stale": snapshot.stale,
                        }
                elif profile_error is None:
                    response_status = 422

                if component is None:
                    component = {
                        "token": token,
                        "budget_context_token": trusted_budget_context_token,
                        "budget_handoff_token": "",
                        "form": form,
                        "fee_profiles": fee_profiles,
                        "profile_notice": profile_notice,
                        "profile_error": profile_error,
                        "profile_name_value": str(request.POST.get("profile_name") or ""),
                        "selected_profile_name": selected_profile_name,
                        "source_currency": source_currency.code,
                        "destination_currency": destination_currency.code,
                        "reference_amount": _money_text(
                            snapshot.output_amount,
                            minor_units=destination_currency.minor_units,
                        ),
                        "effective_date": date_format(snapshot.effective_date, "j M Y"),
                        "provider": (
                            ", ".join(key.upper() for key in snapshot.provider_keys)
                            or "Provider attribution unavailable"
                        ),
                        "stale": snapshot.stale,
                    }

    context = {
        "payment_estimate": component,
        "payment_estimate_error": estimate_error,
    }
    fragment = is_htmx(request)
    template = (
        "components/converter/payment_estimate.html" if fragment else "pages/payment_estimate.html"
    )
    response = render(request, template, context, status=response_status)
    patch_vary_headers(response, ["HX-Request"])
    return response
