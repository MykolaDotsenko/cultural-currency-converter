from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from apps.culture.explore import ExploreDestination
from apps.culture.services import (
    DestinationContext,
    PaymentContext,
    PurchaseEquivalent,
    TypicalPriceContext,
)
from apps.exchange.ai.explore import (
    ExploreExplanationIntent,
    build_explore_explanation_packet,
    build_explore_fallback_result,
)
from apps.exchange.ai.validation import ExplanationValidationError, validate_provider_payload


@pytest.fixture
def explore_packet():
    destination = ExploreDestination(
        country_code="JP",
        country_name="Japan",
        currency_code="JPY",
        city_slug="tokyo",
        city_name="Tokyo",
        city_price_anchor_count=1,
        national_price_anchor_count=1,
        payment_available=True,
        latest_price_observed_at=date(2026, 9, 20),
        payment_verified_at=date(2026, 9, 19),
    )
    context = DestinationContext(
        country_code="JP",
        country_name="Japan",
        city_slug="tokyo",
        city_name="Tokyo",
        as_of=date(2026, 9, 21),
        prices=(
            TypicalPriceContext(
                label="Metro ride",
                category="transit",
                city="Tokyo",
                country_name="Japan",
                currency_code="JPY",
                currency_minor_units=0,
                amount_low=Decimal("180"),
                amount_high=Decimal("330"),
                observed_at=date(2026, 9, 20),
                source_class="official",
                confidence="high",
                source_name="Tokyo Metro",
                source_url="https://example.org/tokyo-metro",
                equivalent=PurchaseEquivalent(
                    minimum_count=Decimal("0"),
                    maximum_count=Decimal("0"),
                    status="zero",
                ),
                city_slug="tokyo",
            ),
        ),
        payment=PaymentContext(
            summary="Cards are common and cash remains useful.",
            payment_customs="Cards are commonly accepted.",
            cash_usage="Cash remains useful for some smaller payments.",
            tipping="Tipping is not generally expected.",
            atm_notes="Cash machines are widely available.",
            dcc_warning="Review dynamic currency conversion before accepting it.",
            source_name="Official travel source",
            source_url="https://example.org/payment",
            verified_at=datetime(2026, 9, 19, 8, tzinfo=UTC),
        ),
    )
    return build_explore_explanation_packet(
        destination,
        context,
        intent=ExploreExplanationIntent.OVERVIEW,
    )


def _payload(*, price_text: str = "Reviewed local price anchor: Metro ride is 180 to 330 JPY."):
    return {
        "short_answer": {
            "text": "Reviewed destination scope: Tokyo, Japan.",
            "supporting_fact_ids": ["destination_identity"],
        },
        "key_factors": [
            {
                "text": "The current primary currency for this reviewed destination scope is JPY.",
                "supporting_fact_ids": ["currency"],
            },
            {
                "text": price_text,
                "supporting_fact_ids": ["price_1"],
            },
        ],
        "watch_out_for": {
            "text": (
                "This is descriptive current destination money context, not an exchange-rate "
                "quote, historical purchasing-power measure, affordability ranking or complete "
                "cost-of-living index."
            ),
            "supporting_fact_ids": ["reference_scope"],
        },
        "next_step": {
            "text": "The reviewed Explore context is evaluated as of 2026-09-21.",
            "supporting_fact_ids": ["as_of"],
        },
    }


def test_explore_packet_contains_only_structured_reviewed_facts(explore_packet):
    fact_ids = explore_packet.fact_ids

    assert {
        "destination_identity",
        "currency",
        "as_of",
        "reference_scope",
        "provenance_boundary",
        "price_1",
        "payment_summary",
        "payment_cards",
        "payment_cash",
        "payment_tipping",
        "payment_atm",
        "payment_dcc",
        "payment_verified",
    }.issubset(fact_ids)
    assert explore_packet.required_fact_ids == ("destination_identity", "reference_scope")
    assert explore_packet.allowed_currencies == ("JPY",)
    assert {"180", "330"}.issubset(set(explore_packet.allowed_numbers))
    assert {"2026-09-19", "2026-09-20", "2026-09-21"}.issubset(
        set(explore_packet.allowed_dates)
    )
    assert "https://" not in explore_packet.canonical_json()
    assert "example.org" not in explore_packet.canonical_json()


def test_explore_packet_validates_grounded_destination_explanation(explore_packet):
    result = validate_provider_payload(_payload(), packet=explore_packet)

    assert result.generated is True
    assert result.short_answer.supporting_fact_ids == ("destination_identity",)
    assert result.watch_out_for.supporting_fact_ids == ("reference_scope",)


@pytest.mark.parametrize(
    "price_text",
    [
        "Reviewed local price anchor: Metro ride is 999 JPY.",
        "Reviewed local price anchor: Metro ride is 180 to 330 USD.",
    ],
)
def test_explore_packet_rejects_literals_not_in_reviewed_facts(explore_packet, price_text):
    with pytest.raises(ExplanationValidationError):
        validate_provider_payload(_payload(price_text=price_text), packet=explore_packet)


def test_explore_fallback_preserves_scope_boundary(explore_packet):
    result = build_explore_fallback_result(
        explore_packet,
        intent=ExploreExplanationIntent.OVERVIEW,
        reason="Live AI is temporarily unavailable.",
    )

    assert result.generated is False
    assert result.source_label == "Built-in explanation"
    assert result.fallback_reason == "Live AI is temporarily unavailable."
    assert result.watch_out_for.supporting_fact_ids == ("reference_scope",)
    assert "affordability ranking" in result.watch_out_for.text
