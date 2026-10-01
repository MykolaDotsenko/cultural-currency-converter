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


def _insight(text: str, fact_ids: list[str]) -> dict[str, object]:
    return {"text": text, "supporting_fact_ids": fact_ids}


def _valid_payload():
    return {
        "short_answer": _insight(
            "100 EUR is approximately 17450 JPY.",
            ["conversion"],
        ),
        "key_factors": [
            _insight(
                "The displayed rate is 1 EUR = 174.5 JPY and attribution includes ECB.",
                ["rate", "provider"],
            ),
            _insight(
                "The effective observation date is 2026-09-18.",
                ["effective_date"],
            ),
        ],
        "watch_out_for": _insight(
            "Reference exchange rates are informational; payment providers may use different "
            "rates or add fees.",
            ["reference_scope"],
        ),
        "next_step": _insight(
            "Use this reference observation as a comparison point for any provider quote.",
            ["reference_scope"],
        ),
    }


def test_valid_grounded_payload_is_normalized(packet):
    result = validate_provider_payload(_valid_payload(), packet=packet)

    assert result.generated is True
    assert result.source_label == "AI-generated explanation"
    assert len(result.key_factors) == 2
    assert result.key_factors[0].supporting_fact_ids == ("rate", "provider")
    assert result.watch_out_for.supporting_fact_ids == ("reference_scope",)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda payload: payload["short_answer"].update(supporting_fact_ids=["not-a-real-fact"]),
            "unknown fact ID",
        ),
        (
            lambda payload: payload["short_answer"].update(
                text="100 EUR became 17450 JPY because of an economic event."
            ),
            "causal",
        ),
        (
            lambda payload: payload["short_answer"].update(text="You should exchange 100 EUR now."),
            "advice",
        ),
        (
            lambda payload: payload["short_answer"].update(text="100 EUR is a 5% gain."),
            "market interpretation|percentage",
        ),
        (
            lambda payload: payload["short_answer"].update(
                text="100 USD is approximately 17450 JPY."
            ),
            "uppercase code",
        ),
        (
            lambda payload: payload["short_answer"].update(text="The date is 2026-09-19."),
            "unknown date",
        ),
        (
            lambda payload: payload["short_answer"].update(text="The rate is 999 EUR."),
            "unsupported number",
        ),
        (
            lambda payload: payload["short_answer"].update(
                text="<strong>100 EUR</strong> is approximately 17450 JPY."
            ),
            "markup",
        ),
        (
            lambda payload: payload["next_step"].update(
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


def test_market_interpretation_filter_does_not_match_inside_normal_words(packet):
    payload = _valid_payload()
    payload["next_step"] = _insight(
        "Run the conversion again using this reference observation.",
        ["reference_scope"],
    )

    result = validate_provider_payload(payload, packet=packet)

    assert result.next_step.text.startswith("Run the conversion again")


def test_market_interpretation_filter_still_rejects_standalone_gain(packet):
    payload = _valid_payload()
    payload["next_step"] = _insight(
        "This reference shows a gain.",
        ["reference_scope"],
    )

    with pytest.raises(ExplanationValidationError, match="market interpretation"):
        validate_provider_payload(payload, packet=packet)


def test_validator_rejects_extra_schema_fields_even_if_provider_schema_would_normally_block_them(
    packet,
):
    payload = _valid_payload()
    payload["extra"] = "unexpected"

    with pytest.raises(ExplanationValidationError, match="unexpected"):
        validate_provider_payload(payload, packet=packet)


def test_validator_rejects_missing_structured_section(packet):
    payload = _valid_payload()
    payload.pop("next_step")

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
    payload = {
        "short_answer": _insight(
            "100 EUR is approximately 17450 JPY.",
            ["conversion"],
        ),
        "key_factors": [
            _insight("The effective observation date is 2026-09-18.", ["effective_date"])
        ],
        "watch_out_for": _insight(
            "100 EUR is approximately 17450 JPY.",
            ["conversion"],
        ),
        "next_step": _insight(
            "Use the displayed conversion as a reference.",
            ["conversion"],
        ),
    }

    with pytest.raises(ExplanationValidationError, match="required facts"):
        validate_provider_payload(payload, packet=focused)
