from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.countries.models import Country, CountryCurrency, Currency
from apps.exchange.domain import DEFAULT_SOURCE_POLICY, ConversionResult, RateQuote
from apps.exchange.shopping import ShoppingAssumptions
from apps.exchange.shopping_snapshot import build_shopping_context_snapshot_token
from apps.travel.models import (
    SavedScenario,
    SavedScenarioKind,
    SavedScenarioObservation,
    SavedScenarioObservationKind,
)

User = get_user_model()


@pytest.fixture(autouse=True)
def use_vite_dev_mode(settings):
    settings.VITE_DEV_SERVER_ENABLED = True


@pytest.fixture
def shopping_save_reference_data(db):
    us = Country.objects.create(iso2="US", iso3="USA", name="United States")
    usd = Currency.objects.create(code="USD", name="US dollar", symbol="$", minor_units=2)
    eur = Currency.objects.create(code="EUR", name="Euro", symbol="€", minor_units=2)
    CountryCurrency.objects.create(country=us, currency=usd, is_primary=True, source="test")
    return us, usd, eur


def _shopping_token() -> str:
    conversion = ConversionResult(
        input_amount=Decimal("130"),
        output_amount=Decimal("117.00"),
        quote=RateQuote(
            base_currency="USD",
            quote_currency="EUR",
            rate=Decimal("0.9"),
            requested_date=None,
            effective_date=date(2026, 10, 1),
            fetched_at=datetime(2026, 10, 2, 8, tzinfo=UTC),
            provider_policy=DEFAULT_SOURCE_POLICY,
            provider_keys=("ecb",),
            historical=False,
        ),
        stale=False,
    )
    return build_shopping_context_snapshot_token(
        conversion=conversion,
        assumptions=ShoppingAssumptions(
            item_price=Decimal("100"),
            shipping=Decimal("20"),
            known_fees=Decimal("10"),
            fx_markup_percent=Decimal("2.5"),
        ),
        purchase_country_code="US",
    )


@pytest.mark.django_db
def test_authenticated_user_can_save_and_reopen_exact_shopping_inputs(
    client,
    shopping_save_reference_data,
):
    user = User.objects.create_user(username="shopping-web-owner", password="StrongPass-482!")
    client.force_login(user)

    response = client.post(
        reverse("save_shopping_scenario"),
        {
            "shopping_context_token": _shopping_token(),
            "title": "US headphones",
        },
    )

    scenario = SavedScenario.objects.get(user=user)
    assert response.status_code == 302
    assert response.url == reverse("saved_scenario_detail", args=(scenario.pk,))
    assert scenario.kind == SavedScenarioKind.SHOPPING
    assert scenario.title == "US headphones"
    assert scenario.source_currency.code == "USD"
    assert scenario.destination_currency.code == "EUR"
    assert scenario.source_country.iso2 == "US"
    assert scenario.destination_country is None
    assert scenario.source_amount == Decimal("130")
    assert scenario.shopping_assumptions.item_price == Decimal("100")
    assert scenario.shopping_assumptions.shipping == Decimal("20")
    assert scenario.shopping_assumptions.known_fees == Decimal("10")
    assert scenario.shopping_assumptions.fx_markup_percent == Decimal("2.5")
    assert scenario.observations.count() == 1

    detail = client.get(response.url)
    assert detail.status_code == 200
    assert b"Saved Shopping estimate" in detail.content
    assert b"100.00 USD" in detail.content
    assert b"20.00 USD" in detail.content
    assert b"10.00 USD" in detail.content
    assert b"117.00 EUR" in detail.content
    assert b"119.92 EUR" in detail.content
    assert b"Reopen Shopping estimate" in detail.content
    assert b"purchase_country=US" in detail.content
    assert b"purchase_currency=USD" in detail.content
    assert b"home_currency=EUR" in detail.content
    assert b"item_price=100" in detail.content
    assert b"shipping=20" in detail.content
    assert b"known_fees=10" in detail.content
    assert b"fx_markup_percent=2.5" in detail.content


@pytest.mark.django_db
def test_saved_shopping_scenario_rejects_tampered_snapshot(
    client,
    shopping_save_reference_data,
):
    user = User.objects.create_user(username="shopping-tamper-owner", password="StrongPass-482!")
    client.force_login(user)

    response = client.post(
        reverse("save_shopping_scenario"),
        {
            "shopping_context_token": f"{_shopping_token()}tampered",
            "title": "Tampered",
        },
        follow=True,
    )

    assert response.status_code == 200
    assert SavedScenario.objects.filter(user=user).count() == 0
    assert b"no longer valid" in response.content


@pytest.mark.django_db
def test_shopping_save_requires_authentication(shopping_save_reference_data, client):
    response = client.post(
        reverse("save_shopping_scenario"),
        {"shopping_context_token": _shopping_token()},
    )

    assert response.status_code == 302
    assert reverse("login") in response.url
    assert SavedScenario.objects.count() == 0


@pytest.mark.django_db
def test_reopen_shopping_inputs_is_provider_free(
    client,
    shopping_save_reference_data,
):
    with patch("apps.exchange.views.build_latest_quote_gateway") as provider_factory:
        response = client.get(
            reverse("shopping_calculation"),
            {
                "purchase_country": "US",
                "purchase_currency": "USD",
                "home_currency": "EUR",
                "item_price": "100",
                "shipping": "20",
                "known_fees": "10",
                "fx_markup_percent": "2.5",
            },
        )

    assert response.status_code == 200
    assert b'value="100"' in response.content
    assert b'value="20"' in response.content
    assert b'value="10"' in response.content
    assert b'value="2.5"' in response.content
    provider_factory.assert_not_called()


@pytest.mark.django_db
def test_saved_shopping_detail_degrades_when_assumption_payload_is_missing(
    client,
    shopping_save_reference_data,
    caplog,
):
    us, usd, eur = shopping_save_reference_data
    user = User.objects.create_user(username="shopping-missing-payload", password="StrongPass-482!")
    scenario = SavedScenario.objects.create(
        user=user,
        kind=SavedScenarioKind.SHOPPING,
        title="Legacy incomplete purchase",
        source_currency=usd,
        destination_currency=eur,
        source_country=us,
        source_amount=Decimal("130"),
    )
    SavedScenarioObservation.objects.create(
        scenario=scenario,
        kind=SavedScenarioObservationKind.INITIAL,
        input_amount=Decimal("130"),
        output_amount=Decimal("117"),
        rate=Decimal("0.9"),
        effective_date=date(2026, 10, 1),
        fetched_at=datetime(2026, 10, 2, 8, tzinfo=UTC),
        provider_keys=["ecb"],
        stale=False,
    )
    client.force_login(user)

    with caplog.at_level("WARNING", logger="cultural_currency.travel"):
        response = client.get(reverse("saved_scenario_detail", args=(scenario.pk,)))

    assert response.status_code == 200
    assert b"Legacy incomplete purchase" in response.content
    assert b'id="scenario-shopping-title"' not in response.content
    assert reverse("shopping_calculation").encode() in response.content
    assert any(record.msg == "saved_shopping_scenario_payload_missing" for record in caplog.records)
