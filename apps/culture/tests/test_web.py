from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.db import DatabaseError
from django.urls import reverse
from django.utils import timezone

from apps.countries.models import Country, CountryCurrency, Currency
from apps.culture.models import (
    CulturalProfile,
    StoryDatePrecision,
    StoryMoment,
    StoryMomentCategory,
    StoryMomentStatus,
    StorySourceKind,
    TypicalPrice,
    TypicalPriceCategory,
)
from apps.culture.services import approve_story_moment, publish_story_moment
from apps.exchange.domain import DEFAULT_SOURCE_POLICY, RateQuote


class FakeGateway:
    def get(self, base, quote, policy, *, now):
        return (
            RateQuote(
                base_currency=base,
                quote_currency=quote,
                rate=Decimal("174.50"),
                requested_date=None,
                effective_date=date(2026, 9, 18),
                fetched_at=datetime(2026, 9, 21, 8, tzinfo=UTC),
                provider_policy=DEFAULT_SOURCE_POLICY,
                provider_keys=("ecb",),
                historical=False,
            ),
            False,
        )


@pytest.fixture(autouse=True)
def use_vite_dev_mode(settings):
    settings.VITE_DEV_SERVER_ENABLED = True


@pytest.fixture
def reference_data(db):
    fi = Country.objects.create(iso2="FI", iso3="FIN", name="Finland")
    jp = Country.objects.create(iso2="JP", iso3="JPN", name="Japan")
    eur = Currency.objects.create(code="EUR", name="Euro", symbol="€", minor_units=2)
    jpy = Currency.objects.create(code="JPY", name="Japanese yen", symbol="¥", minor_units=0)
    CountryCurrency.objects.create(
        country=fi,
        currency=eur,
        is_primary=True,
        valid_from=date(2002, 1, 1),
        source="https://example.org/fi-eur",
    )
    CountryCurrency.objects.create(
        country=jp,
        currency=jpy,
        is_primary=True,
        source="https://example.org/jp-jpy",
    )
    return fi, jp, eur, jpy


def _seed_current_destination_context(reference_data):
    _fi, jp, _eur, jpy = reference_data
    CulturalProfile.objects.create(
        country=jp,
        summary="Current reviewed payment context.",
        payment_customs="Cards are commonly accepted.",
        cash_usage="Cash remains useful.",
        source_name="JNTO",
        source_url="https://example.org/payment",
        verified_at=timezone.now(),
        is_published=True,
    )
    TypicalPrice.objects.create(
        country=jp,
        city="Tokyo",
        category=TypicalPriceCategory.COFFEE,
        label="Cup of coffee",
        amount_low=Decimal("500"),
        amount_high=Decimal("650"),
        currency=jpy,
        source_name="Current price source",
        source_url="https://example.org/coffee",
        observed_at=timezone.localdate(),
        verified_at=timezone.now(),
        is_published=True,
    )


def _story_query(**overrides):
    query = {
        "source_country": "FI",
        "source_currency": "EUR",
        "destination_country": "JP",
        "destination_currency": "JPY",
        "selected_date": "2026-09-21",
        "historical": "0",
    }
    query.update(overrides)
    return query


@pytest.mark.django_db
def test_converter_exposes_progressive_story_entry_without_calling_story_service(
    client,
    reference_data,
):
    payload = {
        "amount": "100.00",
        "source_country": "FI",
        "source_currency": "EUR",
        "destination_country": "JP",
        "destination_currency": "JPY",
    }
    with (
        patch("apps.exchange.views.build_latest_quote_gateway", return_value=FakeGateway()),
        patch("apps.culture.views.compose_story") as composer,
    ):
        response = client.post(reverse("converter"), payload, HTTP_HX_REQUEST="true")

    assert response.status_code == 200
    assert b"Explore money &amp; culture" in response.content
    assert b"/story/?" in response.content
    composer.assert_not_called()


