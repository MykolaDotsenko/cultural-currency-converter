from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.db import DatabaseError
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.countries.models import City, Country, CountryCurrency, Currency
from apps.culture.explore import build_explore_destinations
from apps.culture.models import CulturalProfile, TypicalPrice, TypicalPriceCategory
from apps.culture.services import PRICE_CONTEXT_MAX_AGE
from apps.exchange.ai.contracts import ExplanationInsight, ExplanationResult
from apps.exchange.ai.service import ExplanationDelivery


@pytest.fixture(autouse=True)
def use_vite_dev_mode(settings):
    settings.VITE_DEV_SERVER_ENABLED = True


@pytest.fixture
def explore_reference_data(db):
    today = timezone.localdate()
    japan = Country.objects.create(iso2="JP", iso3="JPN", name="Japan")
    finland = Country.objects.create(iso2="FI", iso3="FIN", name="Finland")
    jpy = Currency.objects.create(code="JPY", name="Japanese yen", minor_units=0)
    eur = Currency.objects.create(code="EUR", name="Euro", minor_units=2)
    CountryCurrency.objects.create(
        country=japan,
        currency=jpy,
        is_primary=True,
        source="test",
    )
    CountryCurrency.objects.create(
        country=finland,
        currency=eur,
        is_primary=True,
        source="test",
    )
    tokyo = City.objects.create(country=japan, slug="tokyo", name="Tokyo")
    osaka = City.objects.create(country=japan, slug="osaka", name="Osaka")

    profile = CulturalProfile.objects.create(
        country=japan,
        summary="Reviewed payment context.",
        payment_customs="Cards are commonly accepted.",
        cash_usage="Cash remains useful.",
        source_name="Official travel source",
        source_url="https://example.org/payment",
        verified_at=timezone.now(),
        is_published=True,
    )
    national_price = TypicalPrice.objects.create(
        country=japan,
        category=TypicalPriceCategory.COFFEE,
        label="National coffee anchor",
        amount_low=Decimal("500"),
        currency=jpy,
        source_name="National source",
        source_url="https://example.org/coffee",
        observed_at=today,
        verified_at=timezone.now(),
        display_order=10,
        is_published=True,
    )
    city_price = TypicalPrice.objects.create(
        country=japan,
        city="Tokyo",
        city_ref=tokyo,
        category=TypicalPriceCategory.TRANSIT,
        label="Tokyo transit anchor",
        amount_low=Decimal("180"),
        amount_high=Decimal("330"),
        currency=jpy,
        source_name="Tokyo source",
        source_url="https://example.org/tokyo-transit",
        observed_at=today,
        verified_at=timezone.now(),
        display_order=20,
        is_published=True,
    )
    return {
        "today": today,
        "japan": japan,
        "finland": finland,
        "jpy": jpy,
        "eur": eur,
        "tokyo": tokyo,
        "osaka": osaka,
        "profile": profile,
        "national_price": national_price,
        "city_price": city_price,
    }


@pytest.mark.django_db
def test_explore_reuses_reviewed_country_and_canonical_city_context(explore_reference_data):
    destinations = build_explore_destinations(as_of=explore_reference_data["today"])

    assert [destination.scope_label for destination in destinations] == [
        "Japan",
        "Tokyo, Japan",
    ]

    national, tokyo = destinations
    assert national.currency_code == "JPY"
    assert national.city_price_anchor_count == 0
    assert national.national_price_anchor_count == 1
    assert national.payment_available is True

    assert tokyo.city_slug == "tokyo"
    assert tokyo.city_price_anchor_count == 1
    assert tokyo.national_price_anchor_count == 1
    assert tokyo.payment_available is True


@pytest.mark.django_db
def test_explore_limit_preserves_combined_country_city_alphabetical_order(
    explore_reference_data,
):
    data = explore_reference_data
    TypicalPrice.objects.create(
        country=data["finland"],
        category=TypicalPriceCategory.COFFEE,
        label="Finland coffee anchor",
        amount_low=Decimal("4.50"),
        currency=data["eur"],
        source_name="Finland source",
        source_url="https://example.org/finland-coffee",
        observed_at=data["today"],
        verified_at=timezone.now(),
        is_published=True,
    )

    destinations = build_explore_destinations(as_of=data["today"], limit=2)

    assert [destination.scope_label for destination in destinations] == [
        "Finland",
        "Japan",
    ]


@pytest.mark.django_db
def test_explore_does_not_create_city_scope_from_unpublished_legacy_city_text_or_national_fallback(
    explore_reference_data,
):
    data = explore_reference_data
    TypicalPrice.objects.create(
        country=data["japan"],
        city="Osaka",
        city_ref=None,
        category=TypicalPriceCategory.CASUAL_MEAL,
        label="Legacy Osaka row",
        amount_low=Decimal("900"),
        currency=data["jpy"],
        source_name="Legacy source",
        source_url="https://example.org/osaka",
        observed_at=data["today"],
        verified_at=timezone.now(),
        is_published=False,
    )

    destinations = build_explore_destinations(as_of=data["today"])

    assert all(destination.city_slug != "osaka" for destination in destinations)
    assert [destination.scope_label for destination in destinations] == [
        "Japan",
        "Tokyo, Japan",
    ]


