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
from apps.exchange.open_prices_context import lookup_public_price_observations
from apps.exchange.product_context import (
    ProductContextTokenError,
    build_product_context_token,
    load_product_context_token,
    lookup_product_identity_cached,
)
from apps.exchange.providers.base import FxProviderError
from apps.exchange.services import quote_conversion
from apps.exchange.shopping import ShoppingCalculationError, calculate_shopping_estimate
from apps.exchange.shopping_snapshot import build_shopping_context_snapshot_token
from integrations.price_data import OpenPricesRateLimited, OpenPricesSourceError, PublicPriceObservation
from integrations.product_data import (
    ProductDataSourceError,
    ProductIdentity,
    ProductNotFound,
    ProductSourceRateLimited,
)

logger = logging.getLogger("cultural_currency.exchange")


def _money_text(value, *, minor_units: int) -> str:
    return f"{value:.{minor_units}f}"


def _product_component(identity: ProductIdentity) -> dict[str, object]:
    return {
        "barcode": identity.barcode,
        "name": identity.product_name,
        "brands": ", ".join(identity.brands),
        "quantity": identity.quantity,
        "categories": identity.categories,
        "source_name": identity.source_name,
        "source_url": identity.source_url,
        "retrieved_at": date_format(identity.retrieved_at, "j M Y"),
    }


def _public_price_component(item: PublicPriceObservation) -> dict[str, object]:
    return {
        "amount": format(item.amount, "f"),
        "currency": item.currency,
        "observed_at": date_format(item.observed_at, "j M Y"),
        "country_code": item.country_code,
        "location": item.location_label,
        "discounted": item.discounted,
        "source_url": item.source_url,
        "proof_id": item.proof_id,
        "retrieved_at": date_format(item.retrieved_at, "j M Y"),
    }


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
    product_identity = None
    product_token = ""
    product_lookup_message = None
    public_prices: tuple[PublicPriceObservation, ...] = ()
    public_prices_checked = False
    public_prices_message = None

    if request.method == "GET" and request.GET.get("barcode") is not None:
        barcode = str(request.GET.get("barcode") or "").strip()
        try:
            product_identity = lookup_product_identity_cached(barcode)
        except ValueError:
            product_lookup_message = {
                "tone": "error",
                "title": "Check the barcode.",
                "detail": "Enter 7–14 barcode digits. Spaces are ignored.",
            }
        except ProductNotFound:
            product_lookup_message = {
                "tone": "neutral",
                "title": "Product not found in Open Food Facts.",
                "detail": (
                    "You can still enter the shelf price manually. "
                    "Product identity never controls the Shopping calculation."
                ),
            }
        except ProductSourceRateLimited:
            product_lookup_message = {
                "tone": "neutral",
                "title": "Product lookup is temporarily busy.",
                "detail": "The Shopping calculator still works with a manually entered price.",
            }
        except ProductDataSourceError as exc:
            logger.warning(
                "shopping_product_lookup_unavailable",
                extra={"error_code": exc.__class__.__name__},
            )
            product_lookup_message = {
                "tone": "neutral",
                "title": "Product context is temporarily unavailable.",
                "detail": "The Shopping calculator still works with a manually entered price.",
            }
        else:
            product_token = build_product_context_token(product_identity)

    if (
        request.method == "GET"
        and product_identity is not None
        and request.GET.get("show_prices") == "1"
    ):
        public_prices_checked = True
        try:
            public_prices = lookup_public_price_observations(product_identity.barcode)
        except OpenPricesRateLimited:
            public_prices_message = (
                "Community price lookup is busy. The Shopping calculator is still available."
            )
        except OpenPricesSourceError as exc:
            logger.warning(
                "shopping_open_prices_lookup_unavailable",
                extra={"error_code": exc.__class__.__name__},
            )
            public_prices_message = (
                "Community price observations are unavailable. Enter your own shelf price below."
            )

    if request.method == "POST":
        submitted_product_token = str(request.POST.get("product_context_token") or "")
        if submitted_product_token:
            try:
                product_identity = load_product_context_token(submitted_product_token)
            except ProductContextTokenError:
                product_lookup_message = {
                    "tone": "neutral",
                    "title": "Saved product context expired.",
                    "detail": (
                        "The product label was removed, but your explicit price and "
                        "Shopping calculation are unchanged."
                    ),
                }
            else:
                product_token = submitted_product_token

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
                "product": (
                    _product_component(product_identity) if product_identity is not None else None
                ),
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
            "product_context": (
                _product_component(product_identity) if product_identity is not None else None
            ),
            "product_context_token": product_token,
            "product_lookup_message": product_lookup_message,
            "public_prices": tuple(_public_price_component(x) for x in public_prices),
            "public_prices_checked": public_prices_checked,
            "public_prices_message": public_prices_message,
        },
        status=status,
    )
