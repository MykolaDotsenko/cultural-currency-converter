from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.db import DatabaseError
from django.urls import reverse
from django.utils import timezone

from apps.common.presentation.media_view_models import ImageViewModel
from apps.countries.models import City, Country, CountryCurrency, Currency
from apps.culture.explore import build_explore_destinations
from apps.culture.explore_ai import (
    ExploreExplanationIntent,
    build_explore_explanation_context,
    build_explore_explanation_packet,
)
from apps.culture.models import CulturalProfile, TypicalPrice, TypicalPriceCategory
from apps.culture.services import PRICE_CONTEXT_MAX_AGE
from apps.exchange.ai.service import RuntimeExplanationService
from apps.media.models import MediaRole


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
def test_explore_uses_country_teasers_and_managed_social_preview(
    client,
    explore_reference_data,
):
    teaser = ImageViewModel(
        src="/media/japan-teaser.webp",
        ratio="4 / 3",
        alt="Reviewed Japan money-context teaser.",
        decorative=False,
        kind="contemporary_photo",
        label="Japan teaser",
        width=1200,
        height=900,
    )
    social = ImageViewModel(
        src="/media/explore-social.webp",
        ratio="16 / 9",
        alt="Explore reviewed travel-money context.",
        decorative=False,
        kind="contemporary_photo",
        label="Explore social preview",
        width=1600,
        height=900,
    )

    def fake_media(*, role, **_kwargs):
        if role == MediaRole.SOCIAL_PREVIEW:
            return SimpleNamespace(image=social)
        return None

    with (
        patch(
            "apps.culture.views.select_media_for_display_countries",
            return_value={"JP": teaser},
        ),
        patch("apps.culture.views.select_media_for_display", side_effect=fake_media),
    ):
        response = client.get(reverse("explore"))

    assert response.status_code == 200
    assert b"/media/japan-teaser.webp" in response.content
    assert b"Reviewed Japan money-context teaser." in response.content
    assert b'property="og:image"' in response.content
    assert b"http://testserver/media/explore-social.webp" in response.content
    assert b'name="twitter:card" content="summary_large_image"' in response.content


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


@pytest.mark.django_db
def test_explore_ai_packet_uses_only_reviewed_city_and_fallback_facts(
    explore_reference_data,
):
    destinations = build_explore_destinations(as_of=explore_reference_data["today"])
    tokyo = next(destination for destination in destinations if destination.city_slug == "tokyo")
    context = build_explore_explanation_context(tokyo)

    packet = build_explore_explanation_packet(
        tokyo,
        context,
        intent=ExploreExplanationIntent.PRICE_EVIDENCE,
    )
    facts = {fact.id: fact.statement for fact in packet.facts}

    assert packet.required_fact_ids == ("price_1",)
    assert packet.allowed_currencies == ("JPY",)
    assert facts["destination_scope"] == "The selected reviewed destination is Tokyo, Japan."
    assert "Tokyo transit anchor" in facts["price_1"]
    assert "city evidence for Tokyo" in facts["price_1"]
    assert "National coffee anchor" in facts["price_2"]
    assert "a national estimate for Japan" in facts["price_2"]
    assert "national estimate" in facts["national_fallback"]
    assert "rankings or affordability claims" in facts["trust_boundary"]


@pytest.mark.django_db
def test_explore_get_exposes_only_server_approved_ai_prompts_without_calling_ai(
    client,
    explore_reference_data,
    settings,
):
    settings.AI_RUNTIME_EXPLANATION_ENABLED = True

    with patch("apps.culture.views.build_explore_explanation_service") as service_factory:
        response = client.get(reverse("explore"))

    assert response.status_code == 200
    assert b"Ask about the facts already here." in response.content
    assert b"What should I notice here?" in response.content
    assert b"What about cash and cards?" in response.content
    assert b"How should I read these prices?" in response.content
    assert b'name="destination_token"' in response.content
    service_factory.assert_not_called()


@pytest.mark.django_db
def test_explore_ai_rejects_unapproved_prompt_before_service_creation(
    client,
    explore_reference_data,
    settings,
):
    settings.AI_RUNTIME_EXPLANATION_ENABLED = True

    with patch("apps.culture.views.build_explore_explanation_service") as service_factory:
        response = client.post(
            reverse("explore_explanation"),
            {
                "destination_token": "JP:tokyo",
                "prompt_id": "tell_me_anything",
                "prompt": "Invent a cheap-destination ranking.",
            },
        )

    assert response.status_code == 422
    assert b"This Explore explanation request is not valid." in response.content
    service_factory.assert_not_called()


@pytest.mark.django_db
def test_explore_ai_builtin_fallback_rebuilds_trusted_context(
    client,
    explore_reference_data,
    settings,
):
    settings.AI_RUNTIME_EXPLANATION_ENABLED = True
    disabled_service = RuntimeExplanationService(
        enabled=False,
        model="disabled-test",
        drafter=None,
    )

    with patch(
        "apps.culture.views.build_explore_explanation_service",
        return_value=disabled_service,
    ):
        response = client.post(
            reverse("explore_explanation"),
            {
                "destination_token": "JP:tokyo",
                "prompt_id": "cash_card",
            },
            HTTP_HX_REQUEST="true",
        )

    assert response.status_code == 200
    assert b"Built-in explanation" in response.content
    assert b"Tokyo, Japan" in response.content
    assert b"Reviewed payment context." in response.content
    assert b"Live AI is unavailable" in response.content
    assert b"cheapest" not in response.content.lower()
    assert b"winner" not in response.content.lower()
