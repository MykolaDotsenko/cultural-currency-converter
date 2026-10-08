"""Stateless mobile JSON adapter for the canonical foreign-purchase estimate."""

from __future__ import annotations

from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.exchange.api_v1 import (
    _api_error,
    _api_response,
    _conversion_result_payload,
    _decimal_text,
    _json_body,
    _provider_quota_error,
    _submission_error_response,
)
from apps.exchange.domain import FxDomainError
from apps.exchange.forms import ShoppingCalculationForm
from apps.exchange.providers.base import FxProviderError
from apps.exchange.services import quote_conversion
from apps.exchange.shopping import ShoppingCalculationError, calculate_shopping_estimate
from apps.exchange.web.gateways import build_latest_quote_gateway

_SHOPPING_FIELDS = {
    "purchaseCountry": "purchase_country",
    "purchaseCurrency": "purchase_currency",
    "homeCurrency": "home_currency",
    "itemPrice": "item_price",
    "shipping": "shipping",
    "knownFees": "known_fees",
    "fxMarkupPercent": "fx_markup_percent",
}


@csrf_exempt
@require_POST
def api_v1_shopping_estimate(request: HttpRequest) -> JsonResponse:
    """Use exactly the same form, FX quote and domain calculation as the web UI."""
    payload = _json_body(request)
    if isinstance(payload, JsonResponse):
        return payload

    unknown = sorted(set(payload) - _SHOPPING_FIELDS.keys())
    if unknown:
        return _api_error(
            code="unknown_fields",
            message="Request contains unsupported fields.",
            status=400,
            details={"fields": unknown},
        )

    invalid_types = sorted(key for key, value in payload.items() if not isinstance(value, str))
    if invalid_types:
        return _api_error(
            code="invalid_request",
            message="Shopping inputs must be decimal or identifier strings.",
            status=400,
            fields={
                key: ["Use a string, including for monetary amounts."] for key in invalid_types
            },
        )

    form = ShoppingCalculationForm({_SHOPPING_FIELDS[key]: value for key, value in payload.items()})
    if not form.is_valid():
        return _api_error(
            code="validation_error",
            message="Shopping inputs are invalid.",
            status=422,
            fields={
                field: [str(message) for message in messages]
                for field, messages in form.errors.items()
            },
        )

    quota_error = _provider_quota_error(request)
    if quota_error is not None:
        return quota_error

    assumptions = form.cleaned_data["shopping_assumptions"]
    purchase_currency = form.cleaned_data["purchase_currency_object"]
    home_currency = form.cleaned_data["home_currency_object"]
    country = form.cleaned_data["purchase_country_object"]

    try:
        conversion = quote_conversion(
            amount=assumptions.purchase_total,
            base_currency=purchase_currency.code,
            quote_currency=home_currency.code,
            quote_minor_units=home_currency.minor_units,
            gateway=build_latest_quote_gateway(),
        )
        estimate = calculate_shopping_estimate(
            conversion=conversion,
            assumptions=assumptions,
            home_minor_units=home_currency.minor_units,
        )
    except FxProviderError as exc:
        return _submission_error_response(exc)
    except (FxDomainError, ShoppingCalculationError):
        return _api_error(
            code="calculation_unavailable",
            message="The shopping estimate could not be calculated safely.",
            status=422,
        )

    return _api_response(
        {
            "schemaVersion": "1",
            "data": {
                "purchaseCountry": country.iso2 if country else None,
                "purchaseCurrency": purchase_currency.code,
                "homeCurrency": home_currency.code,
                "assumptions": {
                    "itemPrice": _decimal_text(assumptions.item_price),
                    "shipping": _decimal_text(assumptions.shipping),
                    "knownFees": _decimal_text(assumptions.known_fees),
                    "fxMarkupPercent": _decimal_text(assumptions.fx_markup_percent),
                },
                "purchaseTotal": _decimal_text(assumptions.purchase_total),
                "referenceHomeCost": _decimal_text(estimate.reference_home_cost),
                "estimatedHomeCost": _decimal_text(estimate.estimated_home_cost),
                "fxMarkupCost": _decimal_text(estimate.fx_markup_cost),
                "unknownCosts": list(estimate.unknown_costs),
                "conversion": _conversion_result_payload(conversion),
            },
        }
    )
