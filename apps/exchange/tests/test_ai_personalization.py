from __future__ import annotations

from datetime import date
from decimal import Decimal

from apps.exchange.ai.intents import ExplanationIntent
from apps.exchange.ai.packets import build_explanation_packet
from apps.exchange.domain import ObservationGranularity
from apps.exchange.trusted_snapshot import TrustedConversionSnapshot


def _snapshot() -> TrustedConversionSnapshot:
    return TrustedConversionSnapshot(
        input_amount=Decimal("100.00"),
        output_amount=Decimal("17450"),
        base_currency="EUR",
        quote_currency="JPY",
        rate=Decimal("174.50"),
        requested_date=None,
        effective_date=date(2026, 9, 18),
        historical=False,
        observation_granularity=ObservationGranularity.DAILY,
        provider_keys=("ecb",),
        stale=False,
    )


def test_personalization_changes_packet_presentation_contract_not_grounded_facts():
    baseline = build_explanation_packet(
        _snapshot(),
        intent=ExplanationIntent.OVERVIEW,
    )
    personalized = build_explanation_packet(
        _snapshot(),
        intent=ExplanationIntent.OVERVIEW,
        locale="uk",
        focus_instruction_suffix=(
            "The user explicitly prefers concise explanations. "
            "Prioritize supplied price facts only when relevant."
        ),
    )

    assert personalized.locale == "uk"
    assert personalized.focus_instruction.startswith(baseline.focus_instruction)
    assert "concise explanations" in personalized.focus_instruction
    assert personalized.facts == baseline.facts
    assert personalized.allowed_currencies == baseline.allowed_currencies
    assert personalized.allowed_dates == baseline.allowed_dates
    assert personalized.allowed_numbers == baseline.allowed_numbers
    assert personalized.packet_hash != baseline.packet_hash
