from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.countries.models import City
from apps.culture.city_health import CITY_COVERAGE_CORE_CATEGORIES, build_city_coverage_health
from apps.culture.models import (
    CulturalProfile,
    StoryMoment,
    StoryMomentStatus,
    TypicalPrice,
    TypicalPriceCategory,
    TypicalPriceConfidence,
    TypicalPriceSourceClass,
)
from apps.culture.services import build_destination_context



@pytest.mark.django_db
def test_story_seed_requires_reference_data_first():
    with pytest.raises(CommandError, match="seed_reference_data"):
        call_command("seed_story_data")


@pytest.mark.django_db
def test_story_seed_is_reviewed_published_and_idempotent():
    call_command("seed_reference_data", stdout=StringIO())

    first = StringIO()
    call_command("seed_story_data", stdout=first)
    second = StringIO()
    call_command("seed_story_data", stdout=second)

    assert StoryMoment.objects.count() == 3
    assert StoryMoment.objects.filter(status=StoryMomentStatus.PUBLISHED).count() == 3
    assert "created=3, existing=0" in first.getvalue()
    assert "created=0, existing=3" in second.getvalue()

    euro_cash = StoryMoment.objects.get(external_id="curated:fi-euro-cash-changeover")
    assert euro_cash.source_name == "European Commission"
    assert euro_cash.countries.filter(iso2="FI").exists()
    assert euro_cash.currencies.filter(code="EUR").exists()


@pytest.mark.django_db
def test_destination_context_seed_requires_reference_data_first():
    with pytest.raises(CommandError, match="seed_reference_data"):
        call_command("seed_destination_context")


@pytest.mark.django_db
def test_destination_context_seed_is_sourced_and_idempotent():
    call_command("seed_reference_data", stdout=StringIO())

    first = StringIO()
    call_command("seed_destination_context", stdout=first)
    second = StringIO()
    call_command("seed_destination_context", stdout=second)

    profile = CulturalProfile.objects.get(country__iso2="JP")
    prices = TypicalPrice.objects.filter(country__iso2="JP").order_by("display_order")

    assert profile.is_published is True
    assert profile.source_name == "Japan National Tourism Organization (JNTO)"
    assert profile.source_url.startswith("https://www.japan.travel/")
    assert prices.count() == 3
    assert list(prices.values_list("category", flat=True)) == [
        TypicalPriceCategory.COFFEE,
        TypicalPriceCategory.CASUAL_MEAL,
        TypicalPriceCategory.TRANSIT,
    ]

    transit = prices.get(category=TypicalPriceCategory.TRANSIT)
    assert transit.city == "Tokyo"
    assert transit.city_ref is not None
    assert transit.city_ref.slug == "tokyo"
    assert transit.city_ref.name == "Tokyo"
    assert transit.amount_low == 180
    assert transit.amount_high == 330
    assert transit.currency.code == "JPY"
    assert transit.source_name == "Tokyo Metro"
    assert transit.source_url.startswith("https://www.tokyometro.jp/")

    assert "created=4, existing=0" in first.getvalue()
    assert "created=0, existing=4" in second.getvalue()


@pytest.mark.django_db
def test_curated_city_wave_one_has_deep_canonical_core_coverage():
    call_command("seed_reference_data", stdout=StringIO())
    call_command("seed_destination_context", stdout=StringIO())

    expected = {
        ("FI", "helsinki"): ("Helsinki", "EUR"),
        ("FI", "turku"): ("Turku", "EUR"),
        ("SE", "stockholm"): ("Stockholm", "SEK"),
        ("DK", "copenhagen"): ("Copenhagen", "DKK"),
        ("NO", "oslo"): ("Oslo", "NOK"),
        ("DE", "berlin"): ("Berlin", "EUR"),
    }

    for (country_code, city_slug), (city_name, currency_code) in expected.items():
        city = City.objects.get(country__iso2=country_code, slug=city_slug)
        assert city.name == city_name
        assert city.is_active is True

        prices = TypicalPrice.objects.filter(city_ref=city, is_published=True)
        assert prices.count() == 4
        assert set(prices.values_list("category", flat=True)) == set(CITY_COVERAGE_CORE_CATEGORIES)
        assert set(prices.values_list("currency__code", flat=True)) == {currency_code}
        assert set(prices.values_list("city", flat=True)) == {city_name}
        assert all(price.source_url.startswith("https://") for price in prices)
        assert all(price.observed_at == date(2026, 10, 1) for price in prices)
        assert all(price.verified_at is not None for price in prices)
        assert all(price.amount_low > 0 for price in prices)

        report = build_city_coverage_health(
            as_of=date(2026, 10, 1),
            country_code=country_code,
            city_slug=city_slug,
        )
        assert len(report) == 1
        assert report[0].fresh_categories == CITY_COVERAGE_CORE_CATEGORIES
        assert report[0].stale_categories == ()
        assert report[0].national_fallback_categories == ()
        assert report[0].provenance_gap_categories == ()
        assert report[0].coverage_score == 100


