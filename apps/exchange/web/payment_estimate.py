from __future__ import annotations

import logging

from django.db import DatabaseError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils.cache import patch_vary_headers
from django.utils.formats import date_format
from django.views.decorators.http import require_POST

from apps.countries.models import Currency
from apps.exchange.snapshot_tokens import (
    ConversionSnapshotTokenError,
    load_conversion_snapshot_token,
)
from apps.exchange.forms import PaymentEstimateForm
from apps.exchange.payment_estimate import PaymentEstimateError, estimate_payment_value
from apps.exchange.web.common import is_htmx

logger = logging.getLogger("cultural_currency.exchange")


def _money_text(value, *, minor_units: int) -> str:
    return f"{value:.{minor_units}f}"


@require_POST
def payment_estimate_view(request: HttpRequest) -> HttpResponse:
    token = request.POST.get("payment_estimate_token", "")
    estimate = None
    estimate_error = None
    form = None
    component = None
    response_status = 200

    try:
        snapshot = load_conversion_snapshot_token(token)
    except ConversionSnapshotTokenError:
        response_status = 422
        estimate_error = {
            "title": "This payment estimate request is no longer valid.",
            "detail": "Run the conversion again, then reopen the payment estimate.",
        }
    else:
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
            if estimate_error is None and (
                source_currency is None or destination_currency is None
            ):
                response_status = 422
                estimate_error = {
                    "title": "Currency precision metadata is unavailable.",
                    "detail": "Run the conversion again after reference data is restored.",
                }
            elif estimate_error is None:
                form = PaymentEstimateForm(
                    request.POST,
                    source_currency_code=source_currency.code,
                    destination_currency_code=destination_currency.code,
                    source_minor_units=source_currency.minor_units,
                    destination_minor_units=destination_currency.minor_units,
                )
                if form.is_valid():
                    try:
                        estimate = estimate_payment_value(
                            source_budget=snapshot.input_amount,
                            reference_destination_amount=snapshot.output_amount,
                            rate=snapshot.rate,
                            fx_markup_percent=form.cleaned_data["fx_markup_percent"],
                            source_fixed_fee=form.cleaned_data["source_fixed_fee_decimal"],
                            destination_fixed_fee=form.cleaned_data[
                                "destination_fixed_fee_decimal"
                            ],
                            destination_minor_units=destination_currency.minor_units,
                        )
                    except PaymentEstimateError as exc:
                        form.add_error(None, str(exc))
                        response_status = 422
                    else:
                        component = {
                            "token": token,
                            "form": form,
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
                else:
                    response_status = 422

                if component is None:
                    component = {
                        "token": token,
                        "form": form,
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
