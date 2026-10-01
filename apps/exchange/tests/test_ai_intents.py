from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from apps.exchange.ai.intents import (
    ExplanationIntent,
    ExplanationIntentError,
    available_explanation_intents,
    ensure_explanation_intent_available,
    parse_explanation_intent,
)
from apps.exchange.ai.packets import build_explanation_packet
from apps.exchange.domain import ObservationGranularity
from apps.exchange.trusted_snapshot import TrustedConversionSnapshot


@pytest.fixture
def current_snapshot() -> TrustedConversionSnapshot:
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


def test_current_quick_prompts_are_bounded_and_relevant() -> None:
    specs = available_explanation_intents(historical=False, stale=False)

    assert tuple(spec.intent for spec in specs) == (
        ExplanationIntent.RATE_MEANING,
        ExplanationIntent.PAYMENT_DIFFERENCE,
    )


def test_stale_current_conversion_adds_cached_reference_prompt() -> None:
    specs = available_explanation_intents(historical=False, stale=True)

    assert tuple(spec.intent for spec in specs) == (
        ExplanationIntent.RATE_MEANING,
        ExplanationIntent.PAYMENT_DIFFERENCE,
        ExplanationIntent.STALE_REFERENCE,
    )


def test_historical_conversion_uses_historical_prompt_not_payment_prompt() -> None:
    specs = available_explanation_intents(historical=True, stale=False)

    assert tuple(spec.intent for spec in specs) == (
        ExplanationIntent.RATE_MEANING,
        ExplanationIntent.HISTORICAL_CONTEXT,
    )


def test_unknown_prompt_id_is_rejected() -> None:
    with pytest.raises(ExplanationIntentError, match="Unknown explanation question"):
        parse_explanation_intent("anything-you-want")


def test_unavailable_prompt_is_rejected_for_current_conversion() -> None:
    with pytest.raises(ExplanationIntentError, match="not available"):
        ensure_explanation_intent_available(
            ExplanationIntent.HISTORICAL_CONTEXT,
            historical=False,
            stale=False,
        )


def test_legacy_missing_prompt_maps_to_overview() -> None:
    assert parse_explanation_intent(None) is ExplanationIntent.OVERVIEW
    assert parse_explanation_intent("") is ExplanationIntent.OVERVIEW


def test_packet_identity_changes_with_selected_intent(current_snapshot) -> None:
    rate_packet = build_explanation_packet(
        current_snapshot,
        intent=ExplanationIntent.RATE_MEANING,
    )
    payment_packet = build_explanation_packet(
        current_snapshot,
        intent=ExplanationIntent.PAYMENT_DIFFERENCE,
    )

    assert rate_packet.intent_id == "rate_meaning"
    assert payment_packet.intent_id == "payment_difference"
    assert rate_packet.packet_hash != payment_packet.packet_hash
    assert rate_packet.required_fact_ids == ("rate", "effective_date")
    assert payment_packet.required_fact_ids == ("reference_scope",)
