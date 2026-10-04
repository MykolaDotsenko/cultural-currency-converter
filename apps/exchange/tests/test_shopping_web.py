from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.urls import reverse

from apps.countries.models import Country, CountryCurrency, Currency
from apps.exchange.domain import DEFAULT_SOURCE_POLICY, RateQuote
from apps.exchange.providers.base import FxProviderTimeout


@pytest.fixture(autouse=True)
def use_vite_dev_mode(settings):
    settings.VITE_DEV_SERVER_ENABLED = True


class ShoppingGateway:
    def __init__(self):
        self.calls = []

    def get(self, base, quote, policy, *, now):
        self.calls.append((base, quote))
        return (
            RateQuote(
                base_currency=base,
                quote_currency=quote,
                rate=Decimal("0.9"),
                requested_date=None,
                effective_date=date(2026, 10, 1),
                fetched_at=datetime(2026, 10, 2, 8, tzinfo=UTC),
                provider_policy=DEFAULT_SOURCE_POLICY,
                provider_keys=("ecb",),
                historical=False,
            ),
            False,
        )


class FailingShoppingGateway:
    def get(self, base, quote, policy, *, now):
        raise FxProviderTimeout("provider timeout")


@pytest.fixture
def shopping_reference_data(db):
    us = Country.objects.create(iso2="US", iso3="USA", name="United States")
    fi = Country.objects.create(iso2="FI", iso3="FIN", name="Finland")
    usd = Currency.objects.create(code="USD", name="US dollar", symbol="$", minor_units=2)
    eur = Currency.objects.create(code="EUR", name="Euro", symbol="€", minor_units=2)
    CountryCurrency.objects.create(country=us, currency=usd, is_primary=True, source="test")
    CountryCurrency.objects.create(country=fi, currency=eur, is_primary=True, source="test")
    return us, fi, usd, eur


def _payload(**overrides):
    payload = {
        "purchase_country": "US",
        "purchase_currency": "USD",
        "home_currency": "EUR",
        "item_price": "100.00",
        "shipping": "20.00",
        "known_fees": "10.00",
        "fx_markup_percent": "2.50",
    }
    payload.update(overrides)
    return payload


@pytest.mark.django_db
def test_shopping_get_is_provider_free(client, shopping_reference_data):
    with patch("apps.exchange.views.build_latest_quote_gateway") as provider_factory:
        response = client.get(reverse("shopping_calculation"))

    assert response.status_code == 200
    assert b"Price abroad, cost at home." in response.content
    assert b"Item price" in response.content
    assert b"Unknown costs" in response.content
    provider_factory.assert_not_called()


@pytest.mark.django_db
def test_shopping_post_uses_explicit_total_and_canonical_reference_rate(
    client,
    shopping_reference_data,
):
    gateway = ShoppingGateway()
    with patch("apps.exchange.views.build_latest_quote_gateway", return_value=gateway):
        response = client.post(reverse("shopping_calculation"), _payload())

    assert response.status_code == 200
    assert gateway.calls == [("USD", "EUR")]
    body = response.content
    assert b"130.00 USD explicit purchase total" in body
    assert b"117.00 EUR" in body
    assert b"119.92" in body
    assert b"2.50%" in body
    assert b"2.92 EUR" in body
    assert b"1 Oct 2026" in body
    assert b"ECB" in body
    assert b'data-country-theme="us"' in body
    assert b"duties not explicitly entered" in body
    assert b"taxes not explicitly entered" in body
    assert b"issuer or merchant fees not explicitly entered" in body


@pytest.mark.django_db
def test_shopping_same_currency_fails_before_provider_access(
    client,
    shopping_reference_data,
):
    with patch("apps.exchange.views.build_latest_quote_gateway") as provider_factory:
        response = client.post(
            reverse("shopping_calculation"),
            _payload(home_currency="USD"),
        )

    assert response.status_code == 422
    assert b"Choose a different home currency" in response.content
    provider_factory.assert_not_called()


@pytest.mark.django_db
def test_shopping_country_currency_mismatch_fails_before_provider_access(
    client,
    shopping_reference_data,
):
    with patch("apps.exchange.views.build_latest_quote_gateway") as provider_factory:
        response = client.post(
            reverse("shopping_calculation"),
            _payload(purchase_currency="EUR"),
        )

    assert response.status_code == 422
    assert b"currently associated with this purchase country" in response.content
    provider_factory.assert_not_called()


@pytest.mark.django_db
def test_shopping_preserves_explicit_inputs_when_provider_is_unavailable(
    client,
    shopping_reference_data,
):
    with patch(
        "apps.exchange.views.build_latest_quote_gateway",
        return_value=FailingShoppingGateway(),
    ):
        response = client.post(reverse("shopping_calculation"), _payload())

    assert response.status_code == 503
    assert b"temporarily unavailable" in response.content
    assert b'value="100.00"' in response.content
    assert b'value="20.00"' in response.content
    assert b'value="10.00"' in response.content
    assert b'id="shopping-result-title"' not in response.content


@pytest.mark.django_db
def test_shopping_invalid_markup_is_bound_and_does_not_call_provider(
    client,
    shopping_reference_data,
):
    with patch("apps.exchange.views.build_latest_quote_gateway") as provider_factory:
        response = client.post(
            reverse("shopping_calculation"),
            _payload(fx_markup_percent="25.01"),
        )

    assert response.status_code == 422
    assert b"Ensure this value is less than or equal to 25" in response.content
    provider_factory.assert_not_called()


@pytest.mark.django_db
def test_shopping_uses_purchase_currency_precision(
    client,
    shopping_reference_data,
):
    with patch("apps.exchange.views.build_latest_quote_gateway") as provider_factory:
        response = client.post(
            reverse("shopping_calculation"),
            _payload(item_price="1000.001"),
        )

    assert response.status_code == 422
    assert b"at most 2 decimal places" in response.content
    provider_factory.assert_not_called()
