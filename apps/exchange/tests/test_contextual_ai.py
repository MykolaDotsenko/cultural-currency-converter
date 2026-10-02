from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from apps.culture.services import (
    DestinationContext,
    PaymentContext,
    TypicalPriceContext,
    calculate_purchase_equivalent,
)
from apps.exchange.ai.contextual import (
    BUDGET_AI_CAPABILITY,
    BUDGET_PACKET_VERSION,
    COMPARISON_AI_CAPABILITY,
    BudgetExplanationIntent,
    ComparisonExplanationIntent,
    ContextualExplanationError,
    build_budget_explanation_packet,
    build_comparison_explanation_packet,
    build_contextual_fallback_result,
    explain_contextual_packet,
)
from apps.exchange.ai.contracts import ExplanationPacket, GroundedFact
from apps.exchange.ai.service import RuntimeExplanationService
from apps.exchange.budget import (
    BudgetAssumptions,
    BudgetBasis,
    BudgetCategoryAssumption,
    interpret_budget,
)
from apps.exchange.comparison import compare_destinations
from apps.exchange.domain import DEFAULT_SOURCE_POLICY, ConversionResult, RateQuote
from apps.exchange.money_context import MoneyContext, MoneyContextState


def _conversion(
    *,
    quote_currency: str,
    output_amount: Decimal,
) -> ConversionResult:
    return ConversionResult(
        input_amount=Decimal("100"),
        output_amount=output_amount,
        quote=RateQuote(
            base_currency="EUR",
            quote_currency=quote_currency,
            rate=output_amount / Decimal("100"),
            requested_date=None,
            effective_date=date(2026, 10, 1),
            fetched_at=datetime(2026, 10, 1, 8, tzinfo=UTC),
            provider_policy=DEFAULT_SOURCE_POLICY,
            provider_keys=("ecb",),
            historical=False,
        ),
        stale=False,
    )


def _payment(country_name: str) -> PaymentContext:
    return PaymentContext(
        summary=f"Reviewed payment context for {country_name}.",
        payment_customs="Cards are commonly accepted.",
        cash_usage="Carry some cash when useful.",
        tipping="Follow local tipping guidance.",
        atm_notes="Review disclosed ATM fees.",
        dcc_warning="Review local-currency pricing when DCC is offered.",
        source_name="Official source",
        source_url="https://example.com/payment",
        verified_at=datetime(2026, 9, 30, 8, tzinfo=UTC),
    )


def _price(
    *,
    country_name: str,
    currency_code: str,
    minor_units: int,
    category: str,
    low: Decimal,
    high: Decimal,
    output_amount: Decimal,
    city_name: str = "",
    city_slug: str = "",
) -> TypicalPriceContext:
    return TypicalPriceContext(
        label=category.replace("_", " ").title(),
        category=category,
        city=city_name,
        country_name=country_name,
        currency_code=currency_code,
        currency_minor_units=minor_units,
        amount_low=low,
        amount_high=high,
        observed_at=date(2026, 9, 15),
        source_class="curated_factual",
        confidence="high",
        source_name="Test source",
        source_url="https://example.com/prices",
        equivalent=calculate_purchase_equivalent(output_amount, low, high),
        city_slug=city_slug,
    )


def _context(
    *,
    country_code: str,
    country_name: str,
    currency_code: str,
    output_amount: Decimal,
    minor_units: int,
    categories: tuple[str, ...] = ("coffee", "casual_meal"),
    city_name: str = "",
    city_slug: str = "",
    payment: bool = True,
) -> MoneyContext:
    prices = tuple(
        _price(
            country_name=country_name,
            currency_code=currency_code,
            minor_units=minor_units,
            category=category,
            low=Decimal("100") if currency_code == "JPY" else Decimal("40"),
            high=Decimal("150") if currency_code == "JPY" else Decimal("60"),
            output_amount=output_amount,
            city_name=city_name,
            city_slug=city_slug,
        )
        for category in categories
    )
    destination = DestinationContext(
        country_code=country_code,
        country_name=country_name,
        as_of=date(2026, 10, 1),
        payment=_payment(country_name) if payment else None,
        prices=prices,
        city_slug=city_slug,
        city_name=city_name,
    )
    return MoneyContext(
        conversion=_conversion(
            quote_currency=currency_code,
            output_amount=output_amount,
        ),
        destination_country_code=country_code,
        destination_city_slug=city_slug,
        as_of=date(2026, 10, 1),
        destination_context=destination,
        destination_state=MoneyContextState.AVAILABLE,
    )


