from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.urls import reverse

from apps.countries.models import Country, CountryCurrency, Currency
from integrations.price_data import OpenPricesSourceError, PublicPriceObservation
from integrations.product_data.base import ProductIdentity


@pytest.fixture(autouse=True)
def use_vite_dev_mode(settings):
    settings.VITE_DEV_SERVER_ENABLED = True


@pytest.fixture(autouse=True)
def shopping_reference_data(db):
    purchase_country = Country.objects.create(iso2="US", iso3="USA", name="United States")
    home_country = Country.objects.create(iso2="FI", iso3="FIN", name="Finland")
    usd = Currency.objects.create(code="USD", name="US dollar", symbol="$", minor_units=2)
    eur = Currency.objects.create(code="EUR", name="Euro", symbol="€", minor_units=2)
    CountryCurrency.objects.create(
        country=purchase_country, currency=usd, is_primary=True, source="test"
    )
    CountryCurrency.objects.create(
        country=home_country, currency=eur, is_primary=True, source="test"
    )


@pytest.fixture
def identity():
    return ProductIdentity(
        barcode="3017624010701",
        product_name="Food sample",
        brands=("Example",),
        quantity="400 g",
        categories=("Food",),
        source_name="Open Food Facts",
        source_url="https://world.openfoodfacts.org/product/3017624010701",
        retrieved_at=datetime(2026, 10, 8, tzinfo=UTC),
    )


@pytest.fixture
def observation():
    return PublicPriceObservation(
        product_code="3017624010701",
        amount=Decimal("3.95"),
        currency="EUR",
        observed_at=date(2026, 9, 15),
        country_code="FI",
        location_label="Example Market Helsinki",
        discounted=False,
        proof_id=4,
        source_url="https://prices.openfoodfacts.org/api/v1/prices/18",
        retrieved_at=datetime(2026, 10, 8, tzinfo=UTC),
    )


@pytest.mark.django_db
def test_shopping_normal_get_and_product_lookup_never_call_prices(client, identity):
    with (
        patch(
            "apps.exchange.web.shopping.lookup_product_identity_cached",
            return_value=identity,
        ),
        patch("apps.exchange.web.shopping.lookup_public_price_observations") as prices,
    ):
        normal = client.get(reverse("shopping_calculation"))
        product = client.get(reverse("shopping_calculation"), {"barcode": identity.barcode})

    assert normal.status_code == 200
    assert product.status_code == 200
    assert b"View optional community-observed prices" in product.content
    prices.assert_not_called()


@pytest.mark.django_db
def test_explicit_lookup_keeps_prices_separate_from_financial_truth(client, identity, observation):
    with (
        patch(
            "apps.exchange.web.shopping.lookup_product_identity_cached",
            return_value=identity,
        ),
        patch(
            "apps.exchange.web.shopping.lookup_public_price_observations",
            return_value=(observation,),
        ) as lookup,
        patch("apps.exchange.views.build_latest_quote_gateway") as fx,
    ):
        response = client.get(
            reverse("shopping_calculation"),
            {"barcode": identity.barcode, "show_prices": "1"},
        )
    body = response.content.decode()
    assert response.status_code == 200
    assert "3.95 EUR per unit" in body
    assert "Example Market Helsinki" in body
    assert "15 Sep 2026" in body
    assert "Open Prices record and proof #4" in body
    assert "manually entered shelf price" in body
    assert 'name="item_price"' in body
    assert 'value="3.95"' not in body
    lookup.assert_called_once_with(identity.barcode)
    fx.assert_not_called()


@pytest.mark.django_db
def test_optional_price_source_failure_does_not_break_calculator(client, identity):
    with (
        patch(
            "apps.exchange.web.shopping.lookup_product_identity_cached",
            return_value=identity,
        ),
        patch(
            "apps.exchange.web.shopping.lookup_public_price_observations",
            side_effect=OpenPricesSourceError("private upstream error"),
        ),
    ):
        response = client.get(
            reverse("shopping_calculation"),
            {"barcode": identity.barcode, "show_prices": "1"},
        )
    assert response.status_code == 200
    assert b"Community price observations are unavailable" in response.content
    assert b"Item price" in response.content
    assert b"private upstream error" not in response.content


@pytest.mark.django_db
def test_empty_qualified_sample_has_explicit_non_live_state(client, identity):
    with (
        patch(
            "apps.exchange.web.shopping.lookup_product_identity_cached",
            return_value=identity,
        ),
        patch(
            "apps.exchange.web.shopping.lookup_public_price_observations",
            return_value=(),
        ),
    ):
        response = client.get(
            reverse("shopping_calculation"),
            {"barcode": identity.barcode, "show_prices": "1"},
        )
    assert response.status_code == 200
    assert b"No qualifying, dated, proof-linked unit-price observations" in response.content
    assert b"not live" in response.content
