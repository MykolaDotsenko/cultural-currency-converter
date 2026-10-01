from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.countries.models import City, Country, CountryCurrency, Currency
from apps.culture.city_health import (
    CITY_COVERAGE_CORE_CATEGORIES,
    build_city_coverage_health,
)
from apps.culture.models import TypicalPrice, TypicalPriceCategory
from apps.culture.price_quality import PRICE_CONTEXT_MAX_AGE


@pytest.fixture
def city_health_data(db):
    japan = Country.objects.create(iso2="JP", iso3="JPN", name="Japan")
    jpy = Currency.objects.create(code="JPY", name="Japanese yen", minor_units=0)
    eur = Currency.objects.create(code="EUR", name="Euro")
    CountryCurrency.objects.create(
        country=japan,
        currency=jpy,
        is_primary=True,
        source="https://example.org/jpy",
    )
    tokyo = City.objects.create(country=japan, slug="tokyo", name="Tokyo")
    osaka = City.objects.create(country=japan, slug="osaka", name="Osaka")
    return japan, jpy, eur, tokyo, osaka


def _price(
    *,
    country,
    currency,
    category,
    label,
    observed_at,
    city=None,
    source_name="Reviewed source",
    source_url="https://example.org/price",
    verified_at=datetime(2026, 9, 20, tzinfo=UTC),
):
    return TypicalPrice.objects.create(
        country=country,
        city_ref=city,
        category=category,
        label=label,
        amount_low=Decimal("500"),
        currency=currency,
        source_name=source_name,
        source_url=source_url,
        observed_at=observed_at,
        verified_at=verified_at,
        is_published=True,
    )


@pytest.mark.django_db
def test_city_health_classifies_runtime_usable_and_maintenance_gap_categories(city_health_data):
    japan, jpy, _eur, tokyo, _osaka = city_health_data
    as_of = date(2026, 10, 1)

    _price(
        country=japan,
        currency=jpy,
        category=TypicalPriceCategory.TRANSIT,
        label="Tokyo transit",
        observed_at=as_of,
        city=tokyo,
    )
    _price(
        country=japan,
        currency=jpy,
        category=TypicalPriceCategory.COFFEE,
        label="National coffee",
        observed_at=as_of,
    )
    _price(
        country=japan,
        currency=jpy,
        category=TypicalPriceCategory.CASUAL_MEAL,
        label="Stale Tokyo meal",
        observed_at=as_of - PRICE_CONTEXT_MAX_AGE - timedelta(days=1),
        city=tokyo,
    )
    _price(
        country=japan,
        currency=jpy,
        category=TypicalPriceCategory.GROCERIES,
        label="Broken provenance groceries",
        observed_at=as_of,
        city=tokyo,
        source_url="https://user:secret@example.org/groceries",
    )

    report = build_city_coverage_health(
        as_of=as_of,
        country_code="jp",
        city_slug="TOKYO",
    )[0]

    assert report.currency_code == "JPY"
    assert report.total_supported_categories == 2
    assert report.fresh_categories == (TypicalPriceCategory.TRANSIT,)
    assert report.stale_categories == (TypicalPriceCategory.CASUAL_MEAL,)
    assert report.national_fallback_categories == (TypicalPriceCategory.COFFEE,)
    assert report.provenance_gap_categories == (TypicalPriceCategory.GROCERIES,)
    assert report.coverage_score == 40
    assert report.summary == (
        "1/4 fresh core city categories; 1 fresh national fallback; "
        "1 stale city categories; 1 provenance gaps."
    )


@pytest.mark.django_db
def test_fresh_city_category_suppresses_same_category_national_fallback(city_health_data):
    japan, jpy, _eur, tokyo, _osaka = city_health_data
    as_of = date(2026, 10, 1)
    _price(
        country=japan,
        currency=jpy,
        category=TypicalPriceCategory.COFFEE,
        label="Tokyo coffee",
        observed_at=as_of,
        city=tokyo,
    )
    _price(
        country=japan,
        currency=jpy,
        category=TypicalPriceCategory.COFFEE,
        label="National coffee",
        observed_at=as_of,
    )

    report = build_city_coverage_health(
        as_of=as_of,
        country_code="JP",
        city_slug="tokyo",
    )[0]

    assert report.fresh_categories == (TypicalPriceCategory.COFFEE,)
    assert report.national_fallback_categories == ()
    assert report.coverage_score == 25