@pytest.mark.django_db
def test_curated_city_wave_one_preserves_source_trust_classes():
    call_command("seed_reference_data", stdout=StringIO())
    call_command("seed_destination_context", stdout=StringIO())

    wave_prices = TypicalPrice.objects.filter(
        city_ref__country__iso2__in={"FI", "SE", "DK", "NO", "DE"},
        city_ref__slug__in={"helsinki", "turku", "stockholm", "copenhagen", "oslo", "berlin"},
        is_published=True,
    )
    assert wave_prices.count() == 24

    transit = wave_prices.filter(category=TypicalPriceCategory.TRANSIT)
    contextual = wave_prices.exclude(category=TypicalPriceCategory.TRANSIT)

    assert transit.count() == 6
    assert contextual.count() == 18
    assert set(transit.values_list("source_class", flat=True)) == {
        TypicalPriceSourceClass.AUTHORITATIVE
    }
    assert set(transit.values_list("confidence", flat=True)) == {TypicalPriceConfidence.HIGH}
    assert set(contextual.values_list("source_class", flat=True)) == {
        TypicalPriceSourceClass.APPROXIMATE_CONTEXTUAL
    }
    assert set(contextual.values_list("confidence", flat=True)) == {TypicalPriceConfidence.MEDIUM}


@pytest.mark.django_db
def test_curated_city_wave_one_keeps_reviewed_price_ranges_stable():
    call_command("seed_reference_data", stdout=StringIO())
    call_command("seed_destination_context", stdout=StringIO())

    expected_ranges = {
        ("FI", "helsinki", TypicalPriceCategory.COFFEE): ("3.00", "5.70"),
        ("FI", "helsinki", TypicalPriceCategory.CASUAL_MEAL): ("13.70", "25.00"),
        ("FI", "helsinki", TypicalPriceCategory.TRANSIT): ("3.30", "3.50"),
        ("FI", "helsinki", TypicalPriceCategory.GROCERIES): ("5.29", "14.30"),
        ("FI", "turku", TypicalPriceCategory.COFFEE): ("3.00", "5.00"),
        ("FI", "turku", TypicalPriceCategory.CASUAL_MEAL): ("13.00", "25.00"),
        ("FI", "turku", TypicalPriceCategory.TRANSIT): ("3.15", None),
        ("FI", "turku", TypicalPriceCategory.GROCERIES): ("7.37", "10.88"),
        ("SE", "stockholm", TypicalPriceCategory.COFFEE): ("39.00", "75.00"),
        ("SE", "stockholm", TypicalPriceCategory.CASUAL_MEAL): ("129.00", "283.30"),
        ("SE", "stockholm", TypicalPriceCategory.TRANSIT): ("43.00", None),
        ("SE", "stockholm", TypicalPriceCategory.GROCERIES): ("93.00", "205.00"),
        ("DK", "copenhagen", TypicalPriceCategory.COFFEE): ("30.00", "60.00"),
        ("DK", "copenhagen", TypicalPriceCategory.CASUAL_MEAL): ("90.00", "300.00"),
        ("DK", "copenhagen", TypicalPriceCategory.TRANSIT): ("24.00", None),
        ("DK", "copenhagen", TypicalPriceCategory.GROCERIES): ("55.00", "134.34"),
        ("NO", "oslo", TypicalPriceCategory.COFFEE): ("38.17", "80.00"),
        ("NO", "oslo", TypicalPriceCategory.CASUAL_MEAL): ("148.92", "300.00"),
        ("NO", "oslo", TypicalPriceCategory.TRANSIT): ("46.00", None),
        ("NO", "oslo", TypicalPriceCategory.GROCERIES): ("96.40", "218.00"),
        ("DE", "berlin", TypicalPriceCategory.COFFEE): ("2.50", "5.00"),
        ("DE", "berlin", TypicalPriceCategory.CASUAL_MEAL): ("10.00", "30.00"),
        ("DE", "berlin", TypicalPriceCategory.TRANSIT): ("4.00", None),
        ("DE", "berlin", TypicalPriceCategory.GROCERIES): ("5.94", "15.12"),
    }

    actual = {}
    for price in TypicalPrice.objects.filter(
        city_ref__isnull=False,
        city_ref__country__iso2__in={"FI", "SE", "DK", "NO", "DE"},
    ).select_related("country", "city_ref"):
        actual[(price.country.iso2, price.city_ref.slug, price.category)] = (
            format(price.amount_low, ".2f"),
            format(price.amount_high, ".2f") if price.amount_high is not None else None,
        )

    assert actual == expected_ranges


@pytest.mark.django_db
def test_curated_city_wave_one_flows_through_destination_context_without_fallback():
    call_command("seed_reference_data", stdout=StringIO())
    call_command("seed_destination_context", stdout=StringIO())

    context = build_destination_context(
        country_code="FI",
        city_slug="helsinki",
        converted_amount=Decimal("100.00"),
        quote_currency="EUR",
        as_of=date(2026, 10, 1),
        price_limit=4,
    )

    assert context is not None
    assert context.city_slug == "helsinki"
    assert context.city_name == "Helsinki"
    assert tuple(price.category for price in context.prices) == CITY_COVERAGE_CORE_CATEGORIES
    assert all(price.city_slug == "helsinki" for price in context.prices)


@pytest.mark.django_db
def test_destination_context_seed_reports_city_wave_idempotency():
    call_command("seed_reference_data", stdout=StringIO())

    first = StringIO()
    call_command("seed_destination_context", stdout=first)
    second = StringIO()
    call_command("seed_destination_context", stdout=second)

    assert "City price wave 1 is ready: created=24, existing=0." in first.getvalue()
    assert "City price wave 1 is ready: created=0, existing=24." in second.getvalue()