def _assumptions(
    *,
    include_transit: bool = False,
) -> BudgetAssumptions:
    categories = [
        BudgetCategoryAssumption("coffee", Decimal("1")),
        BudgetCategoryAssumption("casual_meal", Decimal("2")),
    ]
    if include_transit:
        categories.append(BudgetCategoryAssumption("transit", Decimal("2")))
    return BudgetAssumptions(
        duration_days=2,
        travelers=1,
        categories=tuple(categories),
        basis=BudgetBasis.REFERENCE_CONVERSION,
    )


def test_budget_packet_contains_only_deterministic_result_facts():
    context = _context(
        country_code="JP",
        country_name="Japan",
        currency_code="JPY",
        output_amount=Decimal("3000"),
        minor_units=0,
        city_name="Tokyo",
        city_slug="tokyo",
    )
    interpretation = interpret_budget(
        context,
        assumptions=_assumptions(),
        destination_minor_units=0,
    )

    packet = build_budget_explanation_packet(
        context,
        interpretation,
        intent=BudgetExplanationIntent.OVERVIEW,
    )
    facts = {fact.id: fact.statement for fact in packet.facts}

    assert packet.packet_version == BUDGET_PACKET_VERSION
    assert packet.required_fact_ids == ("available_budget", "trip_assumptions")
    assert packet.allowed_currencies == ("EUR", "JPY")
    assert "Tokyo, Japan" in facts["destination_scope"]
    assert "3000 JPY" in facts["available_budget"]
    assert "2 days" in facts["trip_assumptions"]
    assert "not a full trip-cost forecast" in facts["trust_boundary"]
    assert "cheapest" not in packet.canonical_json().casefold()


def test_budget_packet_preserves_missing_category_and_no_band():
    context = _context(
        country_code="JP",
        country_name="Japan",
        currency_code="JPY",
        output_amount=Decimal("3000"),
        minor_units=0,
        categories=("coffee", "casual_meal"),
    )
    interpretation = interpret_budget(
        context,
        assumptions=_assumptions(include_transit=True),
        destination_minor_units=0,
    )

    packet = build_budget_explanation_packet(
        context,
        interpretation,
        intent=BudgetExplanationIntent.COVERAGE,
    )
    facts = {fact.id: fact.statement for fact in packet.facts}

    assert packet.required_fact_ids == ("coverage",)
    assert "transit" in facts["coverage"]
    assert "No deterministic budget band" in facts["band"]

    fallback = build_contextual_fallback_result(packet, reason="provider unavailable")
    assert fallback.generated is False
    assert fallback.short_answer.supporting_fact_ids == ("coverage",)
    assert fallback.watch_out_for.supporting_fact_ids == ("trust_boundary",)


def test_comparison_packet_keeps_two_scopes_and_payment_context_without_ranking():
    tokyo = _context(
        country_code="JP",
        country_name="Japan",
        currency_code="JPY",
        output_amount=Decimal("3000"),
        minor_units=0,
        city_name="Tokyo",
        city_slug="tokyo",
    )
    norway = _context(
        country_code="NO",
        country_name="Norway",
        currency_code="NOK",
        output_amount=Decimal("1200"),
        minor_units=2,
    )
    comparison = compare_destinations(
        tokyo,
        norway,
        assumptions=_assumptions(),
        left_minor_units=0,
        right_minor_units=2,
    )

    packet = build_comparison_explanation_packet(
        comparison,
        left_destination_name="Tokyo, Japan",
        right_destination_name="Norway",
        intent=ComparisonExplanationIntent.PAYMENT,
    )
    facts = {fact.id: fact.statement for fact in packet.facts}

    assert packet.required_fact_ids == ("left_payment", "right_payment")
    assert packet.allowed_currencies == ("EUR", "JPY", "NOK")
    assert "Tokyo, Japan" in facts["left_conversion"]
    assert "Norway" in facts["right_conversion"]
    assert "Reviewed payment context for Japan" in facts["left_payment"]
    assert "Reviewed payment context for Norway" in facts["right_payment"]
    assert "calculates no winner" in facts["trust_boundary"]
    assert "recommended destination" not in packet.canonical_json().casefold()


