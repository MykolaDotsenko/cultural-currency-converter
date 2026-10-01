from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from apps.exchange.ai.intents import ExplanationIntent
from apps.exchange.ai.packets import build_explanation_packet
from apps.exchange.ai.providers.deterministic_test import DeterministicTestExplanationDrafter
from apps.exchange.ai.validation import validate_provider_payload
from apps.exchange.domain import ObservationGranularity
from apps.exchange.trusted_snapshot import TrustedConversionSnapshot
from integrations.gemini.errors import AIProviderTimeout


@pytest.fixture
def snapshot() -> TrustedConversionSnapshot:
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
        provider_keys=("browser-quality-fixture",),
        stale=False,
    )


def test_runtime_fixture_returns_validator_clean_grounded_answer(snapshot):
    packet = build_explanation_packet(snapshot, intent=ExplanationIntent.RATE_MEANING)
    provider = DeterministicTestExplanationDrafter()

    result = provider.draft(packet)
    validated = validate_provider_payload(result.payload, packet=packet)

    assert validated.generated is True
    assert result.provider_model == "deterministic-browser-fixture"
    assert result.response_id == "fixture-rate_meaning"
    cited = {
        fact_id
        for insight in (
            validated.short_answer,
            *validated.key_factors,
            validated.watch_out_for,
            validated.next_step,
        )
        for fact_id in insight.supporting_fact_ids
    }
    assert set(packet.required_fact_ids) <= cited


def test_runtime_fixture_exercises_timeout_fallback_path(snapshot):
    packet = build_explanation_packet(snapshot, intent=ExplanationIntent.PAYMENT_DIFFERENCE)
    provider = DeterministicTestExplanationDrafter()

    with pytest.raises(AIProviderTimeout, match="fixture timeout"):
        provider.draft(packet)
