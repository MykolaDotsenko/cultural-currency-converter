from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from io import StringIO

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.utils import timezone

from apps.countries.models import City, Country, Currency
from apps.culture.city_health import CITY_COVERAGE_CORE_CATEGORIES, build_city_coverage_health
from apps.culture.city_profile import build_city_money_profile
from apps.culture.explore import build_explore_destinations
from apps.culture.models import (
    TypicalPrice,
    TypicalPriceCategory,
    TypicalPriceUnit,
)
from apps.culture.presentation import build_destination_context_component
from apps.culture.price_quality import PRICE_CONTEXT_MAX_AGE
from apps.culture.services import build_destination_context

AS_OF = date(2026, 10, 1)


@pytest.fixture
def seeded_context(db):
    call_command("seed_reference_data", stdout=StringIO())
    call_command("seed_destination_context", stdout=StringIO())


@pytest.mark.django_db
def test_national_only_evidence_never_becomes_a_city_price_claim(seeded_context):
    japan = Country.objects.get(iso2="JP")
    City.objects.create(country=japan, slug="kyoto", name="Kyoto")

    context = build_destination_context(
        country_code="JP",
        city_slug="kyoto",
        converted_amount=Decimal("10000"),
        quote_currency="JPY",
        as_of=AS_OF,
        price_limit=6,
    )

    assert context is not None
    assert context.city_slug == "kyoto"
    assert context.city_name == "Kyoto"
    assert context.prices
    assert all(price.city_slug == "" for price in context.prices)
    assert all(price.scope_label == "Japan · national estimate" for price in context.prices)

    component = build_destination_context_component(context, historical=False)
    assert component["prices"]
    assert all(price["scope"] == "Japan · national estimate" for price in component["prices"])

    assert build_city_money_profile(country_code="JP", city_slug="kyoto", as_of=AS_OF) is None


@pytest.mark.django_db
def test_wrong_currency_city_anchor_is_excluded_from_context_and_health(seeded_context):
    japan = Country.objects.get(iso2="JP")
    tokyo = City.objects.get(country=japan, slug="tokyo")
    usd = Currency.objects.get(code="USD")
    wrong_currency = TypicalPrice.objects.create(
        country=japan,
        city_ref=tokyo,
        category=TypicalPriceCategory.OTHER,
        unit=TypicalPriceUnit.ITEM,
        label="Wrong-currency city anchor",
        amount_low=Decimal("10.00"),
        currency=usd,
        source_name="Trust audit fixture",
        source_url="https://example.org/wrong-currency",
        observed_at=AS_OF,
        verified_at=timezone.now(),
        display_order=1,
        is_published=True,
    )

    with pytest.raises(ValidationError, match="current primary currency"):
        wrong_currency.full_clean()

    context = build_destination_context(
        country_code="JP",
        city_slug="tokyo",
        converted_amount=Decimal("10000"),
        quote_currency="JPY",
        as_of=AS_OF,
        price_limit=6,
    )

    assert context is not None
    assert all(price.label != wrong_currency.label for price in context.prices)
    assert all(price.currency_code == "JPY" for price in context.prices)

    report = build_city_coverage_health(
        as_of=AS_OF,
        country_code="JP",
        city_slug="tokyo",
    )
    assert len(report) == 1
    assert report[0].fresh_categories == CITY_COVERAGE_CORE_CATEGORIES
    assert TypicalPriceCategory.OTHER not in report[0].fresh_categories
    assert report[0].coverage_score == 100


@pytest.mark.django_db
def test_stale_only_city_price_context_fails_closed(seeded_context):
    singapore = City.objects.get(country__iso2="SG", slug="singapore")
    stale_date = AS_OF - PRICE_CONTEXT_MAX_AGE - timedelta(days=1)
    updated = TypicalPrice.objects.filter(city_ref=singapore).update(observed_at=stale_date)
    assert updated == 4

    context = build_destination_context(
        country_code="SG",
        city_slug="singapore",
        converted_amount=Decimal("100"),
        quote_currency="SGD",
        as_of=AS_OF,
        price_limit=6,
    )

    assert context is not None
    assert context.prices == ()
    assert (
        build_city_money_profile(
            country_code="SG",
            city_slug="singapore",
            as_of=AS_OF,
        )
        is None
    )

    report = build_city_coverage_health(
        as_of=AS_OF,
        country_code="SG",
        city_slug="singapore",
    )
    assert len(report) == 1
    assert report[0].fresh_categories == ()
    assert report[0].stale_categories == CITY_COVERAGE_CORE_CATEGORIES
    assert report[0].national_fallback_categories == ()
    assert report[0].coverage_score == 0

    destinations = build_explore_destinations(as_of=AS_OF, limit=24)
    assert all(destination.city_slug != "singapore" for destination in destinations)


@pytest.mark.django_db
def test_cross_country_city_reference_is_rejected_and_never_rendered(seeded_context):
    japan = Country.objects.get(iso2="JP")
    helsinki = City.objects.get(country__iso2="FI", slug="helsinki")
    jpy = Currency.objects.get(code="JPY")
    invalid = TypicalPrice.objects.create(
        country=japan,
        city_ref=helsinki,
        category=TypicalPriceCategory.OTHER,
        unit=TypicalPriceUnit.ITEM,
        label="Cross-country city anchor",
        amount_low=Decimal("500"),
        currency=jpy,
        source_name="Trust audit fixture",
        source_url="https://example.org/cross-country",
        observed_at=AS_OF,
        verified_at=timezone.now(),
        display_order=1,
        is_published=True,
    )

    with pytest.raises(ValidationError, match="city must belong"):
        invalid.full_clean()

    context = build_destination_context(
        country_code="JP",
        converted_amount=Decimal("10000"),
        quote_currency="JPY",
        as_of=AS_OF,
        price_limit=6,
    )

    assert context is not None
    assert all(price.label != invalid.label for price in context.prices)
    assert all(price.city_slug != "helsinki" for price in context.prices)
