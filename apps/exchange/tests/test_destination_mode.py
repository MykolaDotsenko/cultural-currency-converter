from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

import pytest
from django.urls import reverse

from apps.countries.models import City, Country, CountryCurrency, Currency


@pytest.fixture
def destination_reference_data(db):
    fi = Country.objects.create(iso2="FI", iso3="FIN", name="Finland")
    jp = Country.objects.create(iso2="JP", iso3="JPN", name="Japan")
    no = Country.objects.create(iso2="NO", iso3="NOR", name="Norway")
    eur = Currency.objects.create(code="EUR", name="Euro", symbol="€", minor_units=2)
    jpy = Currency.objects.create(code="JPY", name="Japanese yen", symbol="¥", minor_units=0)
    nok = Currency.objects.create(code="NOK", name="Norwegian krone", symbol="kr", minor_units=2)
    CountryCurrency.objects.create(
        country=fi,
        currency=eur,
        is_primary=True,
        source="test",
    )
    CountryCurrency.objects.create(
        country=jp,
        currency=jpy,
        is_primary=True,
        source="test",
    )
    CountryCurrency.objects.create(
        country=no,
        currency=nok,
        is_primary=True,
        source="test",
    )
    tokyo = City.objects.create(country=jp, slug="tokyo", name="Tokyo")
    return fi, jp, no, eur, jpy, nok, tokyo


@pytest.mark.django_db
def test_destination_mode_get_is_destination_first_and_provider_free(
    client,
    destination_reference_data,
):
    with patch("apps.exchange.views.build_latest_quote_gateway") as provider_factory:
        response = client.get(reverse("destination_mode"))

    assert response.status_code == 200
    assert b"Start with the place." in response.content
    assert b"Tokyo, Japan" in response.content
    assert b"JPY" in response.content
    assert b"No rate is requested on this page." in response.content
    provider_factory.assert_not_called()


@pytest.mark.django_db
def test_destination_mode_city_redirects_to_canonical_converter_without_rate_lookup(
    client,
    destination_reference_data,
):
    with patch("apps.exchange.views.build_latest_quote_gateway") as provider_factory:
        response = client.post(
            reverse("destination_mode"),
            {
                "amount": "100",
                "source_currency": "EUR",
                "destination": "JP:tokyo",
            },
        )

    assert response.status_code == 302
    parsed = urlparse(response["Location"])
    assert parsed.path == reverse("converter")
    query = parse_qs(parsed.query, keep_blank_values=True)
    assert query["convert"] == ["1"]
    assert query["amount"] == ["100"]
    assert query["source_country"] == [""]
    assert query["source_currency"] == ["EUR"]
    assert query["destination_country"] == ["JP"]
    assert query["destination_currency"] == ["JPY"]
    assert query["destination_city_slug"] == ["tokyo"]
    provider_factory.assert_not_called()


@pytest.mark.django_db
def test_destination_mode_country_scope_omits_city_parameter(
    client,
    destination_reference_data,
):
    response = client.post(
        reverse("destination_mode"),
        {
            "amount": "250.50",
            "source_currency": "EUR",
            "destination": "JP",
        },
    )

    assert response.status_code == 302
    query = parse_qs(urlparse(response["Location"]).query, keep_blank_values=True)
    assert query["amount"] == ["250.50"]
    assert query["destination_country"] == ["JP"]
    assert query["destination_currency"] == ["JPY"]
    assert "destination_city_slug" not in query


@pytest.mark.django_db
def test_destination_mode_rejects_tampered_destination_without_redirect(
    client,
    destination_reference_data,
):
    response = client.post(
        reverse("destination_mode"),
        {
            "amount": "100",
            "source_currency": "EUR",
            "destination": "JP:not-a-real-city",
        },
    )

    assert response.status_code == 422
    assert not response.has_header("Location")
    assert b"Select a valid choice" in response.content


@pytest.mark.django_db
def test_destination_mode_uses_source_currency_minor_units(
    client,
    destination_reference_data,
):
    response = client.post(
        reverse("destination_mode"),
        {
            "amount": "1.001",
            "source_currency": "EUR",
            "destination": "JP:tokyo",
        },
    )

    assert response.status_code == 422
    assert b"This amount is ambiguous" in response.content
