from __future__ import annotations

import json
from dataclasses import fields
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.countries.models import City, Country, CountryCurrency, Currency
from apps.culture.services import DestinationContext
from apps.exchange.budget_snapshot import build_budget_context_snapshot_token
from apps.exchange.domain import DEFAULT_SOURCE_POLICY, ConversionResult, RateQuote
from apps.exchange.money_context import MoneyContext, MoneyContextState
from apps.exchange.shopping import ShoppingAssumptions
from apps.exchange.shopping_snapshot import build_shopping_context_snapshot_token
from apps.travel.local_scenario_snapshot import (
    LocalScenarioSnapshot,
    load_local_scenario_token,
)
from apps.travel.models import SavedScenario, SavedScenarioKind

User = get_user_model()


@pytest.fixture(autouse=True)
def use_vite_dev_mode(settings):
    settings.VITE_DEV_SERVER_ENABLED = True


@pytest.fixture
def local_scenario_reference_data(db):
    eur = Currency.objects.create(code="EUR", name="Euro", symbol="€", minor_units=2)
    jpy = Currency.objects.create(code="JPY", name="Japanese yen", symbol="¥", minor_units=0)
    usd = Currency.objects.create(code="USD", name="US dollar", symbol="$", minor_units=2)
    fi = Country.objects.create(iso2="FI", iso3="FIN", name="Finland")
    jp = Country.objects.create(iso2="JP", iso3="JPN", name="Japan")
    us = Country.objects.create(iso2="US", iso3="USA", name="United States")
    CountryCurrency.objects.create(country=fi, currency=eur, is_primary=True, source="test")
    CountryCurrency.objects.create(country=jp, currency=jpy, is_primary=True, source="test")
    CountryCurrency.objects.create(country=us, currency=usd, is_primary=True, source="test")
    tokyo = City.objects.create(country=jp, slug="tokyo", name="Tokyo")
    return eur, jpy, usd, fi, jp, us, tokyo


def _budget_conversion() -> ConversionResult:
    return ConversionResult(
        input_amount=Decimal("600.00"),
        output_amount=Decimal("104700"),
        quote=RateQuote(
            base_currency="EUR",
            quote_currency="JPY",
            rate=Decimal("174.50"),
            requested_date=None,
            effective_date=date(2026, 9, 30),
            fetched_at=datetime(2026, 9, 30, 18, tzinfo=UTC),
            provider_policy=DEFAULT_SOURCE_POLICY,
            provider_keys=("ecb",),
            historical=False,
        ),
        stale=False,
    )


def _budget_context_token() -> str:
    destination = DestinationContext(
        country_code="JP",
        country_name="Japan",
        as_of=date(2026, 9, 30),
        payment=None,
        prices=(),
        city_slug="tokyo",
        city_name="Tokyo",
    )
    return build_budget_context_snapshot_token(
        MoneyContext(
            conversion=_budget_conversion(),
            destination_country_code="JP",
            destination_city_slug="tokyo",
            as_of=date(2026, 9, 30),
            destination_context=destination,
            destination_state=MoneyContextState.EMPTY,
        )
    )


def _shopping_context_token() -> str:
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


def _create_budget_local(client):
    return client.post(
        reverse("create_local_budget_scenario"),
        {
            "budget_context_token": _budget_context_token(),
            "title": "Tokyo browser plan",
            "duration_days": "5",
            "travelers": "2",
            "travel_start_date": "2027-04-12",
            "travel_end_date": "2027-04-18",
            "units_coffee": "1",
            "units_casual_meal": "2",
            "units_transit": "2",
        },
    )


@pytest.mark.django_db
def test_anonymous_budget_save_returns_signed_envelope_without_server_persistence(
    client,
    local_scenario_reference_data,
):
    response = _create_budget_local(client)

    assert response.status_code == 200
    assert response["Cache-Control"] == "private, no-store"
    assert SavedScenario.objects.count() == 0

    body = response.json()
    snapshot = load_local_scenario_token(body["token"])
    assert snapshot.kind == SavedScenarioKind.BUDGET
    assert snapshot.title == "Tokyo browser plan"
    assert snapshot.scope_label == "Tokyo, Japan"
    assert snapshot.source_amount == Decimal("600.00")
    assert snapshot.source_currency_code == "EUR"
    assert snapshot.destination_currency_code == "JPY"
    assert snapshot.destination_country_code == "JP"
    assert snapshot.destination_city_slug == "tokyo"
    assert snapshot.duration_days == 5
    assert snapshot.travelers == 2
    assert snapshot.travel_start_date == date(2027, 4, 12)
    assert snapshot.travel_end_date == date(2027, 4, 18)
    assert snapshot.conversion.output_amount == Decimal("104700")
    assert snapshot.conversion.quote.provider_keys == ("ecb",)

    # The portable snapshot has no account/user field by construction.
    assert "user" not in {field.name for field in fields(LocalScenarioSnapshot)}
    assert "account" not in {field.name for field in fields(LocalScenarioSnapshot)}
    UUID(body["scenario"]["id"])
    assert body["scenario"]["scopeLabel"] == "Tokyo, Japan"
    assert body["detailUrl"] == reverse("local_scenario_detail")


