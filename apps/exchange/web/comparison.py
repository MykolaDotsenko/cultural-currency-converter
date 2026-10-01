from __future__ import annotations

from collections.abc import Callable
from typing import Never

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.exchange.application import ConverterSubmissionCommand, run_converter_submission
from apps.exchange.cache import LatestQuoteGateway
from apps.exchange.comparison import DestinationComparisonError, compare_destinations
from apps.exchange.comparison_presentation import build_destination_comparison_component
from apps.exchange.forms import DestinationComparisonForm


LatestGatewayFactory = Callable[[], LatestQuoteGateway]


def _comparison_category_fields(form: DestinationComparisonForm):
    return tuple(
        form[form.units_field_name(category)]
        for category in form.comparison_categories
        if form.units_field_name(category) in form.fields
    )


def _historical_gateway_not_allowed() -> Never:
    raise AssertionError("Destination comparison must never request a historical quote.")


def _provider_error(side_name: str) -> dict[str, str]:
    return {
        "title": f"{side_name} reference rate is unavailable",
        "detail": (
            "The comparison needs two trusted current conversions. "
            "Nothing has been inferred for the unavailable side; try again shortly."
        ),
    }


@require_http_methods(["GET", "POST"])
def destination_comparison_view(
    request: HttpRequest,
    *,
    latest_gateway_factory: LatestGatewayFactory,
) -> HttpResponse:
    """Compare one source budget across two explicit current destination scopes."""

    form = DestinationComparisonForm(request.POST if request.method == "POST" else None)
    comparison_component = None
    comparison_error = None
    status = 200

    if request.method == "POST":
        if not form.is_valid():
            status = 422
        else:
            cleaned = form.cleaned_data
            shared_gateway = latest_gateway_factory()
            shared_gateway_factory = lambda: shared_gateway
            context_as_of = timezone.localdate()

            left_submission = run_converter_submission(
                ConverterSubmissionCommand(
                    amount=cleaned["amount_decimal"],
                    source_country="",
                    source_currency=cleaned["source_currency"],
                    destination_country=cleaned["left_destination_country"],
                    destination_currency=cleaned["left_destination_currency"],
                    destination_city_slug=cleaned["left_destination_city_slug"],
                ),
                latest_gateway_factory=shared_gateway_factory,
                historical_gateway_factory=_historical_gateway_not_allowed,
                context_as_of=context_as_of,
            )
            if left_submission.error is not None or left_submission.money_context is None:
                comparison_error = _provider_error("Destination A")
                status = 503
            else:
                right_submission = run_converter_submission(
                    ConverterSubmissionCommand(
                        amount=cleaned["amount_decimal"],
                        source_country="",
                        source_currency=cleaned["source_currency"],
                        destination_country=cleaned["right_destination_country"],
                        destination_currency=cleaned["right_destination_currency"],
                        destination_city_slug=cleaned["right_destination_city_slug"],
                    ),
                    latest_gateway_factory=shared_gateway_factory,
                    historical_gateway_factory=_historical_gateway_not_allowed
                    context_as_of=context_as_of,
                )
                if right_submission.error is not None or right_submission.money_context is None:
                    comparison_error = _provider_error("Destination B")
                    status = 503
                else:
                    try:
                        comparison = compare_destinations(
                            left_submission.money_context,
                            right_submission.money_context,
                            assumptions=cleaned["budget_assumptions"],
                            left_minor_units=cleaned["left_destination_minor_units"],
                            right_minor_units=cleaned["right_destination_minor_units"],
                        )
                    except DestinationComparisonError as exc:
                        comparison_error = {
                            "title": "These destinations cannot be compared yet",
                            "detail": str(exc),
                        }
                        status = 422
                    else:
                        comparison_component = build_destination_comparison_component(
                            comparison,
                            left_destination_name=cleaned["left_destination_name"],
                            right_destination_name=cleaned["right_destination_name"],
                            source_minor_units=cleaned["source_minor_units"],
                            left_minor_units=cleaned["left_destination_minor_units"],
                            right_minor_units=cleaned["right_destination_minor_units"],
                        )

    return render(
        request,
        "pages/destination_comparison.html",
        {
            "form": form,
            "comparison_category_fields": _comparison_category_fields(form),
            "comparison": comparison_component,
            "comparison_error": comparison_error,
            "reference_data_ready": form.reference_data_ready,
        },
        status=status,
    )
