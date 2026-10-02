from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import StringIO
from urllib.parse import parse_qs, urlparse

import pytest
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from apps.countries.models import City, Country
from apps.culture.city_profile import build_city_money_profile, build_city_money_profile_component
from apps.culture.models import (
    TypicalPrice,
    TypicalPriceCategory,
    TypicalPriceConfidence,
    TypicalPriceSourceClass,
    TypicalPriceUnit,
)


@pytest.fixture(autouse=True)
def use_vite_dev_mode(settings):
    # Python-only CI deliberately does not build frontend assets. This mirrors
    # the existing Explore view-test harness while browser CI exercises the
    # production Vite bundle separately.
    settings.VITE_DEV_SERVER_ENABLED = True


@pytest.fixture
def seeded_city_context(db):
    call_command("seed_reference_data", stdout=StringIO())
    call_command("seed_destination_context", stdout=StringIO())


@pytest.mark.django_db
def test_city_money_profile_reuses_canonical_context_and_current_currency(seeded_city_context):
    profile = build_city_money_profile(
        country_code="jp",
        city_slug="TOKYO",
        as_of=date(2026, 10, 1),
    )

    assert profile is not None
    assert profile.scope_label == "Tokyo, Japan"
    assert profile.currency_code == "JPY"
    assert profile.currency_name == "Japanese yen"
    assert profile.direct_price_count == 4
    assert profile.national_fallback_count == 0
    assert profile.earliest_price_observed_at == date(2026, 9, 21)
    assert profile.latest_price_observed_at == date(2026, 10, 1)
    assert {price.category for price in profile.prices} == {
        TypicalPriceCategory.COFFEE,
        TypicalPriceCategory.CASUAL_MEAL,
        TypicalPriceCategory.TRANSIT,
        TypicalPriceCategory.GROCERIES,
    }
    assert all(price.currency_code == "JPY" for price in profile.prices)
    assert profile.payment is not None
    assert profile.payment.source_url.startswith("https://")


@pytest.mark.django_db
def test_city_money_profile_keeps_national_fallback_explicit(seeded_city_context):
    tokyo = City.objects.get(country__iso2="JP", slug="tokyo")
    jpy = TypicalPrice.objects.filter(country__iso2="JP", currency__code="JPY").first().currency

    TypicalPrice.objects.filter(
        city_ref=tokyo,
        category=TypicalPriceCategory.GROCERIES,
    ).delete()
    TypicalPrice.objects.create(
        country=tokyo.country,
        category=TypicalPriceCategory.GROCERIES,
        unit=TypicalPriceUnit.BASKET,
        label="Japan grocery basket",
        amount_low=Decimal("1500"),
        amount_high=Decimal("2200"),
        currency=jpy,
        source_name="National reviewed source",
        source_url="https://example.org/japan-groceries",
        observed_at=date(2026, 10, 1),
        verified_at=timezone.now(),
        source_class=TypicalPriceSourceClass.APPROXIMATE_CONTEXTUAL,
        confidence=TypicalPriceConfidence.MEDIUM,
        display_order=40,
        is_published=True,
    )

    profile = build_city_money_profile(
        country_code="JP",
        city_slug="tokyo",
        as_of=date(2026, 10, 1),
    )

    assert profile is not None
    assert profile.direct_price_count == 3
    assert profile.national_fallback_count == 1
    fallback = next(price for price in profile.prices if not price.city_slug)
    assert fallback.category == TypicalPriceCategory.GROCERIES
    assert fallback.scope_label == "Japan · national estimate"

    component = build_city_money_profile_component(profile)
    fallback_component = next(price for price in component["prices"] if not price["is_city_scope"])
    assert fallback_component["scope"] == "Japan · national estimate"
    assert component["has_national_fallback"] is True


@pytest.mark.django_db
def test_city_money_profile_requires_direct_city_evidence(seeded_city_context):
    japan = Country.objects.get(iso2="JP")
    City.objects.create(country=japan, slug="kyoto", name="Kyoto")

    profile = build_city_money_profile(
        country_code="JP",
        city_slug="kyoto",
        as_of=date(2026, 10, 1),
    )

    assert profile is None


@pytest.mark.django_db
def test_city_profile_action_handoffs_preserve_canonical_scope(seeded_city_context):
    profile = build_city_money_profile(
        country_code="JP",
        city_slug="tokyo",
        as_of=date(2026, 10, 1),
    )
    assert profile is not None

    component = build_city_money_profile_component(profile)
    converter = urlparse(str(component["converter_url"]))
    converter_query = parse_qs(converter.query)
    assert converter.path == reverse("converter")
    assert converter_query["destination_country"] == ["JP"]
    assert converter_query["destination_currency"] == ["JPY"]
    assert converter_query["destination_city_slug"] == ["tokyo"]

    budget = urlparse(str(component["budget_url"]))
    assert budget.path == reverse("destination_mode")
    assert parse_qs(budget.query)["destination"] == ["JP:tokyo"]

    compare = urlparse(str(component["compare_url"]))
    assert compare.path == reverse("destination_comparison")
    assert parse_qs(compare.query)["left_destination"] == ["JP:tokyo"]
    assert component["saved_url"] == reverse("saved_state")


@pytest.mark.django_db
def test_city_money_profile_view_renders_reviewed_scope_without_fx(client, seeded_city_context):
    response = client.get(reverse("city_money_profile", args=("JP", "tokyo")))

    assert response.status_code == 200
    assert b"Tokyo, Japan" in response.content
    assert b"Japanese yen" in response.content
    assert b"Tokyo Metro regular ticket" in response.content
    assert b"does not request a live FX rate" in response.content
    assert b"cost-of-living score" in response.content
    assert b"Convert for Tokyo" in response.content


@pytest.mark.django_db
def test_city_money_profile_view_404s_for_unknown_or_unreviewed_city(client, seeded_city_context):
    unknown = client.get(reverse("city_money_profile", args=("JP", "does-not-exist")))
    assert unknown.status_code == 404

    japan = Country.objects.get(iso2="JP")
    City.objects.create(country=japan, slug="kyoto", name="Kyoto")
    unreviewed = client.get(reverse("city_money_profile", args=("JP", "kyoto")))
    assert unreviewed.status_code == 404


@pytest.mark.django_db
def test_explore_city_card_links_to_city_money_profile(client, seeded_city_context):
    response = client.get(reverse("explore"))

    assert response.status_code == 200
    assert reverse("city_money_profile", args=("JP", "tokyo")).encode() in response.content
    assert b"Tokyo" in response.content
    assert b"JPY" in response.content
    assert b"city money profile" in response.content
    assert b"Convert" in response.content


@pytest.mark.django_db
def test_city_profile_budget_and_compare_handoffs_prefill_city(client, seeded_city_context):
    destination = client.get(reverse("destination_mode"), {"destination": "JP:tokyo"})
    assert destination.status_code == 200
    assert b'<option value="JP:tokyo" selected>' in destination.content

    comparison = client.get(
        reverse("destination_comparison"),
        {"left_destination": "JP:tokyo"},
    )
    assert comparison.status_code == 200
    assert b'<option value="JP:tokyo" selected>' in comparison.content