@pytest.mark.django_db
def test_anonymous_shopping_save_returns_signed_envelope_without_server_persistence(
    client,
    local_scenario_reference_data,
):
    response = client.post(
        reverse("create_local_shopping_scenario"),
        {
            "shopping_context_token": _shopping_context_token(),
            "title": "US headphones",
        },
    )

    assert response.status_code == 200
    assert SavedScenario.objects.count() == 0
    snapshot = load_local_scenario_token(response.json()["token"])
    assert snapshot.kind == SavedScenarioKind.SHOPPING
    assert snapshot.scope_label == "United States purchase"
    assert snapshot.source_country_code == "US"
    assert snapshot.destination_country_code == ""
    assert snapshot.shopping_assumptions is not None
    assert snapshot.shopping_assumptions.item_price == Decimal("100")
    assert snapshot.shopping_assumptions.shipping == Decimal("20")
    assert snapshot.shopping_assumptions.known_fees == Decimal("10")
    assert snapshot.shopping_assumptions.fx_markup_percent == Decimal("2.5")


@pytest.mark.django_db
def test_local_detail_is_provider_and_database_free(
    client,
    local_scenario_reference_data,
    django_assert_num_queries,
):
    token = _create_budget_local(client).json()["token"]

    with django_assert_num_queries(0):
        response = client.post(reverse("local_scenario_detail"), {"snapshot": token})

    assert response.status_code == 200
    assert response["Cache-Control"] == "private, no-store"
    assert response["X-Robots-Tag"] == "noindex, nofollow"
    assert response["Referrer-Policy"] == "no-referrer"
    body = response.content.decode("utf-8")
    assert "Tokyo browser plan" in body
    assert "600 EUR" in body
    assert "104700 JPY" in body
    assert "30 Sep 2026" in body
    assert "performs no FX request" in body
    assert "Signing protects integrity, not confidentiality" in body


@pytest.mark.django_db
def test_local_import_requires_explicit_authenticated_request(
    client,
    local_scenario_reference_data,
):
    token = _create_budget_local(client).json()["token"]

    response = client.post(
        reverse("import_local_scenarios"),
        data=json.dumps({"tokens": [token]}),
        content_type="application/json",
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"
    assert SavedScenario.objects.count() == 0


@pytest.mark.django_db
def test_local_import_is_idempotent_and_preserves_immutable_observation(
    client,
    local_scenario_reference_data,
):
    token_response = _create_budget_local(client).json()
    token = token_response["token"]
    local_id = token_response["scenario"]["id"]
    user = User.objects.create_user(username="local-import-owner", password="StrongPass-482!")
    client.force_login(user)

    first = client.post(
        reverse("import_local_scenarios"),
        data=json.dumps({"tokens": [token]}),
        content_type="application/json",
    )
    second = client.post(
        reverse("import_local_scenarios"),
        data=json.dumps({"tokens": [token]}),
        content_type="application/json",
    )

    assert first.status_code == 200
    assert first.json()["importedCount"] == 1
    assert first.json()["createdCount"] == 1
    assert first.json()["items"][0]["localId"] == local_id
    assert second.status_code == 200
    assert second.json()["importedCount"] == 1
    assert second.json()["createdCount"] == 0

    scenarios = SavedScenario.objects.filter(user=user)
    assert scenarios.count() == 1
    scenario = scenarios.get()
    assert str(scenario.import_key) == local_id
    assert scenario.title == "Tokyo browser plan"
    assert scenario.destination_city.slug == "tokyo"
    assert scenario.duration_days == 5
    assert scenario.travelers == 2
    assert scenario.budget_items.count() == 3
    assert scenario.observations.count() == 1
    observation = scenario.observations.get()
    assert observation.input_amount == Decimal("600")
    assert observation.output_amount == Decimal("104700")
    assert observation.rate == Decimal("174.5")
    assert observation.effective_date == date(2026, 9, 30)
    assert observation.provider_keys == ["ecb"]


@pytest.mark.django_db
def test_tampered_or_mixed_import_fails_closed_without_partial_writes(
    client,
    local_scenario_reference_data,
):
    valid = _create_budget_local(client).json()["token"]
    user = User.objects.create_user(username="local-import-tamper", password="StrongPass-482!")
    client.force_login(user)

    response = client.post(
        reverse("import_local_scenarios"),
        data=json.dumps({"tokens": [valid, valid + "tampered"]}),
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_local_scenario"
    assert SavedScenario.objects.filter(user=user).count() == 0


@pytest.mark.django_db
def test_local_import_rejects_duplicate_token_in_same_batch(
    client,
    local_scenario_reference_data,
):
    token = _create_budget_local(client).json()["token"]
    user = User.objects.create_user(username="local-import-duplicate", password="StrongPass-482!")
    client.force_login(user)

    response = client.post(
        reverse("import_local_scenarios"),
        data=json.dumps({"tokens": [token, token]}),
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "duplicate_import"
    assert SavedScenario.objects.filter(user=user).count() == 0


@pytest.mark.django_db
def test_local_detail_get_does_not_expose_snapshot_transport(
    client,
    local_scenario_reference_data,
):
    token = _create_budget_local(client).json()["token"]

    response = client.get(reverse("local_scenario_detail"), {"snapshot": token})

    assert response.status_code == 405
    assert token not in (response.headers.get("Location") or "")
