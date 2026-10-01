from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.countries.models import City, Country, CountryCurrency, Currency
from apps.culture.models import TypicalPrice, TypicalPriceCategory
from apps.culture.price_quality import (
    PRICE_CONTEXT_MAX_AGE,
    TypicalPriceQualityCode,
    TypicalPriceQualityInput,
    TypicalPriceUnit,
    canonical_unit_for_category,
    evaluate_typical_price_quality,
)


@pytest.fixture
def price_reference_data(db):
    japan = Country.objects.create(iso2="JP", iso3="JPN", name="Japan")
    jpy = Currency.objects.create(code="JPY", name="Japanese yen", minor_units=0)
    eur = Currency.objects.create(code="EUR", name="Euro")
    CountryCurrency.objects.create(
        country=japan,
        currency=jpy,
        is_primary=True,
        source="https://example.org/jp-jpy",
    )
    tokyo = City.objects.create(country=japan, slug="tokyo", name="Tokyo")
    return japan, jpy, eur, tokyo


def _quality_input(**overrides):
    today = timezone.localdate()
    values = {
        "category": TypicalPriceCategory.COFFEE,
        "unit": TypicalPriceUnit.SERVING,
        "amount_low": Decimal("500"),
        "amount_high": Decimal("650"),
        "country_code": "JP",
        "currency_code": "JPY",
        "current_primary_currency_code": "JPY",
        "city_text": "Tokyo",
        "city_slug": "tokyo",
        "city_country_code": "JP",
        "city_active": True,
        "source_name": "Reviewed source",
        "source_url": "https://example.org/coffee",
        "observed_at": today,
        "verified_at": timezone.now(),
        "is_published": True,
    }
    values.update(overrides)
    return TypicalPriceQualityInput(**values)


def test_canonical_units_are_explicit_for_each_supported_category():
    assert canonical_unit_for_category(TypicalPriceCategory.COFFEE) == TypicalPriceUnit.SERVING
    assert canonical_unit_for_category(TypicalPriceCategory.CASUAL_MEAL) == TypicalPriceUnit.MEAL
    assert canonical_unit_for_category(TypicalPriceCategory.TRANSIT) == TypicalPriceUnit.RIDE
    assert canonical_unit_for_category(TypicalPriceCategory.GROCERIES) == TypicalPriceUnit.BASKET
    assert canonical_unit_for_category(TypicalPriceCategory.OTHER) == TypicalPriceUnit.ITEM


def test_valid_current_city_price_has_no_quality_issues():
    issues = evaluate_typical_price_quality(_quality_input(), today=timezone.localdate())
    assert issues == ()


@pytest.mark.parametrize(
    ("overrides", "expected_code"),
    [
        ({"city_slug": ""}, TypicalPriceQualityCode.CANONICAL_CITY_REQUIRED),
        (
            {"city_country_code": "FI"},
            TypicalPriceQualityCode.CITY_COUNTRY_MISMATCH,
        ),
        ({"city_active": False}, TypicalPriceQualityCode.CITY_INACTIVE),
        ({"unit": TypicalPriceUnit.RIDE}, TypicalPriceQualityCode.CATEGORY_UNIT_MISMATCH),
        (
            {"currency_code": "EUR"},
            TypicalPriceQualityCode.CURRENT_CURRENCY_MISMATCH,
        ),
        ({"source_name": "  "}, TypicalPriceQualityCode.SOURCE_NAME_MISSING),
        (
            {"source_url": "https://user:secret@example.org/coffee"},
            TypicalPriceQualityCode.PROVENANCE_INVALID,
        ),
        ({"verified_at": None}, TypicalPriceQualityCode.VERIFICATION_MISSING),
    ],
)
def test_quality_evaluator_emits_stable_issue_codes(overrides, expected_code):
    issues = evaluate_typical_price_quality(
        _quality_input(**overrides),
        today=timezone.localdate(),
    )
    assert expected_code in {issue.code for issue in issues}


def test_quality_evaluator_marks_future_and_stale_observations():
    today = timezone.localdate()
    future = evaluate_typical_price_quality(
        _quality_input(observed_at=today + timedelta(days=1)),
        today=today,
    )
    stale = evaluate_typical_price_quality(
        _quality_input(observed_at=today - PRICE_CONTEXT_MAX_AGE - timedelta(days=1)),
        today=today,
    )

    assert TypicalPriceQualityCode.OBSERVATION_FUTURE in {issue.code for issue in future}
    assert TypicalPriceQualityCode.OBSERVATION_STALE in {issue.code for issue in stale}


