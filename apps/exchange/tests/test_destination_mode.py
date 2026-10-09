from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.countries.models import City, Country, CountryCurrency, Currency
from apps.culture.services import DestinationContext
from apps.exchange.domain import DEFAULT_SOURCE_POLICY, RateQuote


@pytest.fixture(autouse=True)
def use_vite_dev_mode(settings):
    settings.VITE_DEV_SERVER_ENABLED = True


class DestinationModeGateway:
    def get(self, base, quote, policy, *, now):
        return (
            RateQuote(
                base_currency=base,
                quote_currency=quote,
                rate=Decimal("174.50"),
                requested_date=None,
                effective_date=date(2026, 9, 18),
                fetched_at=datetime(2026, 9, 20, 8, tzinfo=UTC),
                provider_policy=DEFAULT_SOURCE_POLICY,
                provider_keys=("ecb",),
                historical=False,
            ),
            False,
        )


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


@pytest.mark.django_db
def test_destination_mode_city_scope_reaches_money_context_engine(
    client,
    destination_reference_data,
):
    context = DestinationContext(
        country_code="JP",
        country_name="Japan",
        as_of=timezone.localdate(),
        payment=None,
        prices=(),
        city_slug="tokyo",
        city_name="Tokyo",
    )

    with (
        patch(
            "apps.exchange.views.build_latest_quote_gateway",
            return_value=DestinationModeGateway(),
        ),
        patch(
            "apps.exchange.money_context.build_destination_context_default",
            return_value=context,
        ) as context_builder,
    ):
        response = client.get(
            reverse("converter"),
            {
                "convert": "1",
                "amount": "100",
                "source_country": "",
                "source_currency": "EUR",
                "destination_country": "JP",
                "destination_currency": "JPY",
                "destination_city_slug": "tokyo",
            },
        )

    assert response.status_code == 200
    assert b'name="destination_city_slug"' in response.content
    assert b'value="tokyo"' in response.content
    context_builder.assert_called_once()
    call = context_builder.call_args.kwargs
    assert call["country_code"] == "JP"
    assert call["quote_currency"] == "JPY"
    assert call["city_slug"] == "tokyo"
    assert call["converted_amount"] == Decimal("17450")


@pytest.mark.django_db
def test_destination_mode_reopens_recorded_inputs_without_old_fx(
    client, destination_reference_data
):
    with patch("apps.exchange.views.build_latest_quote_gateway") as gateway:
        response = client.get(
            reverse("destination_mode"),
            {
                "destination": "JP:tokyo",
                "source_currency": "EUR",
                "amount": "150.50",
                "from_history": "1",
                "rate_mode": "historical",
                "requested_date": "1999-01-01",
                "output_amount": "9999",
            },
        )
    assert response.status_code == 200
    assert response.context["form"].initial["destination"] == "JP:tokyo"
    assert response.context["form"].initial["amount"] == "150.50"
    assert response.context["form"].initial["source_currency"] == "EUR"
    assert b"No historical output, observed FX rate" in response.content
    gateway.assert_not_called()


@pytest.mark.django_db
def test_destination_mode_ignores_unsupported_or_invalid_input_prefill(
    client, destination_reference_data
):
    Currency.objects.create(code="FIM", name="Finnish markka", is_active=False)
    for amount in ("-10", "1.234", "9999999999", "5" * 65):
        response = client.get(
            reverse("destination_mode"),
            {"source_currency": "FIM", "amount": amount, "destination": "JP"},
        )
        assert response.status_code == 200
        assert response.context["form"].initial["amount"] == "100"
        assert response.context["form"].initial["source_currency"] == "EUR"
        assert response.context["form"].initial["destination"] == "JP"
        assert b"Finnish markka" not in response.content


@pytest.mark.django_db
def test_destination_mode_explicit_source_overrides_default_without_provider(
    client, destination_reference_data
):
    response = client.get(
        reverse("destination_mode"),
        {"destination": "NO", "source_currency": "JPY", "amount": "5000"},
    )
    assert response.status_code == 200
    assert response.context["form"].initial["source_currency"] == "JPY"
    assert response.context["form"].initial["amount"] == "5000"
