from __future__ import annotations

from decimal import Decimal
from urllib.parse import urlencode

from django.conf import settings
from django.urls import reverse
from django.utils.formats import date_format

from apps.exchange.ai.contextual import (
    COMPARISON_AI_CAPABILITY,
    ComparisonExplanationIntent,
    available_comparison_explanation_intents,
    build_comparison_explanation_packet,
)
from apps.exchange.ai.packet_tokens import GroundedPacketTokenError, build_grounded_packet_token
from apps.exchange.budget import BudgetBand, BudgetInterpretationState
from apps.exchange.comparison import DestinationComparison, DestinationComparisonSide


def _money_text(value: Decimal, *, minor_units: int) -> str:
    return f"{value:.{minor_units}f}"


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _band_label(band: BudgetBand | None) -> str:
    labels = {
        BudgetBand.BELOW_REFERENCE: "Below this reference basket",
        BudgetBand.WITHIN_REFERENCE: "Within this reference range",
        BudgetBand.ABOVE_REFERENCE: "Above this reference basket",
    }
    return labels.get(band, "")


def _destination_token(side: DestinationComparisonSide) -> str:
    return (
        f"{side.destination_country_code}:{side.destination_city_slug}"
        if side.destination_city_slug
        else side.destination_country_code
    )


def _side_action_urls(side: DestinationComparisonSide) -> dict[str, str]:
    token = _destination_token(side)
    quote = side.conversion.quote
    converter_params = {
        "convert": "1",
        "amount": format(side.conversion.input_amount, "f"),
        "source_currency": quote.base_currency,
        "destination_country": side.destination_country_code,
        "destination_currency": side.currency_code,
        "rate_mode": "latest",
    }
    if side.destination_city_slug:
        converter_params["destination_city_slug"] = side.destination_city_slug

    city_profile_url = ""
    if side.destination_city_slug:
        city_profile_url = reverse(
            "city_money_profile",
            kwargs={
                "country_code": side.destination_country_code,
                "city_slug": side.destination_city_slug,
            },
        )

    return {
        "converter_url": f"{reverse('converter')}?{urlencode(converter_params)}",
        "budget_url": (
            f"{reverse('destination_mode')}?{urlencode({'destination': token})}"
        ),
        "city_profile_url": city_profile_url,
    }


def _side_component(
    side: DestinationComparisonSide,
    *,
    destination_name: str,
    minor_units: int,
) -> dict[str, object]:
    budget = side.budget
    payment = side.payment_guidance

    actions = _side_action_urls(side)

    return {
        "destination_name": destination_name,
        "destination_country_code": side.destination_country_code,
        "destination_city_slug": side.destination_city_slug,
        "currency_code": side.currency_code,
        "converted_amount": _money_text(side.converted_amount, minor_units=minor_units),
        "rate": _decimal_text(side.conversion.quote.rate),
        "effective_date": date_format(side.conversion.quote.effective_date, "j M Y"),
        "providers": (
            ", ".join(key.upper() for key in side.conversion.quote.provider_keys)
            or "Provider attribution unavailable"
        ),
        "stale": side.conversion.stale,
        "context_state": side.destination_state.value,
        "context_as_of": date_format(side.context_as_of, "j M Y"),
        **actions,
        "budget": {
            "complete": budget.state is BudgetInterpretationState.COMPLETE,
            "band_label": _band_label(budget.band),
            "available_budget": _money_text(
                budget.available_destination_budget,
                minor_units=minor_units,
            ),
            "daily_budget_per_person": _money_text(
                budget.daily_budget_per_person,
                minor_units=minor_units,
            ),
            "reference_low": _money_text(
                budget.known_reference_total_low,
                minor_units=minor_units,
            ),
            "reference_high": _money_text(
                budget.known_reference_total_high,
                minor_units=minor_units,
            ),
            "missing_categories": tuple(
                category.replace("_", " ").title() for category in budget.missing_categories
            ),
            "lines": tuple(
                {
                    "category": line.category,
                    "label": line.label,
                    "scope_label": line.scope_label,
                    "units": _decimal_text(line.units_per_person_per_day),
                    "daily_low": _money_text(
                        line.per_person_daily_low,
                        minor_units=minor_units,
                    ),
                    "daily_high": _money_text(
                        line.per_person_daily_high,
                        minor_units=minor_units,
                    ),
                    "total_low": _money_text(line.total_low, minor_units=minor_units),
                    "total_high": _money_text(line.total_high, minor_units=minor_units),
                    "observed_at": date_format(line.observed_at, "j M Y"),
                    "confidence": line.confidence,
                    "source_name": line.source_name,
                    "source_url": line.source_url,
                }
                for line in budget.lines
            ),
        },
        "payment": (
            {
                "summary": payment.summary,
                "cash_usage": payment.cash_usage,
                "dcc_warning": payment.dcc_warning,
                "source_name": payment.source_name,
                "source_url": payment.source_url,
                "verified_at": date_format(payment.verified_at, "j M Y"),
            }
            if payment is not None
            else None
        ),
    }


def build_destination_comparison_component(
    comparison: DestinationComparison,
    *,
    left_destination_name: str,
    right_destination_name: str,
    source_minor_units: int,
    left_minor_units: int,
    right_minor_units: int,
) -> dict[str, object]:
    """Build one descriptive, non-ranking presentation contract."""

    ai_explanation = None
    if settings.AI_RUNTIME_EXPLANATION_ENABLED:
        try:
            prompts = []
            for spec in available_comparison_explanation_intents():
                packet = build_comparison_explanation_packet(
                    comparison,
                    left_destination_name=left_destination_name,
                    right_destination_name=right_destination_name,
                    intent=ComparisonExplanationIntent(spec.intent_id),
                )
                prompts.append(
                    {
                        "id": spec.intent_id,
                        "label": spec.label,
                        "question": spec.question,
                        "token": build_grounded_packet_token(
                            packet,
                            capability=COMPARISON_AI_CAPABILITY,
                        ),
                    }
                )
        except GroundedPacketTokenError:
            prompts = []
        if prompts:
            ai_explanation = {"prompts": tuple(prompts)}

    return {
        "source_amount": _money_text(
            comparison.source_amount,
            minor_units=source_minor_units,
        ),
        "source_currency_code": comparison.source_currency_code,
        "duration_days": comparison.assumptions.duration_days,
        "travelers": comparison.assumptions.travelers,
        "coverage_complete": comparison.coverage_complete,
        "selected_categories": tuple(
            {
                "label": item.category.replace("_", " ").title(),
                "units": _decimal_text(item.units_per_person_per_day),
            }
            for item in comparison.assumptions.categories
        ),
        "shared_categories": tuple(
            category.replace("_", " ").title() for category in comparison.shared_categories
        ),
        "left": _side_component(
            comparison.left,
            destination_name=left_destination_name,
            minor_units=left_minor_units,
        ),
        "right": _side_component(
            comparison.right,
            destination_name=right_destination_name,
            minor_units=right_minor_units,
        ),
        "ai_explanation": ai_explanation,
    }
