from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.countries.models import City, Country, CountryCurrency, Currency
from apps.culture.models import TypicalPrice, TypicalPriceConfidence, TypicalPriceSourceClass
from apps.culture.services import DestinationContext
from apps.exchange.budget_snapshot import build_budget_context_snapshot_token
from apps.exchange.domain import DEFAULT_SOURCE_POLICY, ConversionResult, RateQuote
from apps.exchange.money_context import MoneyContext, MoneyContextState
from apps.travel.models import SavedScenario, SavedScenarioBudgetItem, SavedScenarioObservation

User = get_user_model()


@pytest.fixture(autouse=True)
def use_vite_dev_mode(settings):
    settings.VITE_DEV_SERVER_ENABLED = True


@pytest.fixture
def scenario_reference_data(db):
    eur = Currency.objects.create(code="EUR", name="Euro", symbol="€", minor_units=2)
    jpy = Currency.objects.create(code="JPY", name="Japanese yen", symbol="¥", minor_units=0)
    fi = Country.objects.create(iso2="FI", iso3="FIN", name="Finland")
    jp = Country.objects.create(iso2="JP", iso3="JPN", name="Japan")
    CountryCurrency.objects.create(
        country=fi,
        currency=eur,
        is_primary=True,
        source="https://example.com/fi-eur",
    )
    CountryCurrency.objects.create(
        country=jp,
        currency=jpy,
        is_primary=True,
        source="https://example.com/jp-jpy",
    )
    tokyo = City.objects.create(country=jp, slug="tokyo", name="Tokyo")

    TypicalPrice.objects.create(
        country=jp,
        city="Tokyo",
        city_ref=tokyo,
        category="coffee",
        label="Cup of coffee",
        amount_low=Decimal("300"),
        amount_high=Decimal("600"),
        currency=jpy,
        source_name="Reviewed city context",
        source_url="https://example.com/tokyo-coffee",
        observed_at=timezone.localdate(),
        verified_at=timezone.now(),
        source_class=TypicalPriceSourceClass.APPROXIMATE_CONTEXTUAL,
        confidence=TypicalPriceConfidence.MEDIUM,
        display_order=10,
        is_published=True,
    )
    TypicalPrice.objects.create(
        country=jp,
        city="Tokyo",
        city_ref=tokyo,
        category="casual_meal",
        label="Casual meal",
        amount_low=Decimal("900"),
        amount_high=Decimal("1600"),
        currency=jpy,
        source_name="Reviewed city context",
        source_url="https://example.com/tokyo-meal",
        observed_at=timezone.localdate(),
        verified_at=timezone.now(),
        source_class=TypicalPriceSourceClass.APPROXIMATE_CONTEXTUAL,
        confidence=TypicalPriceConfidence.MEDIUM,
        display_order=20,
        is_published=True,
    )
    return eur, jpy, fi, jp, tokyo


def _budget_context_token() -> str:
    quote = RateQuote(
        base_currency="EUR",
        quote_currency="JPY",
        rate=Decimal("174.50"),
        requested_date=None,
        effective_date=timezone.localdate(),
        fetched_at=timezone.now(),
        provider_policy=DEFAULT_SOURCE_POLICY,
        provider_keys=("ecb",),
        historical=False,
    )
    conversion = ConversionResult(
        input_amount=Decimal("100.00"),
        output_amount=Decimal("17450"),
        quote=quote,
        stale=False,
    )
    destination = DestinationContext(
        country_code="JP",
        country_name="Japan",
        as_of=timezone.localdate(),
        payment=None,
        prices=(),
        city_slug="tokyo",
        city_name="Tokyo",
    )
    context = MoneyContext(
        conversion=conversion,
        destination_country_code="JP",
        destination_city_slug="tokyo",
        as_of=timezone.localdate(),
        destination_context=destination,
        destination_state=MoneyContextState.EMPTY,
    )
    return build_budget_context_snapshot_token(context)


def _prepare_payload() -> dict[str, str]:
    return {
        "budget_context_token": _budget_context_token(),
        "duration_days": "5",
        "travelers": "2",
        "units_coffee": "1",
        "units_casual_meal": "2",
    }


def _extract_draft_token(content: bytes) -> str:
    match = re.search(rb'name="scenario_draft_token"\s+value="([^"]+)"', content)
    assert match is not None
    return match.group(1).decode()


@override_settings(VITE_DEV_SERVER_ENABLED=True)
@pytest.mark.django_db
def test_prepare_saved_scenario_requires_authentication(client, scenario_reference_data):
    response = client.post(reverse("prepare_saved_scenario"), _prepare_payload())

    assert response.status_code == 302
    assert reverse("login") in response["Location"]


