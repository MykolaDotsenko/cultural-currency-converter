from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.urls import reverse

from apps.countries.models import Country, CountryCurrency, Currency
from apps.exchange.domain import DEFAULT_SOURCE_POLICY, RateQuote
from apps.exchange.product_context import build_product_context_token
from integrations.product_data.base import ProductDataSourceError, ProductIdentity, ProductNotFound


class ShoppingGateway:
    def get(self, base, quote, policy, *, now):
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


@pytest.fixture(autouse=True)
def use_vite_dev_mode(settings):
    settings.VITE_DEV_SERVER_ENABLED = True


@pytest.fixture
def shopping_reference_data(db):
    us = Country.objects.create(iso2="US", iso3="USA", name="United States")
    fi = Country.objects.create(iso2="FI", iso3="FIN", name="Finland")
    usd = Currency.objects.create(code="USD", name="US dollar", symbol="$", minor_units=2)
    eur = Currency.objects.create(code="EUR", name="Euro", symbol="€", minor_units=2)
    CountryCurrency.objects.create(country=us, currency=usd, is_primary=True, source="test")
    CountryCurrency.objects.create(country=fi, currency=eur, is_primary=True, source="test")
    return us, fi, usd, eur


@pytest.fixture
def product_identity():
    return ProductIdentity(
        barcode="3017624010701",
        product_name="Hazelnut cocoa spread",
        brands=("Example Brand",),
        quantity="400 g",
        categories=("Spreads",),
        source_name="Open Food Facts",
        source_url="https://world.openfoodfacts.org/product/3017624010701",
        retrieved_at=datetime(2026, 10, 8, 10, tzinfo=UTC),
    )


def _shopping_payload(**overrides):
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
def test_normal_shopping_get_never_calls_product_provider(client, shopping_reference_data):
    with patch("apps.exchange.web.shopping.lookup_product_identity_cached") as lookup:
        response = client.get(reverse("shopping_calculation"))

    assert response.status_code == 200
    lookup.assert_not_called()


@pytest.mark.django_db
def test_explicit_barcode_lookup_adds_identity_without_calling_fx(
    client,
    shopping_reference_data,
    product_identity,
):
    with (
        patch(
            "apps.exchange.web.shopping.lookup_product_identity_cached",
            return_value=product_identity,
        ) as lookup,
        patch("apps.exchange.views.build_latest_quote_gateway") as fx_factory,
    ):
        response = client.get(
            reverse("shopping_calculation"),
            {"barcode": product_identity.barcode},
        )

    assert response.status_code == 200
    lookup.assert_called_once_with(product_identity.barcode)
    fx_factory.assert_not_called()
    body = response.content.decode()
    assert "Hazelnut cocoa spread" in body
    assert "Example Brand" in body
    assert "400 g" in body
    assert "Open Food Facts" in body
    assert "never changes the price or FX calculation below." in body
    assert 'name="product_context_token"' in body


@pytest.mark.django_db
def test_signed_product_context_survives_shopping_submit_without_second_lookup(
    client,
    shopping_reference_data,
    product_identity,
):
    token = build_product_context_token(product_identity)
    with (
        patch("apps.exchange.web.shopping.lookup_product_identity_cached") as lookup,
        patch(
            "apps.exchange.views.build_latest_quote_gateway",
            return_value=ShoppingGateway(),
        ),
    ):
        response = client.post(
            reverse("shopping_calculation"),
            _shopping_payload(product_context_token=token),
        )

    assert response.status_code == 200
    lookup.assert_not_called()
    body = response.content.decode()
    assert "Hazelnut cocoa spread" in body
    assert "117.00 EUR" in body
    assert "Product context" in body


@pytest.mark.django_db
def test_tampered_product_context_does_not_block_financial_calculation(
    client,
    shopping_reference_data,
):
    with patch(
        "apps.exchange.views.build_latest_quote_gateway",
        return_value=ShoppingGateway(),
    ):
        response = client.post(
            reverse("shopping_calculation"),
            _shopping_payload(product_context_token="tampered"),
        )

    assert response.status_code == 200
    body = response.content.decode()
    assert "Saved product context expired" in body
    assert "117.00 EUR" in body
    assert "Product context</dt>" not in body


@pytest.mark.django_db
def test_product_lookup_failure_is_optional_not_shopping_failure(
    client,
    shopping_reference_data,
):
    with patch(
        "apps.exchange.web.shopping.lookup_product_identity_cached",
        side_effect=ProductDataSourceError("down"),
    ):
        response = client.get(reverse("shopping_calculation"), {"barcode": "3017624010701"})

    assert response.status_code == 200
    assert b"Product context is temporarily unavailable" in response.content
    assert b"Item price" in response.content


def test_product_api_v1_returns_identity_without_price(client, product_identity):
    with patch(
        "apps.exchange.api_v1.lookup_product_identity_cached",
        return_value=product_identity,
    ):
        response = client.get(reverse("api_v1_product_identity", args=(product_identity.barcode,)))

    assert response.status_code == 200
    assert response["X-API-Version"] == "1"
    data = response.json()["data"]
    assert data["productName"] == "Hazelnut cocoa spread"
    assert data["brands"] == ["Example Brand"]
    assert data["quantity"] == "400 g"
    assert data["price"] is None
    assert data["source"]["databaseLicense"] == "Open Database License (ODbL)"


def test_product_api_v1_maps_not_found_and_provider_failure(client):
    with patch(
        "apps.exchange.api_v1.lookup_product_identity_cached",
        side_effect=ProductNotFound("missing"),
    ):
        missing = client.get(reverse("api_v1_product_identity", args=("12345678",)))

    with patch(
        "apps.exchange.api_v1.lookup_product_identity_cached",
        side_effect=ProductDataSourceError("secret provider detail"),
    ):
        unavailable = client.get(reverse("api_v1_product_identity", args=("3017624010701",)))

    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "product_not_found"
    assert unavailable.status_code == 503
    assert unavailable.json()["error"]["code"] == "product_source_unavailable"
    assert "secret provider detail" not in unavailable.content.decode()
