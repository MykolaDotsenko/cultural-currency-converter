from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.countries.models import City, Country, CountryCurrency, Currency
from apps.culture.services import DestinationContext
from apps.exchange.budget import BudgetCategoryAssumption
from apps.exchange.budget_snapshot import build_budget_context_snapshot_token
from apps.exchange.domain import DEFAULT_SOURCE_POLICY, ConversionResult, RateQuote
from apps.exchange.money_context import MoneyContext, MoneyContextState
from apps.exchange.shopping import ShoppingAssumptions
from apps.exchange.shopping_snapshot import build_shopping_context_snapshot_token
from apps.travel.browser_scenario import (
    BrowserScenarioTokenError,
    build_browser_scenario_token,
    import_browser_scenarios,
    load_browser_scenario_token,
)
from apps.travel.models import SavedScenario, SavedScenarioKind
from apps.travel.scenarios import SavedScenarioSpec

User = get_user_model()


@pytest.fixture(autouse=True)
def use_vite_dev_mode(settings):
    settings.VITE_DEV_SERVER_ENABLED = True


@pytest.fixture
def browser_scenario_reference_data(db):
    eur = Currency.objects.create(code="EUR", name="Euro", symbol="€", minor_units=2)
    jpy = Currency.objects.create(code="JPY", name="Japanese yen", symbol="¥", minor_units=0)
    usd = Currency.objects.create(code="USD", name="US dollar", symbol="$", minor_units=2)
    fi = Country.objects.create(iso2="FI", iso3="FIN", name="Finland")
    jp = Country.objects.create(iso2="JP", iso3="JPN", name="Japan")
    us = Country.objects.create(iso2="US", iso3="USA", name="United States")
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
        country=us,
        currency=usd,
        is_primary=True,
        source="test",
    )
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


def _budget_issue_payload() -> dict[str, str]:
    return {
        "budget_context_token": _budget_context_token(),
        "title": "Browser Tokyo budget",
        "duration_days": "5",
        "travelers": "2",
        "travel_start_date": "2027-04-12",
        "travel_end_date": "2027-04-18",
        "units_coffee": "1",
        "units_casual_meal": "2",
        "units_transit": "2",
    }


@pytest.mark.django_db
def test_browser_scenario_token_round_trip_preserves_explicit_budget_truth(
    browser_scenario_reference_data,
):
    eur, jpy, _usd, _fi, jp, _us, tokyo = browser_scenario_reference_data
    origin_key = uuid4()
    spec = SavedScenarioSpec(
        kind=SavedScenarioKind.BUDGET,
        title="Browser Tokyo budget",
        source_currency=eur,
        destination_currency=jpy,
        destination_country=jp,
        destination_city=tokyo,
        source_amount=Decimal("600"),
        duration_days=5,
        travelers=2,
        travel_start_date=date(2027, 4, 12),
        travel_end_date=date(2027, 4, 18),
        budget_categories=(
            BudgetCategoryAssumption(
                category="coffee",
                units_per_person_per_day=Decimal("1"),
            ),
        ),
        browser_import_key=origin_key,
    )

    issued = build_browser_scenario_token(
        spec=spec,
        conversion=_budget_conversion(),
    )
    snapshot = load_browser_scenario_token(issued.token)

    assert snapshot.origin_key == origin_key
    assert snapshot.kind == SavedScenarioKind.BUDGET
    assert snapshot.title == "Browser Tokyo budget"
    assert snapshot.destination_country_code == "JP"
    assert snapshot.destination_city_slug == "tokyo"
    assert snapshot.duration_days == 5
    assert snapshot.travelers == 2
    assert snapshot.travel_start_date == date(2027, 4, 12)
    assert snapshot.travel_end_date == date(2027, 4, 18)
    assert snapshot.conversion.input_amount == Decimal("600")
    assert snapshot.conversion.output_amount == Decimal("104700")
    assert snapshot.conversion.quote.rate == Decimal("174.50")
    assert snapshot.conversion.quote.provider_keys == ("ecb",)