@pytest.mark.django_db
def test_htmx_story_returns_fragment_with_deterministic_currency_eras(client, reference_data):
    response = client.get(
        reverse("money_culture_story"),
        _story_query(),
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    assert b"<html" not in response.content
    assert b"The sourced story behind this currency context" in response.content
    assert b"Finland" in response.content
    assert b"Japan" in response.content
    assert b"Missing facts are not filled in" not in response.content


@pytest.mark.django_db
def test_no_javascript_story_returns_full_page(client, reference_data):
    response = client.get(reverse("money_culture_story"), _story_query())

    assert response.status_code == 200
    assert b"<html" in response.content
    assert b"The story behind the currency context" in response.content
    assert b"Back to converter" in response.content


@pytest.mark.django_db
def test_current_destination_context_htmx_is_explicitly_current(client, reference_data):
    _seed_current_destination_context(reference_data)

    response = client.get(
        reverse("current_destination_context"),
        {"country": "JP", "currency": "JPY", "amount": "17450"},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    assert b"<html" not in response.content
    assert b"Current destination context" in response.content
    assert b"not historical purchasing power" in response.content
    assert b"Cup of coffee" in response.content
    assert b'aria-label="Explore conversion context"' not in response.content
    assert "HX-Request" in response.get("Vary", "")


@pytest.mark.django_db
def test_current_destination_context_without_javascript_is_full_page(client, reference_data):
    _seed_current_destination_context(reference_data)

    response = client.get(
        reverse("current_destination_context"),
        {"country": "JP", "currency": "JPY", "amount": "17450"},
    )

    assert response.status_code == 200
    assert b"<html" in response.content
    assert b"Current context, separate from historical FX" in response.content
    assert b"Back to converter" in response.content


@pytest.mark.django_db
def test_invalid_current_destination_context_query_is_400_without_composition(
    client,
    reference_data,
):
    with patch("apps.culture.views.build_destination_context") as builder:
        response = client.get(
            reverse("current_destination_context"),
            {"country": "ZZ", "currency": "JPY", "amount": "not-a-number"},
            HTTP_HX_REQUEST="true",
        )

    assert response.status_code == 400
    assert b"request is not valid" in response.content
    builder.assert_not_called()


@pytest.mark.django_db
def test_current_destination_context_failure_is_local_and_htmx_visible(client, reference_data):
    with patch(
        "apps.culture.views.build_destination_context",
        side_effect=RuntimeError("context unavailable"),
    ):
        response = client.get(
            reverse("current_destination_context"),
            {"country": "JP", "currency": "JPY", "amount": "17450"},
            HTTP_HX_REQUEST="true",
        )

    assert response.status_code == 200
    assert b"temporarily unavailable" in response.content
    assert b"The historical conversion remains valid" in response.content


@pytest.mark.django_db
@pytest.mark.parametrize(
    "failure",
    [DatabaseError("media database unavailable"), ValueError("malformed managed media")],
)
def test_story_cover_media_failure_keeps_story_available(
    client, reference_data, failure, caplog
):
    with (
        patch("apps.culture.views.select_media_for_display", side_effect=failure),
        caplog.at_level("WARNING", logger="cultural_currency.culture"),
    ):
        response = client.get(
            reverse("money_culture_story"),
            _story_query(),
            HTTP_HX_REQUEST="true",
        )

    assert response.status_code == 200
    assert b"The sourced story behind this currency context" in response.content
    assert b"temporarily unavailable" not in response.content
    assert any(
        record.msg == "Money and culture story cover media unavailable"
        for record in caplog.records
    )


@pytest.mark.django_db
def test_reviewed_story_fact_appears_with_source_link(client, reference_data):
    fi, _jp, eur, _jpy = reference_data
    moment = StoryMoment.objects.create(
        category=StoryMomentCategory.MONETARY_UNION,
        title="Finland adopted the euro",
        summary="A reviewed sourced transition.",
        start_date=date(1999, 1, 1),
        end_date=date(1999, 1, 1),
        date_precision=StoryDatePrecision.EXACT_DAY,
        source_kind=StorySourceKind.OFFICIAL,
        source_name="European Commission",
        source_url="https://example.org/euro",
        verified_at=timezone.now(),
        status=StoryMomentStatus.NEEDS_REVIEW,
    )
    moment.countries.add(fi)
    moment.currencies.add(eur)
    approve_story_moment(moment)
    publish_story_moment(moment)

    response = client.get(
        reverse("money_culture_story"),
        _story_query(),
        HTTP_HX_REQUEST="true",
    )

    assert b"Finland adopted the euro" in response.content
    assert b"A reviewed sourced transition." in response.content
    assert b"https://example.org/euro" in response.content
    assert b"European Commission" in response.content


@pytest.mark.django_db
def test_unpublished_story_fact_never_appears(client, reference_data):
    fi, _jp, _eur, _jpy = reference_data
    moment = StoryMoment.objects.create(
        category=StoryMomentCategory.CULTURAL_MONEY_FACT,
        title="Draft-only fact",
        summary="This must stay hidden.",
        source_kind=StorySourceKind.OFFICIAL,
        source_name="Source",
        source_url="https://example.org/draft",
        verified_at=timezone.now(),
        status=StoryMomentStatus.APPROVED,
    )
    moment.countries.add(fi)

    response = client.get(
        reverse("money_culture_story"),
        _story_query(),
        HTTP_HX_REQUEST="true",
    )

    assert b"Draft-only fact" not in response.content
    assert b"This must stay hidden" not in response.content


@pytest.mark.django_db
def test_historical_story_excludes_fact_outside_selected_date(client, reference_data):
    fi, _jp, eur, _jpy = reference_data
    moment = StoryMoment.objects.create(
        category=StoryMomentCategory.CASH_CHANGEOVER,
        title="2002 changeover",
        summary="This occurred after the selected historical date.",
        start_date=date(2002, 1, 1),
        end_date=date(2002, 2, 28),
        date_precision=StoryDatePrecision.RANGE,
        source_kind=StorySourceKind.OFFICIAL,
        source_name="Source",
        source_url="https://example.org/changeover",
        verified_at=timezone.now(),
        status=StoryMomentStatus.NEEDS_REVIEW,
    )
    moment.countries.add(fi)
    moment.currencies.add(eur)
    approve_story_moment(moment)
    publish_story_moment(moment)

    response = client.get(
        reverse("money_culture_story"),
        _story_query(selected_date="2001-06-01", historical="1"),
        HTTP_HX_REQUEST="true",
    )

    assert b"2002 changeover" not in response.content


@pytest.mark.django_db
def test_invalid_story_query_is_400_and_does_not_call_composer(client, reference_data):
    with patch("apps.culture.views.compose_story") as composer:
        response = client.get(
            reverse("money_culture_story"),
            _story_query(destination_currency="ZZZ"),
            HTTP_HX_REQUEST="true",
        )

    assert response.status_code == 400
    assert b"not valid" in response.content
    composer.assert_not_called()


@pytest.mark.django_db
def test_current_story_ignores_tampered_old_date_and_normalizes_to_today(client, reference_data):
    captured = {}

    def fake_compose(request):
        captured["request"] = request
        from apps.culture.story import StoryComposition

        return StoryComposition(
            chapters=(),
            status="unavailable",
            selected_date=request.selected_date,
            historical=request.historical,
        )

    with patch("apps.culture.views.compose_story", side_effect=fake_compose):
        response = client.get(
            reverse("money_culture_story"),
            _story_query(selected_date="1999-01-01", historical="0"),
            HTTP_HX_REQUEST="true",
        )

    assert response.status_code == 200
    assert captured["request"].selected_date == timezone.localdate()
    assert captured["request"].historical is False


@pytest.mark.django_db
def test_future_historical_story_date_is_rejected(client, reference_data):
    future = (timezone.localdate().replace(year=timezone.localdate().year + 1)).isoformat()
    response = client.get(
        reverse("money_culture_story"),
        _story_query(selected_date=future, historical="1"),
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_composer_failure_degrades_to_story_only_error_not_conversion_failure(
    client,
    reference_data,
):
    with patch("apps.culture.views.compose_story", side_effect=RuntimeError("boom")):
        response = client.get(
            reverse("money_culture_story"),
            _story_query(),
            HTTP_HX_REQUEST="true",
        )

    assert response.status_code == 200
    assert b"temporarily unavailable" in response.content
    assert b"The conversion remains valid" in response.content
