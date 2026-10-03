from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.utils.formats import date_format

from apps.exchange.ai.contextual import (
    BUDGET_AI_CAPABILITY,
    BudgetExplanationIntent,
    available_budget_explanation_intents,
    build_budget_explanation_packet,
)
from apps.exchange.ai.packet_tokens import GroundedPacketTokenError, build_grounded_packet_token
from apps.exchange.budget import (
    BudgetAssumptions,
    BudgetBand,
    BudgetBasis,
    BudgetInterpretation,
    BudgetInterpretationState,
    available_budget_categories,
)
from apps.exchange.budget_snapshot import build_budget_context_snapshot_token
from apps.exchange.forms import BudgetInterpretationForm
from apps.exchange.money_context import MoneyContext


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


def build_budget_component(
    context: MoneyContext,
    *,
    destination_minor_units: int,
    form: BudgetInterpretationForm | None = None,
    token: str | None = None,
    interpretation: BudgetInterpretation | None = None,
    assumptions: BudgetAssumptions | None = None,
    payment_handoff_token: str = "",
) -> dict[str, object] | None:
    anchors = available_budget_categories(context)
    if not anchors:
        return None

    category_options = tuple((anchor.category, anchor.label) for anchor in anchors)
    budget_form = form or BudgetInterpretationForm(category_options=category_options)
    budget_token = token or build_budget_context_snapshot_token(context)
    budget_basis = interpretation.basis if interpretation is not None else budget_form.budget_basis
    uses_payment_estimate = budget_basis is BudgetBasis.PAYMENT_ESTIMATE
    if uses_payment_estimate and context.payment_estimate is None:
        raise ValueError("Payment-estimate budget presentation requires a payment estimate.")

    destination_context = context.destination_context
    destination_name = (
        destination_context.country_name
        if destination_context is not None
        else context.destination_country_code
    )
    if destination_context is not None and destination_context.city_name:
        destination_name = f"{destination_context.city_name}, {destination_context.country_name}"

    fields = []
    for anchor in anchors:
        field_name = budget_form.units_field_name(anchor.category)
        fields.append(
            {
                "category": anchor.category,
                "field": budget_form[field_name],
                "label": anchor.label,
                "scope_label": anchor.scope_label,
                "is_city_scope": bool(anchor.city_slug),
                "scope_badge": (
                    "City evidence"
                    if anchor.city_slug
                    else (
                        "National fallback"
                        if context.destination_city_slug
                        else "National evidence"
                    )
                ),
                "scope_is_fallback": bool(context.destination_city_slug and not anchor.city_slug),
                "observed_at": date_format(anchor.observed_at, "j M Y"),
                "source_class": anchor.source_class.replace("_", " ").capitalize(),
                "source_name": anchor.source_name,
                "source_url": anchor.source_url,
                "confidence": anchor.confidence,
                "price_low": _money_text(
                    anchor.amount_low,
                    minor_units=anchor.currency_minor_units,
                ),
                "price_high": (
                    _money_text(
                        anchor.amount_high,
                        minor_units=anchor.currency_minor_units,
                    )
                    if anchor.amount_high is not None
                    else ""
                ),
                "currency_code": anchor.currency_code,
            }
        )

    save_payload = None
    if (
        interpretation is not None
        and assumptions is not None
        and interpretation.basis is BudgetBasis.REFERENCE_CONVERSION
    ):
        save_payload = {
            "duration_days": assumptions.duration_days,
            "travelers": assumptions.travelers,
            "categories": tuple(
                {
                    "field_name": BudgetInterpretationForm.units_field_name(item.category),
                    "value": _decimal_text(item.units_per_person_per_day),
                }
                for item in assumptions.categories
            ),
        }

    result_component = None
    if interpretation is not None:
        result_component = {
            "complete": interpretation.state is BudgetInterpretationState.COMPLETE,
            "band_label": _band_label(interpretation.band),
            "available_budget": _money_text(
                interpretation.available_destination_budget,
                minor_units=destination_minor_units,
            ),
            "daily_budget_per_person": _money_text(
                interpretation.daily_budget_per_person,
                minor_units=destination_minor_units,
            ),
            "reference_low": _money_text(
                interpretation.known_reference_total_low,
                minor_units=destination_minor_units,
            ),
            "reference_high": _money_text(
                interpretation.known_reference_total_high,
                minor_units=destination_minor_units,
            ),
            "duration_days": interpretation.duration_days,
            "travelers": interpretation.travelers,
            "missing_categories": tuple(
                category.replace("_", " ").title() for category in interpretation.missing_categories
            ),
            "lines": tuple(
                {
                    "category": line.category,
                    "label": line.label,
                    "scope_label": line.scope_label,
                    "scope_kind": line.scope.value,
                    "scope_badge": (
                        "City evidence"
                        if line.scope.value == "city"
                        else (
                            "National fallback"
                            if interpretation.destination_city_slug
                            else "National evidence"
                        )
                    ),
                    "scope_is_fallback": bool(
                        interpretation.destination_city_slug and line.scope.value == "national"
                    ),
                    "units": _decimal_text(line.units_per_person_per_day),
                    "daily_low": _money_text(
                        line.per_person_daily_low,
                        minor_units=destination_minor_units,
                    ),
                    "daily_high": _money_text(
                        line.per_person_daily_high,
                        minor_units=destination_minor_units,
                    ),
                    "total_low": _money_text(
                        line.total_low,
                        minor_units=destination_minor_units,
                    ),
                    "total_high": _money_text(
                        line.total_high,
                        minor_units=destination_minor_units,
                    ),
                    "observed_at": date_format(line.observed_at, "j M Y"),
                    "source_name": line.source_name,
                    "source_url": line.source_url,
                    "source_class": line.source_class.replace("_", " ").capitalize(),
                    "confidence": line.confidence.capitalize(),
                }
                for line in interpretation.lines
            ),
        }

    ai_explanation = None
    if interpretation is not None and settings.AI_RUNTIME_EXPLANATION_ENABLED:
        try:
            prompts = []
            for spec in available_budget_explanation_intents():
                packet = build_budget_explanation_packet(
                    context,
                    interpretation,
                    intent=BudgetExplanationIntent(spec.intent_id),
                )
                prompts.append(
                    {
                        "id": spec.intent_id,
                        "label": spec.label,
                        "question": spec.question,
                        "token": build_grounded_packet_token(
                            packet,
                            capability=BUDGET_AI_CAPABILITY,
                        ),
                    }
                )
        except GroundedPacketTokenError:
            prompts = []
        if prompts:
            ai_explanation = {"prompts": tuple(prompts)}

    payment_estimate_component = None
    if uses_payment_estimate and context.payment_estimate is not None:
        payment_estimate_component = {
            "estimated_amount": _money_text(
                context.payment_estimate.estimated_destination_amount,
                minor_units=destination_minor_units,
            ),
            "difference_amount": _money_text(
                context.payment_estimate.destination_value_lost,
                minor_units=destination_minor_units,
            ),
            "fx_markup_percent": _decimal_text(context.payment_estimate.fx_markup_percent),
            "source_fixed_fee": _decimal_text(context.payment_estimate.source_fixed_fee),
            "destination_fixed_fee": _money_text(
                context.payment_estimate.destination_fixed_fee,
                minor_units=destination_minor_units,
            ),
            "source_currency": context.conversion.quote.base_currency,
        }

    return {
        "token": budget_token,
        "payment_handoff_token": payment_handoff_token,
        "basis": budget_basis.value,
        "basis_label": (
            "Payment-adjusted estimate" if uses_payment_estimate else "Reference conversion"
        ),
        "form": budget_form,
        "fields": tuple(fields),
        "destination_name": destination_name,
        "currency_code": context.quote_currency,
        "reference_amount": _money_text(
            context.conversion.output_amount,
            minor_units=destination_minor_units,
        ),
        "planning_amount": _money_text(
            (
                context.payment_estimate.estimated_destination_amount
                if uses_payment_estimate and context.payment_estimate is not None
                else context.conversion.output_amount
            ),
            minor_units=destination_minor_units,
        ),
        "payment_estimate": payment_estimate_component,
        "as_of": date_format(context.as_of, "j M Y"),
        "result": result_component,
        "save_payload": save_payload,
        "ai_explanation": ai_explanation,
    }
