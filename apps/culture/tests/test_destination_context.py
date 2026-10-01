from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.common.presentation.media_view_models import ImageViewModel
from apps.countries.models import City, Country, Currency
from apps.culture.models import (
    CulturalProfile,
    TypicalPrice,
    TypicalPriceCategory,
    TypicalPriceConfidence,
)
from apps.culture.presentation import build_destination_context_component
from apps.culture.services import (
    PRICE_CONTEXT_MAX_AGE,
    DestinationContext,
    build_destination_context,
    calculate_purchase_equivalent,
)


@pytest.fixture
def japan_context(db):
    japan = Country.objects.create(iso2="JP", iso3="JPN", name="Japan")
    jpy = Currency.objects.create(code="JPY", name="Japanese yen", symbol="¥", minor_units=0)
    tokyo = City.objects.create(country=japan, slug="tokyo", name="Tokyo")
    profile = CulturalProfile.objects.create(
        country=japan,
        summary="Current sourced payment context.",
        payment_customs="Cards are commonly accepted in many urban businesses.",
        cash_usage="Cash remains useful as a fallback.",
        tipping="Tipping is generally not practiced.",
        source_name="JNTO",
        source_url="https://example.org/payment",
        verified_at=timezone.now(),
        is_published=True,
    )
    price = TypicalPrice.objects.create(
        country=japan,
        city="Tokyo",
        city_ref=tokyo,
        category=TypicalPriceCategory.TRANSIT,
        label="Metro ticket",
        amount_low=Decimal("180"),
        amount_high=Decimal("330"),
        currency=jpy,
        source_name="Tokyo Metro",
        source_url="https://example.org/fare",
        observed_at=timezone.localdate(),
        verified_at=timezone.now(),
        confidence=TypicalPriceConfidence.HIGH,
        is_published=True,
    )
    return japan, jpy, profile, price


def test_purchase_equivalent_keeps_decimal_math_and_range_direction():
    value = calculate_purchase_equivalent(Decimal("17450"), Decimal("100"), Decimal("600"))
    assert value.minimum_count == Decimal("17450") / Decimal("600")
    assert value.maximum_count == Decimal("174.5")
    assert value.status == "range"


def test_purchase_equivalent_reports_below_one_without_division_guessing():
    value = calculate_purchase_equivalent(Decimal("50"), Decimal("100"), Decimal("600"))
    assert value.status == "below_one"


@pytest.mark.django_db
def test_published_profile_requires_https_provenance():
    japan = Country.objects.create(iso2="JP", iso3="JPN", name="Japan")
    profile = CulturalProfile(
        country=japan,
        payment_customs="Cards.",
        source_name="Source",
        source_url="http://example.org",
        verified_at=timezone.now(),
        is_published=True,
    )
    with pytest.raises(ValidationError, match="HTTPS"):
        profile.full_clean()


@pytest.mark.django_db
def test_published_profile_rejects_credentialed_https_provenance():
    japan = Country.objects.create(iso2="JP", iso3="JPN", name="Japan")
    profile = CulturalProfile(
        country=japan,
        payment_customs="Cards.",
        source_name="Source",
        source_url="https://user:secret@example.org/payment",
        verified_at=timezone.now(),
        is_published=True,
    )

    with pytest.raises(ValidationError, match="credential-free HTTPS"):
        profile.full_clean()


@pytest.mark.django_db
def test_published_typical_price_rejects_credentialed_https_provenance():
    japan = Country.objects.create(iso2="JP", iso3="JPN", name="Japan")
    jpy = Currency.objects.create(code="JPY", name="Japanese yen")
    price = TypicalPrice(
        country=japan,
        category=TypicalPriceCategory.COFFEE,
        label="Coffee",
        amount_low=Decimal("600"),
        currency=jpy,
        source_name="Source",
        source_url="https://user:secret@example.org/price",
        observed_at=timezone.localdate(),
        verified_at=timezone.now(),
        is_published=True,
    )

    with pytest.raises(ValidationError, match="credential-free HTTPS"):
        price.full_clean()


@pytest.mark.django_db
def test_typical_price_rejects_reversed_range():
    japan = Country.objects.create(iso2="JP", iso3="JPN", name="Japan")
    jpy = Currency.objects.create(code="JPY", name="Japanese yen")
    price = TypicalPrice(
        country=japan,
        category=TypicalPriceCategory.COFFEE,
        label="Coffee",
        amount_low=Decimal("600"),
        amount_high=Decimal("100"),
        currency=jpy,
        source_name="Source",
        source_url="https://example.org",
        observed_at=timezone.localdate(),
    )
    with pytest.raises(ValidationError, match="High price"):
        price.full_clean()


