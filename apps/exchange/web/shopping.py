from __future__ import annotations

import logging
from collections.abc import Callable

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils.formats import date_format
from django.views.decorators.http import require_http_methods

from apps.countries.theme_profiles import country_theme_key
from apps.exchange.cache import LatestQuoteGateway
from apps.exchange.domain import FxDomainError
from apps.exchange.forms import ShoppingCalculationForm
from apps.exchange.providers.base import FxProviderError
from apps.exchange.services import quote_conversion
from apps.exchange.shopping import ShoppingCalculationError, calculate_shopping_estimate
from apps.exchange.shopping_snapshot import build_shopping_context_snapshot_token

logger = logging.getLogger("cultural_currency.exchange")


def _money_text(value, *, minor_units: int) -> str:
    return f"{value:.{minor_units}f}"


@require_http_methods(["GET", "POST"])
def shopping_calculation_view(
    request: HttpRequest,
    *,
    latest_gateway_factory: Callable[[], LatestQuoteGateway],
) -> HttpResponse:
    """Calculate one explicit foreign-purchase estimate through canonical FX."""

    initial = None
    if request.method == "GET":
        initial = {
            key: str(request.GET.get(key) or "").strip()
            for key in (
                "purchase_country",
                "purchase_currency",
                "home_currency",
                "item_price",
                "shipping",
                "known_fees",
                "fx_markup_percent",
            )
            if request.GET.get(key) is not None
        }
    form = ShoppingCalculationForm(
        request.POST if request.method == "POST" else None,
        initial=initial,
    )
    component = None
    error = None
    status = 200

    if request.method == "POST" and form.is_valid():
        assumptions = form.cleaned_data["shopping_assumptions"]
        purchase_currency = form.cleaned_data["purchase_currency_object"]
        home_currency = form.cleaned_data["home_currency_object"]
        purchase_country = form.cleaned_data.get("purchase_country_object")

        try:
            conversion = quote_conversion(
                amount=assumptions.purchase_total,
                base_currency=purchase_currency.code,
                quote_currency=home_currency.code,
                quote_minor_units=home_currency.minor_units,
                gateway=latest_gateway_factory(),
            )
            estimate = calculate_shopping_estimate(
                conversion=conversion,
                assumptions=assumptions,
                home_minor_units=home_currency.minor_units,
            )
        except FxProviderError as exc:
            logger.warning(
                "shopping_fx_unavailable",
                extra={"error_code": exc.__class__.__name__},
            )
            status = 503
            error = {
                "title": "Shopping reference rate is temporarily unavailable.",
                "detail": (
                    "Your purchase assumptions are still visible below. "
                    "Try the reference-rate calculation again in a moment."
                ),
            }
        except (FxDomainError, ShoppingCalculationError) as exc:
            logger.warning(
                "shopping_calculation_rejected",
                extra={"error_code": exc.__class__.__name__},
            )
            form.add_error(None, str(exc))
            status = 422
        else:
            component = {
                "save_token": build_shopping_context_snapshot_token(
                    conversion=conversion,
                    assumptions=assumptions,
                    purchase_country_code=(
                        purchase_country.iso2 if purchase_country is not None else ""
                    ),
                ),
                "purchase_country_code": purchase_country.iso2 if purchase_country else "",
                "purchase_country_name": purchase_country.name if purchase_country else "",
                "theme": country_theme_key(purchase_country.iso2) if purchase_country else "",
                "purchase_currency": purchase_currency.code,
                "home_currency": home_currency.code,
                "item_price": _money_text(
                    assumptions.item_price,
                    minor_units=purchase_currency.minor_units,
                ),
                "shipping": _money_text(
                    assumptions.shipping,
                    minor_units=purchase_currency.minor_units,
                ),
                "known_fees": _money_text(
                    assumptions.known_fees,
                    minor_units=purchase_currency.minor_units,
                ),
                "purchase_total": _money_text(
                    assumptions.purchase_total,
                    minor_units=purchase_currency.minor_units,
                ),
                "reference_home_cost": _money_text(
                    estimate.reference_home_cost,
                    minor_units=home_currency.minor_units,
                ),
                "estimated_home_cost": _money_text(
                    estimate.estimated_home_cost,
                    minor_units=home_currency.minor_units,
                ),
                "fx_markup_percent": format(assumptions.fx_markup_percent, "f"),
                "fx_markup_cost": _money_text(
                    estimate.fx_markup_cost,
                    minor_units=home_currency.minor_units,
                ),
                "effective_date": date_format(conversion.quote.effective_date, "j M Y"),
                "providers": (
                    ", ".join(key.upper() for key in conversion.quote.provider_keys)
                    or "Provider attribution unavailable"
                ),
                "stale": conversion.stale,
                "unknown_costs": estimate.unknown_costs,
            }

    elif request.method == "POST":
        status = 422

    return render(
        request,
        "pages/shopping.html",
        {
            "form": form,
            "shopping": component,
            "shopping_error": error,
            "reference_data_ready": form.reference_data_ready,
        },
        status=status,
    )