@pytest.mark.django_db
def test_browser_scenario_token_fails_closed_on_tampering(browser_scenario_reference_data):
    eur, jpy, _usd, _fi, jp, _us, tokyo = browser_scenario_reference_data
    issued = build_browser_scenario_token(
        spec=SavedScenarioSpec(
            kind=SavedScenarioKind.BUDGET,
            title="Tokyo",
            source_currency=eur,
            destination_currency=jpy,
            destination_country=jp,
            destination_city=tokyo,
            source_amount=Decimal("600"),
            duration_days=3,
            travelers=1,
            budget_categories=(
                BudgetCategoryAssumption(
                    category="coffee",
                    units_per_person_per_day=Decimal("1"),
                ),
            ),
        ),
        conversion=_budget_conversion(),
    )

    with pytest.raises(BrowserScenarioTokenError, match="invalid"):
        load_browser_scenario_token(issued.token + "tampered")


@pytest.mark.django_db
def test_anonymous_budget_issue_validates_and_signs_without_account_persistence(
    client,
    browser_scenario_reference_data,
):
    response = client.post(
        reverse("issue_browser_budget_scenario"),
        _budget_issue_payload(),
    )

    assert response.status_code == 200
    assert response["Cache-Control"] == "private, no-store"
    assert SavedScenario.objects.count() == 0
    payload = response.json()["scenario"]
    assert payload["kind"] == "budget"
    assert payload["title"] == "Browser Tokyo budget"
    assert payload["scope"] == "Tokyo"
    assert payload["sourceCurrency"] == "EUR"
    assert payload["destinationCurrency"] == "JPY"
    assert payload["sourceAmount"] == "600"
    assert payload["reopenUrl"].startswith(reverse("converter"))

    snapshot = load_browser_scenario_token(payload["token"])
    assert str(snapshot.origin_key) == payload["id"]
    assert snapshot.duration_days == 5
    assert snapshot.travelers == 2


@pytest.mark.django_db
def test_anonymous_shopping_issue_validates_and_signs_without_account_persistence(
    client,
    browser_scenario_reference_data,
):
    response = client.post(
        reverse("issue_browser_shopping_scenario"),
        {
            "shopping_context_token": _shopping_context_token(),
            "title": "Browser US headphones",
        },
    )

    assert response.status_code == 200
    assert response["Cache-Control"] == "private, no-store"
    assert SavedScenario.objects.count() == 0
    payload = response.json()["scenario"]
    assert payload["kind"] == "shopping"
    assert payload["title"] == "Browser US headphones"
    assert payload["scope"] == "United States"
    assert payload["sourceCurrency"] == "USD"
    assert payload["destinationCurrency"] == "EUR"
    assert "purchase_country=US" in payload["reopenUrl"]

    snapshot = load_browser_scenario_token(payload["token"])
    assert snapshot.shopping_assumptions is not None
    assert snapshot.shopping_assumptions.purchase_total == Decimal("130")


@pytest.mark.django_db
def test_browser_scenario_import_is_explicit_idempotent_and_owner_scoped(
    client,
    browser_scenario_reference_data,
):
    issue = client.post(reverse("issue_browser_budget_scenario"), _budget_issue_payload()).json()
    token = issue["scenario"]["token"]
    origin_key = issue["scenario"]["id"]
    owner = User.objects.create_user(username="browser-import-owner", password="StrongPass-482!")
    other = User.objects.create_user(username="browser-import-other", password="StrongPass-482!")
    client.force_login(owner)

    first = client.post(
        reverse("import_browser_scenarios"),
        data=json.dumps({"scenarios": [token]}),
        content_type="application/json",
    )
    second = client.post(
        reverse("import_browser_scenarios"),
        data=json.dumps({"scenarios": [token]}),
        content_type="application/json",
    )

    assert first.status_code == 200
    assert first.json()["createdCount"] == 1
    assert first.json()["importedOriginKeys"] == [origin_key]
    assert second.status_code == 200
    assert second.json()["createdCount"] == 0
    assert SavedScenario.objects.filter(user=owner).count() == 1
    scenario = SavedScenario.objects.get(user=owner)
    assert str(scenario.browser_import_key) == origin_key
    assert scenario.title == "Browser Tokyo budget"
    assert scenario.destination_city.slug == "tokyo"
    assert SavedScenario.objects.filter(user=other).count() == 0