@pytest.mark.django_db
def test_destination_context_preserves_city_scope_and_provenance(japan_context):
    context = build_destination_context(
        country_code="JP",
        converted_amount=Decimal("17450"),
        quote_currency="JPY",
    )
    assert context is not None
    assert context.payment is not None
    assert context.payment.source_name == "JNTO"
    assert len(context.prices) == 1
    assert context.prices[0].scope_label == "Tokyo"
    assert context.prices[0].source_name == "Tokyo Metro"


@pytest.mark.django_db
def test_country_context_uses_one_anchor_per_category(japan_context):
    japan, jpy, _profile, tokyo_transit = japan_context
    today = timezone.localdate()
    national_coffee = TypicalPrice.objects.create(
        country=japan,
        category=TypicalPriceCategory.COFFEE,
        label="National coffee",
        amount_low=Decimal("500"),
        currency=jpy,
        source_name="National source",
        source_url="https://example.org/national-coffee",
        observed_at=today,
        verified_at=timezone.now(),
        display_order=10,
        is_published=True,
    )
    TypicalPrice.objects.create(
        country=japan,
        city="Tokyo",
        city_ref=tokyo_transit.city_ref,
        category=TypicalPriceCategory.COFFEE,
        label="Tokyo coffee",
        amount_low=Decimal("600"),
        currency=jpy,
        source_name="Tokyo source",
        source_url="https://example.org/tokyo-coffee",
        observed_at=today,
        verified_at=timezone.now(),
        display_order=10,
        is_published=True,
    )
    national_meal = TypicalPrice.objects.create(
        country=japan,
        category=TypicalPriceCategory.CASUAL_MEAL,
        label="National meal",
        amount_low=Decimal("900"),
        currency=jpy,
        source_name="National source",
        source_url="https://example.org/national-meal",
        observed_at=today,
        verified_at=timezone.now(),
        display_order=20,
        is_published=True,
    )

    context = build_destination_context(
        country_code="JP",
        converted_amount=Decimal("17450"),
        quote_currency="JPY",
        price_limit=3,
    )

    assert context is not None
    assert [item.label for item in context.prices] == [
        national_coffee.label,
        national_meal.label,
        tokyo_transit.label,
    ]
    assert [item.category for item in context.prices] == [
        TypicalPriceCategory.COFFEE,
        TypicalPriceCategory.CASUAL_MEAL,
        TypicalPriceCategory.TRANSIT,
    ]
    assert context.prices[-1].scope_label == "Tokyo"


@pytest.mark.django_db
def test_city_scoped_context_prefers_city_and_falls_back_only_to_national(japan_context):
    japan, jpy, _profile, tokyo_transit = japan_context
    osaka = City.objects.create(country=japan, slug="osaka", name="Osaka")
    today = timezone.localdate()

    national_coffee = TypicalPrice.objects.create(
        country=japan,
        category=TypicalPriceCategory.COFFEE,
        label="National coffee anchor",
        amount_low=Decimal("500"),
        currency=jpy,
        source_name="National source",
        source_url="https://example.org/national-coffee",
        observed_at=today,
        verified_at=timezone.now(),
        display_order=10,
        is_published=True,
    )
    national_meal = TypicalPrice.objects.create(
        country=japan,
        category=TypicalPriceCategory.CASUAL_MEAL,
        label="National meal anchor",
        amount_low=Decimal("900"),
        currency=jpy,
        source_name="National source",
        source_url="https://example.org/national-meal",
        observed_at=today,
        verified_at=timezone.now(),
        display_order=20,
        is_published=True,
    )
    TypicalPrice.objects.create(
        country=japan,
        city="Osaka",
        city_ref=osaka,
        category=TypicalPriceCategory.CASUAL_MEAL,
        label="Osaka meal",
        amount_low=Decimal("800"),
        currency=jpy,
        source_name="Osaka source",
        source_url="https://example.org/osaka-meal",
        observed_at=today,
        verified_at=timezone.now(),
        display_order=1,
        is_published=True,
    )

    context = build_destination_context(
        country_code="JP",
        city_slug="TOKYO",
        converted_amount=Decimal("17450"),
        quote_currency="JPY",
        price_limit=3,
    )

    assert context is not None
    assert context.city_slug == "tokyo"
    assert context.city_name == "Tokyo"
    assert [item.label for item in context.prices] == [
        tokyo_transit.label,
        national_coffee.label,
        national_meal.label,
    ]
    assert [item.scope_label for item in context.prices] == [
        "Tokyo",
        "Japan · national estimate",
        "Japan · national estimate",
    ]
    assert all(item.label != "Osaka meal" for item in context.prices)