@pytest.mark.django_db
def test_wrong_currency_rows_do_not_count_as_coverage(city_health_data):
    japan, _jpy, eur, tokyo, _osaka = city_health_data
    as_of = date(2026, 10, 1)
    _price(
        country=japan,
        currency=eur,
        category=TypicalPriceCategory.COFFEE,
        label="Wrong-currency coffee",
        observed_at=as_of,
        city=tokyo,
    )

    report = build_city_coverage_health(
        as_of=as_of,
        country_code="JP",
        city_slug="tokyo",
    )[0]

    assert report.currency_code == "JPY"
    assert report.total_supported_categories == 0
    assert report.fresh_categories == ()
    assert report.coverage_score == 0


@pytest.mark.django_db
def test_other_category_is_reported_but_does_not_inflate_core_score(city_health_data):
    japan, jpy, _eur, tokyo, _osaka = city_health_data
    as_of = date(2026, 10, 1)
    _price(
        country=japan,
        currency=jpy,
        category=TypicalPriceCategory.OTHER,
        label="Other local anchor",
        observed_at=as_of,
        city=tokyo,
    )

    report = build_city_coverage_health(
        as_of=as_of,
        country_code="JP",
        city_slug="tokyo",
    )[0]

    assert TypicalPriceCategory.OTHER not in CITY_COVERAGE_CORE_CATEGORIES
    assert report.total_supported_categories == 1
    assert report.fresh_categories == (TypicalPriceCategory.OTHER,)
    assert report.coverage_score == 0


@pytest.mark.django_db
def test_report_is_stable_alphabetical_by_country_and_city(city_health_data):
    _japan, _jpy, _eur, _tokyo, _osaka = city_health_data

    reports = build_city_coverage_health(as_of=date(2026, 10, 1))

    assert [(report.country_code, report.city_slug) for report in reports] == [
        ("JP", "osaka"),
        ("JP", "tokyo"),
    ]


@pytest.mark.django_db
def test_json_command_exposes_stable_machine_readable_contract(city_health_data):
    japan, jpy, _eur, tokyo, _osaka = city_health_data
    as_of = date(2026, 10, 1)
    _price(
        country=japan,
        currency=jpy,
        category=TypicalPriceCategory.TRANSIT,
        label="Tokyo transit",
        observed_at=as_of,
        city=tokyo,
    )
    stdout = StringIO()

    call_command(
        "report_city_coverage",
        country="jp",
        city="tokyo",
        as_of=as_of.isoformat(),
        as_json=True,
        stdout=stdout,
    )

    payload = json.loads(stdout.getvalue())
    assert payload == [
        {
            "country_code": "JP",
            "country_name": "Japan",
            "city_slug": "tokyo",
            "city_name": "Tokyo",
            "currency_code": "JPY",
            "total_supported_categories": 1,
            "fresh_categories": ["transit"],
            "stale_categories": [],
            "national_fallback_categories": [],
            "provenance_gap_categories": [],
            "coverage_score": 25,
            "summary": (
                "1/4 fresh core city categories; 0 fresh national fallback; "
                "0 stale city categories; 0 provenance gaps."
            ),
        }
    ]


@pytest.mark.django_db
def test_text_command_labels_score_as_maintenance_coverage(city_health_data):
    stdout = StringIO()

    call_command(
        "report_city_coverage",
        country="JP",
        city="tokyo",
        as_of="2026-10-01",
        stdout=stdout,
    )

    output = stdout.getvalue()
    assert "JP/tokyo · Tokyo · currency=JPY" in output
    assert "score=0/100" in output
    assert "0/4 fresh core city categories" in output


@pytest.mark.django_db
def test_city_filter_requires_country_to_avoid_ambiguous_slug(city_health_data):
    with pytest.raises(CommandError, match="--city requires --country"):
        call_command("report_city_coverage", city="tokyo")


@pytest.mark.django_db
def test_unknown_city_scope_fails_explicitly(city_health_data):
    with pytest.raises(CommandError, match="No active city coverage scope found"):
        call_command("report_city_coverage", country="JP", city="kyoto")


@pytest.mark.django_db
def test_invalid_as_of_date_fails_explicitly(city_health_data):
    with pytest.raises(CommandError, match="--as-of must be YYYY-MM-DD"):
        call_command("report_city_coverage", country="JP", as_of="01-10-2026")