def test_comparison_packet_names_partial_coverage_and_absent_payment():
    tokyo = _context(
        country_code="JP",
        country_name="Japan",
        currency_code="JPY",
        output_amount=Decimal("3000"),
        minor_units=0,
    )
    norway = _context(
        country_code="NO",
        country_name="Norway",
        currency_code="NOK",
        output_amount=Decimal("1200"),
        minor_units=2,
        categories=("coffee",),
        payment=False,
    )
    comparison = compare_destinations(
        tokyo,
        norway,
        assumptions=_assumptions(),
        left_minor_units=0,
        right_minor_units=2,
    )

    packet = build_comparison_explanation_packet(
        comparison,
        left_destination_name="Japan",
        right_destination_name="Norway",
        intent=ComparisonExplanationIntent.COVERAGE,
    )
    facts = {fact.id: fact.statement for fact in packet.facts}

    assert "partial" in facts["right_coverage"].casefold()
    assert "casual meal" in facts["right_coverage"]
    assert "No reviewed current payment-guidance record" in facts["right_payment"]
    assert "Coverage is partial" in facts["comparison_coverage"]


def test_contextual_service_disabled_returns_grounded_fallback():
    packet = ExplanationPacket(
        packet_version=BUDGET_PACKET_VERSION,
        locale="en",
        intent_id=BudgetExplanationIntent.COVERAGE.value,
        intent_question="How complete is the evidence?",
        focus_instruction="Explain only coverage.",
        required_fact_ids=("coverage",),
        facts=(
            GroundedFact(id="coverage", statement="All selected categories are sourced."),
            GroundedFact(
                id="trust_boundary",
                statement="This is not an affordability verdict.",
            ),
            GroundedFact(
                id="provenance_scope",
                statement="Evidence remains visible in the application.",
            ),
        ),
        allowed_currencies=(),
        allowed_uppercase_tokens=(),
        allowed_dates=(),
        allowed_numbers=(),
    )
    service = RuntimeExplanationService(
        enabled=False,
        model="disabled-test",
        drafter=None,
    )

    delivery = explain_contextual_packet(
        packet,
        capability=BUDGET_AI_CAPABILITY,
        service=service,
    )

    assert delivery.cache_status == "deterministic_fallback"
    assert delivery.result.generated is False
    assert delivery.result.short_answer.text == "All selected categories are sourced."


def test_contextual_service_rejects_packet_version_capability_crossover():
    packet = ExplanationPacket(
        packet_version=BUDGET_PACKET_VERSION,
        locale="en",
        intent_id=BudgetExplanationIntent.OVERVIEW.value,
        intent_question="Question",
        focus_instruction="Focus",
        required_fact_ids=(),
        facts=(
            GroundedFact(id="trust_boundary", statement="Trust boundary."),
            GroundedFact(id="provenance_scope", statement="Provenance remains visible."),
        ),
        allowed_currencies=(),
        allowed_uppercase_tokens=(),
        allowed_dates=(),
        allowed_numbers=(),
    )
    service = RuntimeExplanationService(
        enabled=False,
        model="disabled-test",
        drafter=None,
    )

    with pytest.raises(ContextualExplanationError, match="Comparison explanation packet"):
        explain_contextual_packet(
            packet,
            capability=COMPARISON_AI_CAPABILITY,
            service=service,
        )
