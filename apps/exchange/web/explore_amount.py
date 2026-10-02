from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Never
from urllib.parse import urlencode

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format
from django.views.decorators.http import require_http_methods

from apps.exchange.application import ConverterSubmissionCommand, run_converter_submission
from apps.exchange.cache import LatestQuoteGateway
from apps.exchange.forms import ExploreAmountForm
from apps.exchange.money_context import MoneyContextState

LatestGatewayFactory = Callable[[], LatestQuoteGateway]


def _historical_gateway_not_allowed() -> Never:
    raise AssertionError("Explore same-amount view must never request a historical quote.")


def _money_text(value: Decimal, *, minor_units: int) -> str:
    return f"{value:.{minor_units}f}"


def _price_text(price) -> str:
    low = _money_text(price.amount_low, minor_units=price.currency_minor_units)
    if price.amount_high is None or price.amount_high == price.amount_low:
        return f"{low} {price.currency_code}"
    high = _money_text(price.amount_high, minor_units=price.currency_minor_units)
    return f"{low}–{high} {price.currency_code}"


def _result_card(*, resolution: dict[str, object], submission) -> dict[str, object]:
    if submission.error is not None or submission.money_context is None:
        return {
            "token": resolution["token"],
            "scope_label": resolution["scope_label"],
            "country_code": resolution["country_code"],
            "city_slug": resolution["city_slug"],
            "currency_code": resolution["currency_code"],
            "available": False,
            "error": "Reference rate is temporarily unavailable for this destination.",
        }

    context = submission.money_context
    conversion = context.conversion
    minor_units = int(resolution["minor_units"])
    provider = ", ".join(key.upper() for key in conversion.quote.provider_keys)
    if not provider:
        provider = "Exact same-currency rate"

    price_rows = ()
    if context.destination_context is not None:
        price_rows = tuple(
            {
                "label": price.label,
                "price_text": _price_text(price),
                "scope_label": price.scope_label,
                "observed_at": date_format(price.observed_at, "j M Y"),
                "source_name": price.source_name,
                "source_url": price.source_url,
            }
            for price in context.destination_context.prices[:3]
        )

    converter_params = {
        "load": "1",
        "destination_country": resolution["country_code"],
        "destination_currency": resolution["currency_code"],
    }
    if resolution["city_slug"]:
        converter_params["destination_city_slug"] = resolution["city_slug"]

    return {
        "token": resolution["token"],
        "scope_label": resolution["scope_label"],
        "country_code": resolution["country_code"],
        "city_slug": resolution["city_slug"],
        "currency_code": resolution["currency_code"],
        "available": True,
        "converted_amount": _money_text(conversion.output_amount, minor_units=minor_units),
        "rate": format(conversion.quote.rate, "f"),
        "effective_date": date_format(conversion.quote.effective_date, "j M Y"),
        "provider": provider,
        "stale": conversion.stale,
        "context_state": context.destination_state.value,
        "price_rows": price_rows,
        "converter_url": f"{reverse('converter')}?{urlencode(converter_params)}",
    }


@require_http_methods(["GET", "POST"])
def explore_same_amount_view(
    request: HttpRequest,
    *,
    latest_gateway_factory: LatestGatewayFactory,
) -> HttpResponse:
    """Apply one explicit source amount independently across 2–4 destinations."""

    form = ExploreAmountForm(request.POST if request.method == "POST" else None)
    cards: tuple[dict[str, object], ...] = ()
    response_status = 200

    if request.method == "POST":
        if not form.is_valid():
            response_status = 422
        else:
            cleaned = form.cleaned_data
            shared_gateway = latest_gateway_factory()

            def shared_gateway_factory() -> LatestQuoteGateway:
                return shared_gateway

            built = []
            for resolution in cleaned["destination_resolutions"]:
                submission = run_converter_submission(
                    ConverterSubmissionCommand(
                        amount=cleaned["amount_decimal"],
                        source_country="",
                        source_currency=cleaned["source_currency"],
                        destination_country=resolution["country_code"],
                        destination_currency=resolution["currency_code"],
                        destination_city_slug=resolution["city_slug"],
                    ),
                    latest_gateway_factory=shared_gateway_factory,
                    historical_gateway_factory=_historical_gateway_not_allowed,
                    context_as_of=timezone.localdate(),
                )
                built.append(_result_card(resolution=resolution, submission=submission))
            cards = tuple(built)

    return render(
        request,
        "pages/explore_same_amount.html",
        {
            "form": form,
            "cards": cards,
            "reference_data_ready": form.reference_data_ready,
            "successful_card_count": sum(bool(card.get("available")) for card in cards),
        },
        status=response_status,
    )
