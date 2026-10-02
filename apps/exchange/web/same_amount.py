from __future__ import annotations

from collections.abc import Callable
from typing import Never

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.exchange.application import ConverterSubmissionCommand, run_converter_submission
from apps.exchange.cache import LatestQuoteGateway
from apps.exchange.forms import SameAmountDestinationsForm
from apps.exchange.same_amount import (
    SameAmountDestinationSnapshot,
    compose_same_amount_across_destinations,
)
from apps.exchange.same_amount_presentation import build_same_amount_component

LatestGatewayFactory = Callable[[], LatestQuoteGateway]


def _historical_gateway_not_allowed() -> Never:
    raise AssertionError("Same-amount destination exploration must never request historical FX.")


def _get_initial(request: HttpRequest) -> dict[str, object] | None:
    destinations = tuple(
        value.strip()
        for value in request.GET.getlist("destination")
        if value.strip()
    )
    initial: dict[str, object] = {}
    amount = str(request.GET.get("amount") or "").strip()
    source_currency = str(request.GET.get("source_currency") or "").upper().strip()
    if amount:
        initial["amount"] = amount
    if source_currency:
        initial["source_currency"] = source_currency
    if destinations:
        initial["destinations"] = destinations
    return initial or None


@require_http_methods(["GET", "POST"])
def same_amount_destinations_view(
    request: HttpRequest,
    *,
    latest_gateway_factory: LatestGatewayFactory,
) -> HttpResponse:
    """Show one source amount across several explicit destination scopes."""

    form = SameAmountDestinationsForm(
        request.POST if request.method == "POST" else None,
        initial=_get_initial(request) if request.method == "GET" else None,
    )
    component = None
    status = 200

    if request.method == "POST":
        if not form.is_valid():
            status = 422
        else:
            cleaned = form.cleaned_data
            shared_gateway = latest_gateway_factory()

            def shared_gateway_factory() -> LatestQuoteGateway:
                return shared_gateway

            snapshots: list[SameAmountDestinationSnapshot] = []
            failures: list[dict[str, str]] = []
            context_as_of = timezone.localdate()

            for destination in cleaned["resolved_destinations"]:
                submission = run_converter_submission(
                    ConverterSubmissionCommand(
                        amount=cleaned["amount_decimal"],
                        source_country="",
                        source_currency=cleaned["source_currency"],
                        destination_country=destination["country_code"],
                        destination_currency=destination["currency_code"],
                        destination_city_slug=destination["city_slug"],
                    ),
                    latest_gateway_factory=shared_gateway_factory,
                    historical_gateway_factory=_historical_gateway_not_allowed,
                    context_as_of=context_as_of,
                )

                if (
                    submission.error is not None
                    or submission.conversion is None
                    or submission.money_context is None
                ):
                    failures.append(
                        {
                            "token": destination["token"],
                            "scope_label": destination["scope_label"],
                            "currency_code": destination["currency_code"],
                            "title": "Reference rate unavailable",
                            "detail": (
                                "No amount has been inferred for this destination. "
                                "The other selected destinations remain valid."
                            ),
                        }
                    )
                    continue

                snapshots.append(
                    SameAmountDestinationSnapshot(
                        token=destination["token"],
                        scope_label=destination["scope_label"],
                        country_code=destination["country_code"],
                        city_slug=destination["city_slug"],
                        currency_code=destination["currency_code"],
                        minor_units=destination["minor_units"],
                        context=submission.money_context,
                    )
                )

            if snapshots:
                result = compose_same_amount_across_destinations(tuple(snapshots))
                component = build_same_amount_component(
                    result,
                    source_minor_units=cleaned["source_minor_units"],
                    failed_destinations=tuple(failures),
                )
            else:
                component = {
                    "source_amount": format(cleaned["amount_decimal"], "f"),
                    "source_currency_code": cleaned["source_currency"],
                    "destinations": (),
                    "failed_destinations": tuple(failures),
                    "partial": True,
                }
                status = 503

    return render(
        request,
        "pages/same_amount_destinations.html",
        {
            "form": form,
            "same_amount": component,
            "reference_data_ready": form.reference_data_ready,
        },
        status=status,
    )