@pytest.mark.django_db
def test_explore_excludes_stale_price_only_destination(explore_reference_data):
    data = explore_reference_data
    TypicalPrice.objects.create(
        country=data["finland"],
        category=TypicalPriceCategory.COFFEE,
        label="Stale Finland anchor",
        amount_low=Decimal("4.50"),
        currency=data["eur"],
        source_name="Old source",
        source_url="https://example.org/old-coffee",
        observed_at=data["today"] - PRICE_CONTEXT_MAX_AGE - timedelta(days=1),
        verified_at=timezone.now(),
        is_published=True,
    )

    destinations = build_explore_destinations(as_of=data["today"])

    assert all(destination.country_code != "FI" for destination in destinations)


@pytest.mark.django_db
def test_explore_suppresses_invalid_provenance_instead_of_publishing_discovery(
    explore_reference_data,
):
    data = explore_reference_data
    data["profile"].source_url = "https://user:secret@example.org/payment"
    data["profile"].save(update_fields=("source_url",))
    for price in (data["national_price"], data["city_price"]):
        price.source_url = "https://user:secret@example.org/price"
        price.save(update_fields=("source_url",))

    assert build_explore_destinations(as_of=data["today"]) == ()


def test_explore_limit_is_bounded():
    with pytest.raises(ValueError, match="between 1 and 24"):
        build_explore_destinations(limit=25)


@pytest.mark.django_db
def test_explore_page_is_provider_free_and_links_back_to_canonical_converter(
    client,
    explore_reference_data,
):
    with patch("apps.exchange.views.build_latest_quote_gateway") as latest_gateway_factory:
        response = client.get(reverse("explore"))

    assert response.status_code == 200
    assert b"Know the money before you know the place." in response.content
    assert b"Start with what matters to you." in response.content
    assert "Region → country → city.".encode() in response.content
    assert b"Tokyo" in response.content
    assert b"city money profile" in response.content
    assert b"No popularity list" in response.content
    assert b"destination_city_slug=tokyo" in response.content
    assert b"load=1" in response.content
    assert b"left_destination=JP%3Atokyo" in response.content
    assert b"left_destination=JP" in response.content
    assert b'data-place-token="JP:tokyo"' in response.content
    assert b'data-place-token="JP"' in response.content
    assert b"data-save-place" in response.content
    latest_gateway_factory.assert_not_called()


@pytest.mark.django_db
def test_explore_database_failure_degrades_locally(client):
    with patch(
        "apps.culture.views.build_explore_destinations",
        side_effect=DatabaseError("context unavailable"),
    ):
        response = client.get(reverse("explore"))

    assert response.status_code == 200
    assert b"Explore is temporarily unavailable." in response.content
    assert b"The converter and saved travel-money tools remain available." in response.content


@pytest.mark.django_db
def test_explore_programming_error_is_not_silenced(client):
    with (
        patch(
            "apps.culture.views.build_explore_destinations",
            side_effect=RuntimeError("programming bug"),
        ),
        pytest.raises(RuntimeError, match="programming bug"),
    ):
        client.get(reverse("explore"))


@pytest.mark.django_db
def test_explore_collection_failure_degrades_without_hiding_regional_navigation(
    client,
    explore_reference_data,
):
    with patch(
        "apps.culture.views.build_explore_collections",
        side_effect=DatabaseError("collection unavailable"),
    ):
        response = client.get(reverse("explore"))

    assert response.status_code == 200
    assert b"Curated collections are temporarily unavailable." in response.content
    assert "Region → country → city.".encode() in response.content
    assert b"Tokyo" in response.content


@pytest.mark.django_db
def test_explore_navigation_failure_degrades_to_reviewed_flat_destination_list(
    client,
    explore_reference_data,
):
    with patch(
        "apps.culture.views.build_explore_regions",
        side_effect=DatabaseError("navigation unavailable"),
    ):
        response = client.get(reverse("explore"))

    assert response.status_code == 200
    assert b"Regional navigation is temporarily unavailable." in response.content
    assert b"Tokyo, Japan" in response.content
    assert b"View city money profile" in response.content


class StubExploreExplanationService:
    def __init__(self):
        self.packets = []

    def explain_packet(self, packet, *, fallback_factory):
        self.packets.append(packet)
        facts = {fact.id: fact for fact in packet.facts}
        return ExplanationDelivery(
            result=ExplanationResult(
                short_answer=ExplanationInsight(
                    text=facts["destination_identity"].statement,
                    supporting_fact_ids=("destination_identity",),
                ),
                key_factors=(
                    ExplanationInsight(
                        text=facts["currency"].statement,
                        supporting_fact_ids=("currency",),
                    ),
                ),
                watch_out_for=ExplanationInsight(
                    text=facts["reference_scope"].statement,
                    supporting_fact_ids=("reference_scope",),
                ),
                next_step=ExplanationInsight(
                    text=facts["as_of"].statement,
                    supporting_fact_ids=("as_of",),
                ),
                generated=True,
                source_label="AI-generated explanation",
            ),
            cache_status="live",
            packet_hash=packet.packet_hash,
        )


