from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from apps.exchange.ai.intents import ExplanationIntent
from apps.exchange.ai.packets import build_explanation_packet
from apps.exchange.ai.validation import ExplanationValidationError, validate_provider_payload
from apps.exchange.domain import ObservationGranularity
from apps.exchange.trusted_snapshot import TrustedConversionSnapshot


@pytest.fixture
def packet():
    snapshot = TrustedConversionSnapshot(
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
    return build_explanation_packet(snapshot)


def _valid_payload():
    return {
        "headline": "Reference conversion explained",
        "bullets": [
            {
                "text": "100 EUR is approximately 17450 JPY.",
                "supporting_fact_ids": ["conversion"],
            },
            {
                "text": "The displayed rate is 1 EUR = 174.5 JPY and attribution includes ECB.",
                "supporting_fact_ids": ["rate", "provider"],
            },
            {
                "text": "The effective observation date is 2026-09-18.",
                "supporting_fact_ids": ["effective_date"],
            },
        ],
        "caveat": (
            "Reference exchange rates are informational; payment providers may use different "
            "rates or add fees."
        ),
    }


def test_valid_grounded_payload_is_normalized(packet):
    result = validate_provider_payload(_valid_payload(), packet=packet)

    assert result.generated is True
    assert result.source_label == "AI-generated explanation"
    assert len(result.bullets) == 3
    assert result.bullets[1].supporting_fact_ids == ("rate", "provider")


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda payload: payload["bullets"][0].update(supporting_fact_ids=["not-a-real-fact"]),
            "unknown fact ID",
        ),
        (
            lambda payload: payload["bullets"][0].update(
                text="100 EUR became 17450 JPY because of an economic event."
            ),
            "causal",
        ),
        (
            lambda payload: payload["bullets"][0].update(text="You should exchange 100 EUR now."),
            "advice",
        ),
        (
            lambda payload: payload["bullets"][0].update(text="100 EUR is a 5% gain."),
            "market interpretation|percentage",
        ),
        (
            lambda payload: payload["bullets"][0].update(
                text="100 USD is approximately 17450 JPY."
            ),
            "uppercase code",
        ),
        (
            lambda payload: payload["bullets"][0].update(text="The date is 2026-09-19."),
            "unknown date",
        ),
        (
            lambda payload: payload["bullets"][0].update(text="The rate is 999 EUR."),
            "unsupported number",
        ),
        (
            lambda payload: payload["bullets"][0].update(
                text="<strong>100 EUR</strong> is approximately 17450 JPY."
            ),
            "markup",
        ),
        (
            lambda payload: payload["bullets"][0].update(
                text="See https://example.com for 100 EUR."
            ),
            "markup",
        ),
    ],
)
def test_semantic_validator_rejects_untrusted_extensions(packet, mutation, message):
    payload = _valid_payload()
    mutation(payload)

    with pytest.raises(ExplanationValidationError, match=message):
        validate_provider_payload(payload, packet=packet)


def test_validator_rejects_extra_schema_fields_even_if_provider_schema_would_normally_block_them(
    packet,
):
    payload = _valid_payload()
    payload["extra"] = "unexpected"

    with pytest.raises(ExplanationValidationError, match="unexpected"):
        validate_provider_payload(payload, packet=packet)


def test_packet_hash_is_canonical_and_contains_only_public_conversion_facts(packet):
    encoded = packet.canonical_json()

    assert len(packet.packet_hash) == 64
    assert "EUR" in encoded
    assert "JPY" in encoded
    assert "ECB" in encoded
    assert "email" not in encoded.casefold()
    assert "location" not in encoded.casefold()


def test_selected_question_requires_its_grounding_facts(packet):
    focused = build_explanation_packet(
        TrustedConversionSnapshot(
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
        ),
        intent=ExplanationIntent.PAYMENT_DIFFERENCE,
    )
    payload = _valid_payload()
    payload["bullets"] = [
        {
            "text": "100 EUR is approximately 17450 JPY.",
            "supporting_fact_ids": ["conversion"],
        }
    ]

    with pytest.raises(ExplanationValidationError, match="required facts"):
        validate_provider_payload(payload, packet=focused)