@pytest.mark.django_db
def test_save_fills_canonical_unit_and_city_display(price_reference_data):
    japan, jpy, _eur, tokyo = price_reference_data
    price = TypicalPrice.objects.create(
        country=japan,
        city="  legacy display  ",
        city_ref=tokyo,
        category=TypicalPriceCategory.COFFEE,
        label="  Cup   of coffee ",
        amount_low=Decimal("500"),
        currency=jpy,
        source_name="  Reviewed   source ",
        source_url="https://example.org/coffee",
        observed_at=timezone.localdate(),
    )

    assert price.unit == TypicalPriceUnit.SERVING
    assert price.city == "Tokyo"
    assert price.label == "Cup of coffee"
    assert price.source_name == "Reviewed source"


@pytest.mark.django_db
def test_published_city_price_requires_canonical_city_reference(price_reference_data):
    japan, jpy, _eur, _tokyo = price_reference_data
    price = TypicalPrice(
        country=japan,
        city="Tokyo",
        category=TypicalPriceCategory.COFFEE,
        unit=TypicalPriceUnit.SERVING,
        label="Coffee",
        amount_low=Decimal("500"),
        currency=jpy,
        source_name="Source",
        source_url="https://example.org/coffee",
        observed_at=timezone.localdate(),
        verified_at=timezone.now(),
        is_published=True,
    )

    with pytest.raises(ValidationError, match="canonical City"):
        price.full_clean()


@pytest.mark.django_db
def test_published_price_requires_current_primary_currency(price_reference_data):
    japan, _jpy, eur, tokyo = price_reference_data
    price = TypicalPrice(
        country=japan,
        city_ref=tokyo,
        category=TypicalPriceCategory.COFFEE,
        unit=TypicalPriceUnit.SERVING,
        label="Coffee",
        amount_low=Decimal("5"),
        currency=eur,
        source_name="Source",
        source_url="https://example.org/coffee",
        observed_at=timezone.localdate(),
        verified_at=timezone.now(),
        is_published=True,
    )

    with pytest.raises(ValidationError, match="current primary currency"):
        price.full_clean()


@pytest.mark.django_db
def test_published_price_requires_fresh_observation(price_reference_data):
    japan, jpy, _eur, tokyo = price_reference_data
    price = TypicalPrice(
        country=japan,
        city_ref=tokyo,
        category=TypicalPriceCategory.COFFEE,
        unit=TypicalPriceUnit.SERVING,
        label="Coffee",
        amount_low=Decimal("500"),
        currency=jpy,
        source_name="Source",
        source_url="https://example.org/coffee",
        observed_at=timezone.localdate() - PRICE_CONTEXT_MAX_AGE - timedelta(days=1),
        verified_at=timezone.now(),
        is_published=True,
    )

    with pytest.raises(ValidationError, match="freshness window"):
        price.full_clean()


@pytest.mark.django_db
def test_duplicate_identity_normalizes_label_whitespace_and_case(price_reference_data):
    japan, jpy, _eur, tokyo = price_reference_data
    today = timezone.localdate()
    TypicalPrice.objects.create(
        country=japan,
        city_ref=tokyo,
        category=TypicalPriceCategory.COFFEE,
        label="Cup of Coffee",
        amount_low=Decimal("500"),
        currency=jpy,
        source_name="Source",
        source_url="https://example.org/coffee",
        observed_at=today,
    )
    duplicate = TypicalPrice(
        country=japan,
        city_ref=tokyo,
        category=TypicalPriceCategory.COFFEE,
        unit=TypicalPriceUnit.SERVING,
        label="  cup   OF coffee ",
        amount_low=Decimal("550"),
        currency=jpy,
        source_name="Another source",
        source_url="https://example.org/coffee-2",
        observed_at=today,
    )

    with pytest.raises(ValidationError, match="Duplicate typical-price observation"):
        duplicate.full_clean()


@pytest.mark.django_db
def test_database_rejects_category_unit_mismatch(price_reference_data):
    japan, jpy, _eur, _tokyo = price_reference_data

    with pytest.raises(IntegrityError), transaction.atomic():
        TypicalPrice.objects.create(
            country=japan,
            category=TypicalPriceCategory.COFFEE,
            unit=TypicalPriceUnit.RIDE,
            label="Invalid unit",
            amount_low=Decimal("500"),
            currency=jpy,
            source_name="Source",
            source_url="https://example.org/invalid-unit",
            observed_at=timezone.localdate(),
        )


@pytest.mark.django_db
def test_database_rejects_published_legacy_city_without_canonical_reference(
    price_reference_data,
):
    japan, jpy, _eur, _tokyo = price_reference_data

    with pytest.raises(IntegrityError), transaction.atomic():
        TypicalPrice.objects.create(
            country=japan,
            city="Tokyo",
            category=TypicalPriceCategory.COFFEE,
            label="Legacy city row",
            amount_low=Decimal("500"),
            currency=jpy,
            source_name="Source",
            source_url="https://example.org/legacy-city",
            observed_at=timezone.localdate(),
            verified_at=timezone.now(),
            is_published=True,
        )