@pytest.mark.django_db
def test_explore_ai_is_optional_and_never_calls_service_on_page_load(
    client,
    explore_reference_data,
):
    with (
        override_settings(AI_RUNTIME_EXPLANATION_ENABLED=True),
        patch("apps.culture.views.build_runtime_explanation_service") as ai_factory,
    ):
        response = client.get(reverse("explore"))

    assert response.status_code == 200
    assert b"Optional AI" in response.content
    assert b"Explain what" in response.content
    assert b'name="destination_token"' in response.content
    assert b'value="JP:tokyo"' in response.content
    assert b'value="explore_overview"' in response.content
    assert b'value="explore_evidence"' in response.content
    assert b"rank places or create new source claims" in response.content
    ai_factory.assert_not_called()


@pytest.mark.django_db
def test_disabled_explore_ai_has_zero_ui_or_endpoint_effect(client, explore_reference_data):
    with override_settings(AI_RUNTIME_EXPLANATION_ENABLED=False):
        page = client.get(reverse("explore"))
        endpoint = client.post(
            reverse("explore_explanation"),
            {"destination_token": "JP:tokyo", "prompt_id": "explore_overview"},
        )

    assert page.status_code == 200
    assert b"Explain what" not in page.content
    assert b"destination_token" not in page.content
    assert endpoint.status_code == 404


@pytest.mark.django_db
def test_explore_ai_rebuilds_reviewed_context_before_service_call(
    client,
    explore_reference_data,
):
    service = StubExploreExplanationService()
    with (
        override_settings(AI_RUNTIME_EXPLANATION_ENABLED=True),
        patch(
            "apps.culture.views.build_runtime_explanation_service",
            return_value=service,
        ),
    ):
        response = client.post(
            reverse("explore_explanation"),
            {
                "destination_token": "JP:tokyo",
                "prompt_id": "explore_overview",
                "prompt": "Please answer a different question.",
            },
            HTTP_HX_REQUEST="true",
        )

    assert response.status_code == 200
    assert b"<html" not in response.content
    assert b"AI-generated explanation" in response.content
    assert b"What matters most in this reviewed destination money context?" in response.content
    assert len(service.packets) == 1
    packet = service.packets[0]
    assert packet.intent_id == "explore_overview"
    assert {"destination_identity", "currency", "price_1", "reference_scope"}.issubset(
        packet.fact_ids
    )
    assert packet.allowed_currencies == ("JPY",)
    assert "https://" not in packet.canonical_json()
    assert "different question" not in packet.canonical_json()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "payload",
    [
        {"destination_token": "XX:unknown", "prompt_id": "explore_overview"},
        {"destination_token": "JP:tokyo", "prompt_id": "unknown_prompt"},
    ],
)
def test_explore_ai_rejects_untrusted_destination_or_prompt_before_service(
    client,
    explore_reference_data,
    payload,
):
    with (
        override_settings(AI_RUNTIME_EXPLANATION_ENABLED=True),
        patch("apps.culture.views.build_runtime_explanation_service") as ai_factory,
    ):
        response = client.post(reverse("explore_explanation"), payload)

    assert response.status_code == 422
    ai_factory.assert_not_called()


@pytest.mark.django_db
def test_explore_ai_database_failure_fails_closed_before_service(
    client,
    explore_reference_data,
):
    with (
        override_settings(AI_RUNTIME_EXPLANATION_ENABLED=True),
        patch(
            "apps.culture.ai_web.build_explore_destinations",
            side_effect=DatabaseError("reviewed context unavailable"),
        ),
        patch("apps.culture.views.build_runtime_explanation_service") as ai_factory,
    ):
        response = client.post(
            reverse("explore_explanation"),
            {"destination_token": "JP:tokyo", "prompt_id": "explore_overview"},
        )

    assert response.status_code == 503
    assert b"temporarily unavailable" in response.content
    ai_factory.assert_not_called()


@pytest.mark.django_db
def test_explore_ai_no_javascript_post_returns_full_page(
    client,
    explore_reference_data,
):
    service = StubExploreExplanationService()
    with (
        override_settings(AI_RUNTIME_EXPLANATION_ENABLED=True),
        patch(
            "apps.culture.views.build_runtime_explanation_service",
            return_value=service,
        ),
    ):
        response = client.post(
            reverse("explore_explanation"),
            {"destination_token": "JP:tokyo", "prompt_id": "explore_evidence"},
        )

    assert response.status_code == 200
    assert b"<html" in response.content
    assert b"Reviewed destination context, explained." in response.content
    assert b"How should I read the scope and freshness" in response.content
    assert b"Back to Explore" in response.content
