from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.countries.models import City, Country, CountryCurrency, Currency
from apps.exchange.domain import DEFAULT_SOURCE_POLICY, ConversionResult, RateQuote
from apps.travel.models import SavedScenarioKind
from apps.travel.scenarios import (
    SavedScenarioSpec,
    create_saved_scenario,
    record_scenario_recheck,
    record_scenario_spend,
)

User = get_user_model()


@pytest.fixture(autouse=True)
def use_vite_dev_mode(settings):
    settings.VITE_DEV_SERVER_ENABLED = True


@pytest.fixture
def trip_budget_scenario(db):
    eur = Currency.objects.create(code="EUR", name="Euro", minor_units=2)
    jpy = Currency.objects.create(code="JPY", name="Japanese yen", minor_units=0)
    fi = Country.objects.create(iso2="FI", iso3="FIN", name="Finland")
    jp = Country.objects.create(iso2="JP", iso3="JPN", name="Japan")
    CountryCurrency.objects.create(
        country=fi,
        currency=eur,
        is_primary=True,
        source="https://example.test/fi-eur",
    )
    CountryCurrency.objects.create(
        country=jp,
        currency=jpy,
        is_primary=True,
        source="https://example.test/jp-jpy",
    )
    tokyo = City.objects.create(country=jp, slug="tokyo", name="Tokyo")
    owner = User.objects.create_user(username="trip-budget-owner", password="StrongPass-482!")

    initial = ConversionResult(
        input_amount=Decimal("600"),
        output_amount=Decimal("104700"),
        quote=RateQuote(
            base_currency="EUR",
            quote_currency="JPY",
            rate=Decimal("174.5"),
            requested_date=None,
            effective_date=date(2026, 9, 30),
            fetched_at=datetime(2026, 9, 30, 18, tzinfo=UTC),
            provider_policy=DEFAULT_SOURCE_POLICY,
            provider_keys=("ecb",),
            historical=False,
        ),
        stale=False,
    )
    scenario = create_saved_scenario(
        owner,
        spec=SavedScenarioSpec(
            kind=SavedScenarioKind.BUDGET,
            title="Tokyo five days",
            source_currency=eur,
            destination_currency=jpy,
            source_country=fi,
            destination_country=jp,
            destination_city=tokyo,
            source_amount=Decimal("600"),
            duration_days=5,
            travelers=1,
        ),
        conversion=initial,
    )
    return owner, scenario


@pytest.mark.django_db
def test_saved_budget_detail_shows_original_reference_and_zero_confirmed_spend(
    client,
    trip_budget_scenario,
):
    owner, scenario = trip_budget_scenario
    client.force_login(owner)

    response = client.get(reverse("saved_scenario_detail", args=(scenario.pk,)))

    assert response.status_code == 200
    assert b"Trip budget remaining" in response.content
    assert b"104700 JPY remaining" in response.content
    assert b"Confirmed spend 0 JPY" in response.content
    assert b"About 20940 JPY per planned day" in response.content
    assert b"No confirmed spend has been added yet." in response.content
    assert b"No merchant, receipt image or purchase description is stored here." in response.content


@pytest.mark.django_db
def test_owner_can_add_confirmed_spend_and_remaining_uses_original_baseline(
    client,
    trip_budget_scenario,
):
    owner, scenario = trip_budget_scenario
    client.force_login(owner)

    response = client.post(
        reverse("add_saved_scenario_spend", args=(scenario.pk,)),
        {"amount": "4700"},
    )

    assert response.status_code == 302
    assert response.url == reverse("saved_scenario_detail", args=(scenario.pk,))
    entry = scenario.spend_entries.get()
    assert entry.amount == Decimal("4700.000000000000")

    detail = client.get(response.url)
    assert b"100000 JPY remaining" in detail.content
    assert b"Confirmed spend 4700 JPY" in detail.content
    assert b"About 20000 JPY per planned day" in detail.content


@pytest.mark.django_db
def test_invalid_destination_precision_returns_422_without_persisting_spend(
    client,
    trip_budget_scenario,
):
    owner, scenario = trip_budget_scenario
    client.force_login(owner)

    response = client.post(
        reverse("add_saved_scenario_spend", args=(scenario.pk,)),
        {"amount": "12.5"},
    )

    assert response.status_code == 422
    assert b"This currency supports at most 0 decimal places." in response.content
    assert b'aria-invalid="true"' in response.content
    assert scenario.spend_entries.count() == 0


@pytest.mark.django_db
def test_rate_recheck_never_moves_trip_budget_reference_baseline(client, trip_budget_scenario):
    owner, scenario = trip_budget_scenario
    record_scenario_spend(scenario, amount=Decimal("4700"))
    record_scenario_recheck(
        scenario,
        conversion=ConversionResult(
            input_amount=Decimal("600"),
            output_amount=Decimal("120000"),
            quote=RateQuote(
                base_currency="EUR",
                quote_currency="JPY",
                rate=Decimal("200"),
                requested_date=None,
                effective_date=date(2026, 10, 1),
                fetched_at=datetime(2026, 10, 1, 8, tzinfo=UTC),
                provider_policy=DEFAULT_SOURCE_POLICY,
                provider_keys=("ecb",),
                historical=False,
            ),
            stale=False,
        ),
    )
    client.force_login(owner)

    response = client.get(reverse("saved_scenario_detail", args=(scenario.pk,)))

    assert response.status_code == 200
    assert b"100000 JPY remaining" in response.content
    assert b"saved reference budget 104700 JPY" in response.content
    assert b"120000 JPY" in response.content
    assert (
        b"Re-checking the FX rate never changes this remaining-budget baseline." in response.content
    )


@pytest.mark.django_db
def test_owner_can_remove_spend_and_budget_recalculates(client, trip_budget_scenario):
    owner, scenario = trip_budget_scenario
    entry = record_scenario_spend(scenario, amount=Decimal("4700"))
    client.force_login(owner)

    response = client.post(
        reverse("delete_saved_scenario_spend", args=(scenario.pk, entry.pk)),
    )

    assert response.status_code == 302
    assert response.url == reverse("saved_scenario_detail", args=(scenario.pk,))
    assert scenario.spend_entries.count() == 0
    detail = client.get(response.url)
    assert b"104700 JPY remaining" in detail.content


@pytest.mark.django_db
def test_spend_actions_are_owner_scoped(client, trip_budget_scenario):
    _owner, scenario = trip_budget_scenario
    entry = record_scenario_spend(scenario, amount=Decimal("1000"))
    other = User.objects.create_user(username="trip-budget-other", password="StrongPass-482!")
    client.force_login(other)

    add_response = client.post(
        reverse("add_saved_scenario_spend", args=(scenario.pk,)),
        {"amount": "500"},
    )
    delete_response = client.post(
        reverse("delete_saved_scenario_spend", args=(scenario.pk, entry.pk)),
    )

    assert add_response.status_code == 404
    assert delete_response.status_code == 404
    assert scenario.spend_entries.count() == 1


@pytest.mark.django_db
def test_anonymous_spend_action_redirects_to_sign_in(client, trip_budget_scenario):
    _owner, scenario = trip_budget_scenario

    response = client.post(
        reverse("add_saved_scenario_spend", args=(scenario.pk,)),
        {"amount": "500"},
    )

    assert response.status_code == 302
    assert reverse("login") in response.url
    assert scenario.spend_entries.count() == 0
