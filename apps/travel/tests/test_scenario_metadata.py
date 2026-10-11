"""Editing saved scenario metadata is owner-scoped and preserves money observations."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.countries.models import Country, Currency
from apps.travel.models import (
    SavedScenario,
    SavedScenarioKind,
    SavedScenarioObservation,
    SavedScenarioObservationKind,
    SavedScenarioSpendEntry,
    SavedScenarioSpendSource,
)


@pytest.fixture(autouse=True)
def vite_test_mode(settings):
    settings.VITE_DEV_SERVER_ENABLED = True


@pytest.fixture
def owned_scenario(db):
    owner = get_user_model().objects.create_user(
        username="metadata-owner", password="Owner-Password-865!"
    )
    other = get_user_model().objects.create_user(
        username="metadata-other", password="Other-Password-534!"
    )
    eur = Currency.objects.create(code="EUR", name="Euro")
    jpy = Currency.objects.create(code="JPY", name="Japanese yen", minor_units=0)
    jp = Country.objects.create(iso2="JP", iso3="JPN", name="Japan")
    scenario = SavedScenario.objects.create(
        user=owner,
        kind=SavedScenarioKind.BUDGET,
        title="Initial Tokyo budget",
        source_currency=eur,
        destination_currency=jpy,
        destination_country=jp,
        source_amount=Decimal("500.00"),
        travelers=2,
        duration_days=5,
        travel_start_date=date(2027, 4, 5),
        travel_end_date=date(2027, 4, 10),
    )
    observation = SavedScenarioObservation.objects.create(
        scenario=scenario,
        kind=SavedScenarioObservationKind.INITIAL,
        input_amount=Decimal("500"),
        output_amount=Decimal("75000"),
        rate=Decimal("150"),
        effective_date=date(2026, 10, 10),
        fetched_at=timezone.now(),
        provider_keys=["synthetic-test"],
    )
    spend = SavedScenarioSpendEntry.objects.create(
        scenario=scenario,
        amount=Decimal("250"),
        source=SavedScenarioSpendSource.MANUAL,
        submission_key=uuid4(),
    )
    return owner, other, scenario, observation, spend


@pytest.mark.django_db
def test_owner_can_update_title_and_dates_without_changing_financial_baseline(
    client, owned_scenario
):
    owner, _other, scenario, observation, spend = owned_scenario
    client.force_login(owner)
    url = reverse("edit_saved_scenario", args=(scenario.pk,))
    page = client.get(url)
    assert page.status_code == 200
    assert b"original exchange-rate observation" in page.content
    version = page.context["version"]
    response = client.post(
        url,
        {
            "version": version,
            "title": "New trip title",
            "travel_start_date": "2027-05-05",
            "travel_end_date": "2027-05-10",
            "source_amount": "99999999",
            "travelers": "20",
        },
    )
    assert response.status_code == 302
    assert response.url == reverse("saved_scenario_detail", args=(scenario.pk,))
    scenario.refresh_from_db()
    assert scenario.title == "New trip title"
    assert scenario.travel_start_date == date(2027, 5, 5)
    assert scenario.travel_end_date == date(2027, 5, 10)
    assert scenario.source_amount == Decimal("500")
    assert scenario.travelers == 2
    observation.refresh_from_db()
    spend.refresh_from_db()
    assert observation.output_amount == Decimal("75000")
    assert observation.effective_date == date(2026, 10, 10)
    assert spend.amount == Decimal("250")


@pytest.mark.django_db
def test_stale_editor_rejected_and_latest_metadata_shown(client, owned_scenario):
    owner, _other, scenario, _obs, _spent = owned_scenario
    client.force_login(owner)
    url = reverse("edit_saved_scenario", args=(scenario.pk,))
    version = client.get(url).context["version"]
    scenario.title = "Updated in another tab"
    scenario.save(update_fields=["title", "updated_at"])
    response = client.post(url, {"version": version, "title": "Stale overwrite"})
    assert response.status_code == 409
    assert b"changed since you opened" in response.content
    scenario.refresh_from_db()
    assert scenario.title == "Updated in another tab"


@pytest.mark.django_db
def test_invalid_date_order_and_missing_start_cannot_be_saved(client, owned_scenario):
    owner, _other, scenario, _obs, _spent = owned_scenario
    client.force_login(owner)
    url = reverse("edit_saved_scenario", args=(scenario.pk,))
    for start, end in (("2027-05-10", "2027-05-01"), ("", "2027-05-01")):
        version = client.get(url).context["version"]
        result = client.post(
            url,
            {
                "version": version,
                "title": "Invalid",
                "travel_start_date": start,
                "travel_end_date": end,
            },
        )
        assert result.status_code == 422
        scenario.refresh_from_db()
        assert scenario.title == "Initial Tokyo budget"


@pytest.mark.django_db
def test_user_cannot_read_or_edit_another_users_scenario(client, owned_scenario):
    _owner, other, scenario, _obs, _spent = owned_scenario
    client.force_login(other)
    url = reverse("edit_saved_scenario", args=(scenario.pk,))
    assert client.get(url).status_code == 404
    assert client.post(url, {"title": "Hacked", "version": "123"}).status_code == 404
    scenario.refresh_from_db()
    assert scenario.title == "Initial Tokyo budget"


@pytest.mark.django_db
def test_anonymous_user_cannot_edit_scenario(client, owned_scenario):
    _owner, _other, scenario, _obs, _spent = owned_scenario
    path = reverse("edit_saved_scenario", args=(scenario.pk,))
    response = client.get(path)
    assert response.status_code == 302
    assert reverse("login") in response["Location"]


@pytest.mark.django_db
def test_edit_requires_valid_csrf_token(owned_scenario):
    owner, _other, scenario, _obs, _spent = owned_scenario
    client = Client(enforce_csrf_checks=True)
    client.force_login(owner)
    response = client.post(
        reverse("edit_saved_scenario", args=(scenario.pk,)),
        {"version": scenario.updated_at.isoformat(), "title": "CSRF bypass"},
    )
    assert response.status_code == 403
    scenario.refresh_from_db()
    assert scenario.title == "Initial Tokyo budget"


@pytest.mark.django_db
def test_shopping_scenario_can_rename_but_cannot_change_trip_dates(client, owned_scenario):
    owner, _other, budget, _obs, _spent = owned_scenario
    client.force_login(owner)
    shopping = SavedScenario.objects.create(
        user=owner,
        kind=SavedScenarioKind.SHOPPING,
        title="Purchase",
        source_currency=budget.source_currency,
        destination_currency=budget.destination_currency,
        source_amount=Decimal("10"),
    )
    url = reverse("edit_saved_scenario", args=(shopping.pk,))
    page = client.get(url)
    assert page.status_code == 200
    assert "travel_start_date" not in page.context["form"].fields
    saved = client.post(
        url,
        {
            "version": page.context["version"],
            "title": "Renamed purchase",
            "travel_start_date": "2027-06-01",
            "travel_end_date": "2027-06-07",
        },
    )
    assert saved.status_code == 302
    shopping.refresh_from_db()
    assert shopping.title == "Renamed purchase"
    assert shopping.travel_start_date is None
    assert shopping.travel_end_date is None