@pytest.mark.django_db
def test_browser_scenario_import_batch_is_atomic_when_one_token_is_invalid(
    client,
    browser_scenario_reference_data,
):
    issue = client.post(reverse("issue_browser_budget_scenario"), _budget_issue_payload()).json()
    owner = User.objects.create_user(username="browser-atomic-owner", password="StrongPass-482!")
    client.force_login(owner)

    response = client.post(
        reverse("import_browser_scenarios"),
        data=json.dumps(
            {
                "scenarios": [
                    issue["scenario"]["token"],
                    issue["scenario"]["token"] + "tampered",
                ]
            }
        ),
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_scenarios"
    assert SavedScenario.objects.filter(user=owner).count() == 0


@pytest.mark.django_db
def test_browser_scenario_import_requires_auth_and_strict_json(
    client,
    browser_scenario_reference_data,
):
    token = client.post(
        reverse("issue_browser_budget_scenario"),
        _budget_issue_payload(),
    ).json()["scenario"]["token"]

    anonymous = client.post(
        reverse("import_browser_scenarios"),
        data=json.dumps({"scenarios": [token]}),
        content_type="application/json",
    )
    assert anonymous.status_code == 302
    assert reverse("login") in anonymous.url

    user = User.objects.create_user(username="browser-json-owner", password="StrongPass-482!")
    client.force_login(user)
    wrong_type = client.post(
        reverse("import_browser_scenarios"),
        data="scenarios=x",
        content_type="text/plain",
    )
    assert wrong_type.status_code == 415
    assert wrong_type.json()["error"]["code"] == "unsupported_media_type"


@pytest.mark.django_db
def test_sign_in_and_saved_page_do_not_import_browser_scenarios_implicitly(
    client,
    browser_scenario_reference_data,
):
    issue = client.post(reverse("issue_browser_budget_scenario"), _budget_issue_payload()).json()
    assert load_browser_scenario_token(issue["scenario"]["token"]).kind == SavedScenarioKind.BUDGET

    user = User.objects.create_user(username="browser-no-auto-owner", password="StrongPass-482!")
    client.force_login(user)
    response = client.get(reverse("saved_state"))

    assert response.status_code == 200
    assert b"Browser-only scenarios" in response.content
    assert b"Import browser scenarios to account" in response.content
    assert SavedScenario.objects.filter(user=user).count() == 0


@pytest.mark.django_db
def test_service_import_can_be_retried_without_duplicate_rows(
    browser_scenario_reference_data,
):
    eur, jpy, _usd, _fi, jp, _us, tokyo = browser_scenario_reference_data
    user = User.objects.create_user(username="browser-service-owner", password="StrongPass-482!")
    issued = build_browser_scenario_token(
        spec=SavedScenarioSpec(
            kind=SavedScenarioKind.BUDGET,
            title="Service import",
            source_currency=eur,
            destination_currency=jpy,
            destination_country=jp,
            destination_city=tokyo,
            source_amount=Decimal("600"),
            duration_days=3,
            travelers=1,
            budget_categories=(
                BudgetCategoryAssumption(
                    category="coffee",
                    units_per_person_per_day=Decimal("1"),
                ),
            ),
        ),
        conversion=_budget_conversion(),
    )

    first = import_browser_scenarios(user, [issued.token])
    second = import_browser_scenarios(user, [issued.token])

    assert first.created_count == 1
    assert second.created_count == 0
    assert first.scenario_ids == second.scenario_ids
    assert SavedScenario.objects.filter(user=user).count() == 1
