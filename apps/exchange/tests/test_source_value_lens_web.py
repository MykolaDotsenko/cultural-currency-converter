"""Bilateral source/destination lens uses reviewed local context, not extra FX."""

from decimal import Decimal
from unittest.mock import patch

import pytest
from django.db import DatabaseError
from django.urls import reverse
from django.utils import timezone

from apps.countries.models import City
from apps.culture.models import TypicalPrice, TypicalPriceCategory
from apps.exchange.tests.test_web import FakeGateway, FakeHistoricalGateway, payload
from apps.exchange.tests.test_web import reference_data as reference_data


@pytest.fixture(autouse=True)
def use_vite_dev_mode(settings):
    # Full-page converter responses must not require a production Vite manifest in CI.
    settings.VITE_DEV_SERVER_ENABLED = True


@pytest.fixture
def bilateral_prices(reference_data):
    fi, jp, eur, jpy, _fim = reference_data
    for country, currency, label, price, url in (
        (fi, eur, "Finland coffee", "5.00", "https://example.org/fi-coffee"),
        (jp, jpy, "Japan coffee", "500", "https://example.org/jp-coffee"),
    ):
        TypicalPrice.objects.create(
            country=country,
            currency=currency,
            category=TypicalPriceCategory.COFFEE,
            label=label,
            amount_low=Decimal(price),
            source_name="Reviewed local evidence",
            source_url=url,
            observed_at=timezone.localdate(),
            verified_at=timezone.now(),
            is_published=True,
        )
    return fi, jp, eur, jpy


@pytest.mark.django_db
@pytest.mark.parametrize("htmx", [False, True])
def test_bilateral_lens_preserves_independent_amounts_and_sourced_prices(
    client, bilateral_prices, htmx
):
    gateway = FakeGateway()
    headers = {"HTTP_HX_REQUEST": "true"} if htmx else {}
    with patch("apps.exchange.views.build_latest_quote_gateway", return_value=gateway):
        if htmx:
            response = client.post(reverse("converter"), payload(), **headers)
        else:
            response = client.get(
                reverse("converter"),
                {
                    "convert": "1",
                    **payload(),
                },
            )

    assert response.status_code == 200
    html = response.content.decode()
    assert "data-bilateral-value-lens" in html
    assert 'data-value-side="source"' in html
    assert 'data-value-side="destination"' in html
    assert "Finland coffee" in html
    assert "Japan coffee" in html
    assert "5.00 EUR typical" in html
    assert "500 JPY typical" in html
    assert "About 20" in html
    assert "About 34" in html
    assert "https://example.org/fi-coffee" in html
    assert "https://example.org/jp-coffee" in html
    assert len(gateway.calls) == 1


@pytest.mark.django_db
def test_bilateral_lens_is_omitted_without_published_source_prices(client, reference_data):
    gateway = FakeGateway()
    with patch("apps.exchange.views.build_latest_quote_gateway", return_value=gateway):
        response = client.post(reverse("converter"), payload(), HTTP_HX_REQUEST="true")

    assert response.status_code == 200
    assert b"data-bilateral-value-lens" not in response.content
    assert len(gateway.calls) == 1


@pytest.mark.django_db
def test_bilateral_lens_never_disguises_historical_fx_as_current_value(client, bilateral_prices):
    historical = FakeHistoricalGateway()
    with (
        patch("apps.exchange.views.build_historical_quote_gateway", return_value=historical),
        patch("apps.exchange.web.converter.build_destination_context") as source_builder,
    ):
        response = client.post(
            reverse("converter"),
            payload(rate_mode="historical", requested_date="2026-09-18"),
            HTTP_HX_REQUEST="true",
        )

    assert response.status_code == 200
    assert b"data-bilateral-value-lens" not in response.content
    source_builder.assert_not_called()


@pytest.mark.django_db
def test_source_context_failure_never_hides_a_valid_conversion(client, bilateral_prices):
    gateway = FakeGateway()
    with (
        patch("apps.exchange.views.build_latest_quote_gateway", return_value=gateway),
        patch(
            "apps.exchange.web.converter.build_destination_context",
            side_effect=DatabaseError("optional evidence store down"),
        ),
    ):
        response = client.post(reverse("converter"), payload(), HTTP_HX_REQUEST="true")

    assert response.status_code == 200
    assert b'id="current-conversion-result"' in response.content
    assert b"data-bilateral-value-lens" not in response.content
    assert len(gateway.calls) == 1


@pytest.mark.django_db
def test_destination_city_scope_remains_explicit_in_bilateral_lens(client, bilateral_prices):
    _fi, jp, _eur, jpy = bilateral_prices
    city = City.objects.create(country=jp, slug="tokyo", name="Tokyo")
    TypicalPrice.objects.filter(country=jp).delete()
    TypicalPrice.objects.create(
        country=jp,
        city="Tokyo",
        city_ref=city,
        currency=jpy,
        category=TypicalPriceCategory.COFFEE,
        label="Tokyo coffee",
        amount_low=Decimal("600"),
        source_name="Tokyo fare source",
        source_url="https://example.org/tokyo-coffee",
        observed_at=timezone.localdate(),
        verified_at=timezone.now(),
        is_published=True,
    )
    with patch("apps.exchange.views.build_latest_quote_gateway", return_value=FakeGateway()):
        response = client.post(
            reverse("converter"),
            payload(destination_city_slug="tokyo"),
            HTTP_HX_REQUEST="true",
        )
    assert response.status_code == 200
    html = response.content.decode()
    assert "data-bilateral-value-lens" in html
    assert "Tokyo coffee" in html
    assert "600 JPY typical · Tokyo" in html