@pytest.mark.django_db
def test_prepare_and_create_saved_trip_is_complete_no_javascript_flow(
    client,
    scenario_reference_data,
):
    user = User.objects.create_user(username="owner", password="StrongPass-482!")
    client.force_login(user)

    prepared = client.post(reverse("prepare_saved_scenario"), _prepare_payload())

    assert prepared.status_code == 200
    assert b"Keep the assumptions, not a frozen promise" in prepared.content
    assert b"Tokyo, Japan" in prepared.content
    assert b"100.00 EUR" in prepared.content
    assert b"17450 JPY" in prepared.content
    draft_token = _extract_draft_token(prepared.content)

    created = client.post(
        reverse("create_saved_scenario"),
        {
            "scenario_draft_token": draft_token,
            "kind": "trip",
            "title": "Tokyo spring trip",
            "travel_start_date": "2027-04-12",
            "travel_end_date": "2027-04-16",
        },
    )

    scenario = SavedScenario.objects.get(user=user)
    assert created.status_code == 302
    assert created["Location"] == reverse(
        "saved_scenario_detail",
        kwargs={"scenario_id": scenario.pk},
    )
    assert scenario.title == "Tokyo spring trip"
    assert scenario.destination_country.iso2 == "JP"
    assert scenario.destination_city.slug == "tokyo"
    assert scenario.source_amount == Decimal("100.00")
    assert scenario.duration_days == 5
    assert scenario.travelers == 2
    assert scenario.travel_start_date == date(2027, 4, 12)
    assert scenario.travel_end_date == date(2027, 4, 16)
    assert set(
        SavedScenarioBudgetItem.objects.filter(scenario=scenario).values_list(
            "category",
            flat=True,
        )
    ) == {"coffee", "casual_meal"}
    observation = SavedScenarioObservation.objects.get(scenario=scenario)
    assert observation.input_amount == Decimal("100.00")
    assert observation.output_amount == Decimal("17450")
    assert observation.provider_keys == ["ecb"]

    detail = client.get(created["Location"])
    assert detail.status_code == 200
    assert b"Tokyo spring trip" in detail.content
    assert b"Starting FX observation" in detail.content
    assert b"Open in converter" in detail.content


@pytest.mark.django_db
def test_create_saved_scenario_rejects_tampered_draft_without_writing(
    client,
    scenario_reference_data,
):
    user = User.objects.create_user(username="owner", password="StrongPass-482!")
    client.force_login(user)

    response = client.post(
        reverse("create_saved_scenario"),
        {
            "scenario_draft_token": "tampered",
            "kind": "trip",
            "title": "Should not persist",
        },
    )

    assert response.status_code == 422
    assert b"no longer valid" in response.content
    assert not SavedScenario.objects.filter(user=user).exists()


@pytest.mark.django_db
def test_saved_scenario_detail_and_delete_are_owner_scoped(
    client,
    scenario_reference_data,
):
    owner = User.objects.create_user(username="owner", password="StrongPass-482!")
    other = User.objects.create_user(username="other", password="StrongPass-573!")
    client.force_login(owner)

    prepared = client.post(reverse("prepare_saved_scenario"), _prepare_payload())
    draft_token = _extract_draft_token(prepared.content)
    created = client.post(
        reverse("create_saved_scenario"),
        {
            "scenario_draft_token": draft_token,
            "kind": "budget",
            "title": "Tokyo budget",
        },
    )
    scenario = SavedScenario.objects.get(user=owner)
    assert created.status_code == 302

    client.force_login(other)
    detail = client.get(
        reverse("saved_scenario_detail", kwargs={"scenario_id": scenario.pk})
    )
    delete = client.post(
        reverse("delete_saved_scenario", kwargs={"scenario_id": scenario.pk})
    )
    assert detail.status_code == 404
    assert delete.status_code == 404
    assert SavedScenario.objects.filter(pk=scenario.pk).exists()

    client.force_login(owner)
    delete = client.post(
        reverse("delete_saved_scenario", kwargs={"scenario_id": scenario.pk})
    )
    assert delete.status_code == 302
    assert delete["Location"] == reverse("saved_state")
    assert not SavedScenario.objects.filter(pk=scenario.pk).exists()


@pytest.mark.django_db
def test_saved_state_lists_only_current_users_plans(client, scenario_reference_data):
    owner = User.objects.create_user(username="owner", password="StrongPass-482!")
    other = User.objects.create_user(username="other", password="StrongPass-573!")
    client.force_login(owner)

    prepared = client.post(reverse("prepare_saved_scenario"), _prepare_payload())
    draft_token = _extract_draft_token(prepared.content)
    client.post(
        reverse("create_saved_scenario"),
        {
            "scenario_draft_token": draft_token,
            "kind": "trip",
            "title": "Owner Tokyo plan",
        },
    )

    scenario = SavedScenario.objects.get(user=owner)
    scenario.pk = None
    scenario.user = other
    scenario.title = "Other private plan"
    scenario.save()

    response = client.get(reverse("saved_state"))

    assert response.status_code == 200
    assert b"Saved plans" in response.content
    assert b"Owner Tokyo plan" in response.content
    assert b"Other private plan" not in response.content