@pytest.mark.django_db
def test_city_scoped_context_does_not_duplicate_category_with_national_fallback(japan_context):
    japan, jpy, _profile, _tokyo_transit = japan_context
    TypicalPrice.objects.create(
        country=japan,
        category=TypicalPriceCategory.TRANSIT,
        label="National transit",
        amount_low=Decimal("200"),
        currency=jpy,
        source_name="National source",
        source_url="https://example.org/national-transit",
        observed_at=timezone.localdate(),
        verified_at=timezone.now(),
        is_published=True,
    )

    context = build_destination_context(
        country_code="JP",
        city_slug="tokyo",
        converted_amount=Decimal("17450"),
        quote_currency="JPY",
    )

    assert context is not None
    assert [item.category for item in context.prices].count(TypicalPriceCategory.TRANSIT) == 1


@pytest.mark.django_db
def test_unknown_city_scope_is_rejected_instead_of_silently_using_national_data(japan_context):
    with pytest.raises(ValueError, match="Destination city is not available"):
        build_destination_context(
            country_code="JP",
            city_slug="kyoto",
            converted_amount=Decimal("17450"),
            quote_currency="JPY",
        )


@pytest.mark.django_db
def test_typical_price_rejects_city_from_another_country(japan_context):
    japan, jpy, _profile, _price = japan_context
    finland = Country.objects.create(iso2="FI", iso3="FIN", name="Finland")
    helsinki = City.objects.create(country=finland, slug="helsinki", name="Helsinki")
    price = TypicalPrice(
        country=japan,
        city="Helsinki",
        city_ref=helsinki,
        category=TypicalPriceCategory.COFFEE,
        label="Invalid city scope",
        amount_low=Decimal("500"),
        currency=jpy,
        source_name="Source",
        source_url="https://example.org/price",
        observed_at=timezone.localdate(),
    )

    with pytest.raises(ValidationError, match="city must belong"):
        price.full_clean()


@pytest.mark.django_db
def test_destination_context_suppresses_invalid_published_provenance(japan_context):
    japan, jpy, profile, price = japan_context
    profile.source_url = "https://user:secret@example.org/payment"
    profile.save(update_fields=("source_url",))
    price.source_url = "https://user:secret@example.org/fare"
    price.save(update_fields=("source_url",))
    fallback = TypicalPrice.objects.create(
        country=japan,
        city="Tokyo",
        city_ref=price.city_ref,
        category=TypicalPriceCategory.CASUAL_MEAL,
        label="Simple meal",
        amount_low=Decimal("900"),
        currency=jpy,
        source_name="Valid fallback",
        source_url="https://example.org/meal",
        observed_at=timezone.localdate(),
        verified_at=timezone.now(),
        display_order=200,
        is_published=True,
    )

    context = build_destination_context(
        country_code="JP",
        converted_amount=Decimal("17450"),
        quote_currency="JPY",
    )

    assert context is not None
    assert context.payment is None
    assert [item.label for item in context.prices] == [fallback.label]


@pytest.mark.django_db
def test_destination_context_suppresses_old_prices_but_keeps_payment(japan_context):
    _japan, _jpy, _profile, price = japan_context
    price.observed_at = timezone.localdate() - PRICE_CONTEXT_MAX_AGE - timedelta(days=1)
    price.save(update_fields=("observed_at",))
    context = build_destination_context(
        country_code="JP",
        converted_amount=Decimal("1000"),
        quote_currency="JPY",
    )
    assert context is not None
    assert context.payment is not None
    assert context.prices == ()


@pytest.mark.django_db
def test_destination_context_does_not_backdate_current_context(japan_context):
    context = build_destination_context(
        country_code="JP",
        converted_amount=Decimal("1000"),
        quote_currency="JPY",
        as_of=date(2026, 9, 21),
    )
    assert context is not None
    component = build_destination_context_component(context, historical=True)
    assert component["historical_notice"]
    assert "not backdated" in component["historical_notice"]


@pytest.mark.django_db
def test_currency_only_conversion_has_no_destination_context(japan_context):
    assert (
        build_destination_context(
            country_code="",
            converted_amount=Decimal("1000"),
            quote_currency="JPY",
        )
        is None
    )


def test_supporting_media_is_suppressed_when_destination_has_no_reviewed_context():
    image = ImageViewModel(
        src="/media/sourced/support.webp",
        ratio="4 / 5",
        alt="Supporting destination image",
        decorative=False,
        kind="contemporary_photo",
        label="Supporting image",
        width=1200,
        height=1500,
    )
    context = DestinationContext(
        country_code="FI",
        country_name="Finland",
        as_of=date(2026, 9, 29),
        payment=None,
        prices=(),
    )

    component = build_destination_context_component(
        context,
        historical=False,
        hero_image=image,
        everyday_value_image=image,
        payment_culture_image=image,
        local_detail_image=image,
    )

    assert component["hero_image"] is image
    assert component["everyday_value_image"] is None
    assert component["payment_culture_image"] is None
    assert component["local_detail_image"] is None
