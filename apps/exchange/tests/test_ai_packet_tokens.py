from __future__ import annotations

import pytest

from apps.exchange.ai.contracts import ExplanationPacket, GroundedFact
from apps.exchange.ai.packet_tokens import (
    GroundedPacketTokenError,
    build_grounded_packet_token,
    load_grounded_packet_token,
)


@pytest.fixture
def packet() -> ExplanationPacket:
    return ExplanationPacket(
        packet_version="exchange.budget_explanation:v1",
        locale="en",
        intent_id="budget_overview",
        intent_question="How should I read this budget interpretation?",
        focus_instruction="Explain only the supplied trusted facts.",
        required_fact_ids=("available_budget",),
        facts=(
            GroundedFact(
                id="available_budget",
                statement="The trusted available amount is 100 EUR.",
            ),
            GroundedFact(
                id="trust_boundary",
                statement="AI explains application-owned facts and cannot replace them.",
            ),
        ),
        allowed_currencies=("EUR",),
        allowed_uppercase_tokens=("AI",),
        allowed_dates=(),
        allowed_numbers=("100",),
    )


def test_grounded_packet_token_round_trip_preserves_canonical_packet(packet):
    token = build_grounded_packet_token(packet, capability="budget_explanation")

    restored = load_grounded_packet_token(
        token,
        expected_capability="budget_explanation",
    )

    assert restored.canonical_json() == packet.canonical_json()
    assert restored.packet_hash == packet.packet_hash


def test_grounded_packet_token_rejects_capability_crossover(packet):
    token = build_grounded_packet_token(packet, capability="budget_explanation")

    with pytest.raises(GroundedPacketTokenError, match="capability"):
        load_grounded_packet_token(
            token,
            expected_capability="comparison_explanation",
        )


def test_grounded_packet_token_rejects_tampering(packet):
    token = build_grounded_packet_token(packet, capability="budget_explanation")

    with pytest.raises(GroundedPacketTokenError, match="invalid"):
        load_grounded_packet_token(
            token + "x",
            expected_capability="budget_explanation",
        )


def test_grounded_packet_builder_rejects_unknown_required_fact():
    invalid = ExplanationPacket(
        packet_version="exchange.budget_explanation:v1",
        locale="en",
        intent_id="budget_overview",
        intent_question="Question",
        focus_instruction="Focus",
        required_fact_ids=("missing",),
        facts=(GroundedFact(id="available_budget", statement="The amount is 10 EUR."),),
        allowed_currencies=("EUR",),
        allowed_uppercase_tokens=(),
        allowed_dates=(),
        allowed_numbers=("10",),
    )

    with pytest.raises(GroundedPacketTokenError, match="required facts"):
        build_grounded_packet_token(invalid, capability="budget_explanation")
