from __future__ import annotations

from datetime import date
from io import StringIO

import pytest
from django.core.management import call_command
from django.urls import reverse

from apps.culture.explore_ai import (
    ExploreAIIntent,
    build_explore_ai_packet,
    load_explore_ai_snapshot_token,
)
from apps.exchange.ai.validation import ExplanationValidationError, validate_provider_payload


@pytest.fixture(autouse=True)
def use_vite_dev_mode(settings):
    settings.VITE_DEV_SERVER_ENABLED = True


@pytest.fixture
def seeded_explore_ai(db):
    call_command("seed_reference_data", stdout=StringIO())
    call_command("seed_story_data", stdout=StringIO())
    call_command("seed_destination_context", stdout=StringIO())


@pytest.mark.django_db
def test_explore_ai_get_exposes_only_grounded_reviewed_prompts(client, seeded_explore_ai):
    response = client.get(reverse("explore_context_ai"), {"destination": "JP:tokyo"})

    assert response.status_code == 200
    assert b"Tokyo, Japan" in response.content
    assert b"Everyday money" in response.content
    assert b"Paying here" in response.content
    assert b"Sources &amp; freshness" in response.content
    assert b"no open-ended chatbot" in response.content
    assert b"cannot create prices" in response.content

    snapshot = load_explore_ai_snapshot_token(response.context["explore_ai"]["signed_token"])
    assert snapshot.country_code == "JP"
    assert snapshot.city_slug == "tokyo"
    assert snapshot.currency_code == "JPY"
    assert snapshot.prices
    assert snapshot.as_of <= date.today()


@pytest.mark.django_db
def test_explore_ai_disabled_uses_structured_deterministic_fallback(
    client,
    settings,
    seeded_explore_ai,
):
    settings.AI_RUNTIME_EXPLANATION_ENABLED = False
    landing = client.get(reverse("explore_context_ai"), {"destination": "JP:tokyo"})
    token = landing.context["explore_ai"]["signed_token"]

    response = client.post(
        reverse("explore_context_ai"),
        {
            "explore_context_token": token,
            "prompt_id": ExploreAIIntent.LOCAL_MONEY.value,
        },
    )

    assert response.status_code == 200
    assert b"Built-in explanation" in response.content
    assert b"reviewed" in response.content
    assert b"Live AI was not used" in response.content


@pytest.mark.django_db
def test_explore_ai_tampered_token_fails_closed(client, seeded_explore_ai):
    response = client.post(
        reverse("explore_context_ai"),
        {
            "explore_context_token": "tampered",
            "prompt_id": ExploreAIIntent.LOCAL_MONEY.value,
        },
    )

    assert response.status_code == 422
    assert b"no longer valid" in response.content


@pytest.mark.django_db
def test_explore_ai_unknown_destination_is_not_manufactured(client, seeded_explore_ai):
    response = client.get(reverse("explore_context_ai"), {"destination": "JP:missing"})

    assert response.status_code == 404


@pytest.mark.django_db
def test_explore_ai_packet_rejects_provider_numbers_not_in_reviewed_context(
    client,
    seeded_explore_ai,
):
    landing = client.get(reverse("explore_context_ai"), {"destination": "JP:tokyo"})
    snapshot = load_explore_ai_snapshot_token(landing.context["explore_ai"]["signed_token"])
    spec = next(
        spec
        for spec in landing.context["explore_ai"]["intents"]
        if spec.intent is ExploreAIIntent.LOCAL_MONEY
    )
    packet = build_explore_ai_packet(snapshot, spec=spec)

    with pytest.raises(ExplanationValidationError, match="unsupported number"):
        validate_provider_payload(
            {
                "short_answer": {
                    "text": "A typical reviewed purchase costs 999999 JPY.",
                    "supporting_fact_ids": ["price_1"],
                },
                "key_factors": [
                    {
                        "text": "Reviewed context is scoped to Tokyo, Japan.",
                        "supporting_fact_ids": ["scope"],
                    }
                ],
                "watch_out_for": {
                    "text": "Missing destination facts must not be inferred.",
                    "supporting_fact_ids": ["evidence_scope"],
                },
                "next_step": {
                    "text": "Use the reviewed destination context.",
                    "supporting_fact_ids": ["scope"],
                },
            },
            packet=packet,
        )
