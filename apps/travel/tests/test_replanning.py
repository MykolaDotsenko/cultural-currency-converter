"""Budget replanning is an explicit, versioned owner-only operation."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.countries.models import Country, Currency
from apps.travel.models import (
    SavedScenario,
    SavedScenarioBudgetItem,
    SavedScenarioKind,
    SavedScenarioObservation,
    SavedScenarioObservationKind,
    SavedScenarioSpendEntry,
    SavedScenarioSpendSource,
)
from apps.travel.replanning import ReplanningError, replan_budget


@pytest.fixture(autouse=True)
def vite_test_mode(settings):
    settings.VITE_DEV_SERVER_ENABLED = True


@pytest.fixture
def budget(db):
    user = get_user_model().objects.create_user(
        username="replanning-owner", password="Test-Owner-984!"
    )
    stranger = get_user_model().objects.create_user(
        username="replanning-other", password="Other-Password-873!"
    )
    eur = Currency.objects.create(code="EUR", name="Euro")
    jpy = Currency.objects.create(code="JPY", name="Japanese yen", minor_units=0)
    japan = Country.objects.create(iso2="JP", iso3="JPN", name="Japan")
    scenario = SavedScenario.objects.create(
        user=user,
        kind=SavedScenarioKind.BUDGET,
        title="Trip to Japan",
        source_currency=eur,
        destination_currency=jpy,
        destination_country=japan,
        source_amount=Decimal("500.00"),
        travelers=2,
        duration_days=6,
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
        amount=Decimal("350"),
        source=SavedScenarioSpendSource.MANUAL,
        submission_key=uuid4(),
    )
    return user, stranger, scenario, observation, spend


@pytest.mark.django_db
def test_owner_changes_duration_and_travelers_with_append_only_history(client, budget):
    owner, _other, scenario, observation, spend = budget
    client.force_login(owner)
    url = reverse("replan_saved_budget", args=(scenario.pk,))
    page = client.get(url)
    assert page.status_code == 200
    assert b"original exchange-rate observation" in page.content
    res = client.post(
        url,
        {"version": page.context["version"], "travelers": "3", "duration_days": "9"},
    )
    assert res.status_code == 302
    assert res.url == reverse("saved_scenario_detail", args=(scenario.pk,))
    scenario.refresh_from_db()
    assert (scenario.travelers, scenario.duration_days) == (3, 9)
    assert list(scenario.plan_revisions.values_list("revision", "travelers", "duration_days")) == [
        (0, 2, 6),
        (1, 3, 9),
    ]
    observation.refresh_from_db()
    spend.refresh_from_db()
    assert observation.output_amount == Decimal("75000")
    assert spend.amount == Decimal("350")
    assert scenario.source_amount == Decimal("500.00")


@pytest.mark.django_db
def test_replan_noop_creates_no_history_and_does_not_change_version(budget):
    owner, _other, scenario, _obs, _spend = budget
    original = scenario.updated_at
    assert (
        replan_budget(
            owner_id=owner.pk,
            scenario_id=scenario.pk,
            expected_version=original.isoformat(),
            travelers=2,
            duration_days=6,
        )
        is False
    )
    scenario.refresh_from_db()
    assert scenario.updated_at == original
    assert not scenario.plan_revisions.exists()


@pytest.mark.django_db
def test_stale_editor_conflict_is_http_409_and_preserves_latest_values(client, budget):
    owner, _other, scenario, _obs, _spend = budget
    client.force_login(owner)
    url = reverse("replan_saved_budget", args=(scenario.pk,))
    version = client.get(url).context["version"]
    replan_budget(
        owner_id=owner.pk,
        scenario_id=scenario.pk,
        expected_version=version,
        travelers=4,
        duration_days=8,
    )
    stale = client.post(url, {"version": version, "travelers": "5", "duration_days": "7"})
    assert stale.status_code == 409
    assert b"another tab" in stale.content
    scenario.refresh_from_db()
    assert (scenario.travelers, scenario.duration_days) == (4, 8)
    assert scenario.plan_revisions.count() == 2


@pytest.mark.django_db
@pytest.mark.parametrize("travelers,days", [("0", "3"), ("21", "2"), ("2", "366"), ("2", "0")])
def test_invalid_planning_inputs_never_mutate(client, budget, travelers, days):
    owner, _other, scenario, _obs, _spend = budget
    client.force_login(owner)
    url = reverse("replan_saved_budget", args=(scenario.pk,))
    version = client.get(url).context["version"]
    res = client.post(url, {"version": version, "travelers": travelers, "duration_days": days})
    assert res.status_code == 422
    scenario.refresh_from_db()
    assert (scenario.travelers, scenario.duration_days) == (2, 6)
    assert scenario.plan_revisions.count() == 0


@pytest.mark.django_db
def test_owner_can_explicitly_clear_duration(budget):
    owner, _other, scenario, _obs, _spend = budget
    assert (
        replan_budget(
            owner_id=owner.pk,
            scenario_id=scenario.pk,
            expected_version=scenario.updated_at.isoformat(),
            travelers=2,
            duration_days=None,
        )
        is True
    )
    scenario.refresh_from_db()
    assert scenario.duration_days is None


@pytest.mark.django_db
def test_cross_account_budget_is_not_readable_or_editable(client, budget):
    _owner, stranger, scenario, _obs, _spend = budget
    client.force_login(stranger)
    url = reverse("replan_saved_budget", args=(scenario.pk,))
    assert client.get(url).status_code == 404
    assert client.post(url, {"travelers": "10", "duration_days": "3"}).status_code == 404


@pytest.mark.django_db
def test_anonymous_cannot_replan_budget(client, budget):
    _owner, _other, scenario, _obs, _spend = budget
    resp = client.get(reverse("replan_saved_budget", args=(scenario.pk,)))
    assert resp.status_code == 302
    assert reverse("login") in resp["Location"]


@pytest.mark.django_db
def test_replan_post_requires_csrf_token(budget):
    owner, _other, scenario, _obs, _spend = budget
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(owner)
    res = csrf_client.post(
        reverse("replan_saved_budget", args=(scenario.pk,)),
        {"travelers": 3, "duration_days": 5, "version": scenario.updated_at.isoformat()},
    )
    assert res.status_code == 403
    scenario.refresh_from_db()
    assert scenario.travelers == 2


@pytest.mark.django_db
def test_shopping_scenario_cannot_be_replanned(client, budget):
    owner, _other, scenario, _obs, _spend = budget
    shopping = SavedScenario.objects.create(
        user=owner,
        kind=SavedScenarioKind.SHOPPING,
        title="Shopping",
        source_currency=scenario.source_currency,
        destination_currency=scenario.destination_currency,
        source_amount=Decimal("20"),
    )
    client.force_login(owner)
    url = reverse("replan_saved_budget", args=(shopping.pk,))
    assert client.get(url).status_code == 404
    assert client.post(url, {"travelers": 4, "duration_days": 4}).status_code == 404


@pytest.mark.django_db
def test_revision_is_immutable_and_20_edit_limit_is_atomic(budget):
    owner, _other, scenario, observation, spend = budget
    for revision in range(1, 21):
        scenario.refresh_from_db()
        replan_budget(
            owner_id=owner.pk,
            scenario_id=scenario.pk,
            expected_version=scenario.updated_at.isoformat(),
            travelers=(revision % 20) + 1,
            duration_days=6 + revision,
        )
    revisions = scenario.plan_revisions.order_by("revision")
    assert revisions.count() == 21
    old = revisions.first()
    assert old is not None
    old.travelers = 7
    with pytest.raises(ValidationError, match="append-only"):
        old.save()
    scenario.refresh_from_db()
    with pytest.raises(ReplanningError, match="maximum planning revisions"):
        replan_budget(
            owner_id=owner.pk,
            scenario_id=scenario.pk,
            expected_version=scenario.updated_at.isoformat(),
            travelers=7,
            duration_days=90,
        )
    scenario.refresh_from_db()
    assert scenario.duration_days == 26
    assert scenario.plan_revisions.count() == 21
    assert SavedScenarioObservation.objects.get(pk=observation.pk).output_amount == Decimal("75000")
    assert SavedScenarioSpendEntry.objects.get(pk=spend.pk).amount == Decimal("350")


@pytest.mark.django_db
def test_category_replan_saves_snapshot_and_preserves_immutable_money(client, budget):
    owner, _other, scenario, observation, spend = budget
    coffee = SavedScenarioBudgetItem.objects.create(
        scenario=scenario, category="coffee", units_per_person_per_day=Decimal("1.00")
    )
    meal = SavedScenarioBudgetItem.objects.create(
        scenario=scenario, category="casual_meal", units_per_person_per_day=Decimal("2.00")
    )
    client.force_login(owner)
    url = reverse("replan_saved_budget", args=(scenario.pk,))
    page = client.get(url)
    assert page.status_code == 200
    assert f"budget_item_{coffee.pk}" in page.context["form"].fields
    res = client.post(
        url,
        {
            "version": page.context["version"],
            "travelers": 3,
            "duration_days": 7,
            f"budget_item_{coffee.pk}": "1.75",
            f"budget_item_{meal.pk}": "2.00",
        },
    )
    assert res.status_code == 302
    scenario.refresh_from_db()
    coffee.refresh_from_db()
    meal.refresh_from_db()
    assert (scenario.travelers, scenario.duration_days) == (3, 7)
    assert coffee.units_per_person_per_day == Decimal("1.75")
    assert meal.units_per_person_per_day == Decimal("2.00")
    revisions = list(scenario.plan_revisions.order_by("revision"))
    assert len(revisions) == 2
    assert revisions[0].category_snapshot == [
        {"category": "casual_meal", "units_per_person_per_day": "2.00"},
        {"category": "coffee", "units_per_person_per_day": "1.00"},
    ]
    assert revisions[1].category_snapshot == [
        {"category": "casual_meal", "units_per_person_per_day": "2.00"},
        {"category": "coffee", "units_per_person_per_day": "1.75"},
    ]
    observation.refresh_from_db()
    spend.refresh_from_db()
    assert observation.output_amount == Decimal("75000")
    assert observation.rate == Decimal("150")
    assert spend.amount == Decimal("350")
    assert scenario.source_amount == Decimal("500")


@pytest.mark.django_db
def test_blank_category_input_keeps_existing_quantities(client, budget):
    owner, _other, scenario, _obs, _spend = budget
    coffee = SavedScenarioBudgetItem.objects.create(
        scenario=scenario, category="coffee", units_per_person_per_day=Decimal("1.00")
    )
    client.force_login(owner)
    url = reverse("replan_saved_budget", args=(scenario.pk,))
    res = client.post(
        url,
        {
            "version": scenario.updated_at.isoformat(),
            "travelers": "3",
            "duration_days": "7",
            f"budget_item_{coffee.pk}": "",
        },
    )
    assert res.status_code == 302
    coffee.refresh_from_db()
    assert coffee.units_per_person_per_day == Decimal("1.00")


@pytest.mark.django_db
@pytest.mark.parametrize("invalid", ["0", "100.01", "-1", "1.001", "NaN"])
def test_category_replan_invalid_quantities_never_write(client, budget, invalid):
    owner, _other, scenario, _obs, _spend = budget
    coffee = SavedScenarioBudgetItem.objects.create(
        scenario=scenario, category="coffee", units_per_person_per_day=Decimal("1.00")
    )
    client.force_login(owner)
    url = reverse("replan_saved_budget", args=(scenario.pk,))
    res = client.post(
        url,
        {
            "version": scenario.updated_at.isoformat(),
            "travelers": "3",
            "duration_days": "7",
            f"budget_item_{coffee.pk}": invalid,
        },
    )
    assert res.status_code == 422
    coffee.refresh_from_db()
    scenario.refresh_from_db()
    assert coffee.units_per_person_per_day == Decimal("1.00")
    assert scenario.travelers == 2
    assert not scenario.plan_revisions.exists()


@pytest.mark.django_db
def test_foreign_budget_item_is_rejected_without_mutation(budget):
    owner, stranger, scenario, _obs, _spend = budget
    foreign = SavedScenarioBudgetItem.objects.create(
        scenario=SavedScenario.objects.create(
            user=stranger,
            kind=SavedScenarioKind.BUDGET,
            source_currency=scenario.source_currency,
            destination_currency=scenario.destination_currency,
            destination_country=scenario.destination_country,
            source_amount=Decimal("200"),
        ),
        category="coffee",
        units_per_person_per_day=Decimal("1"),
    )
    with pytest.raises(ReplanningError, match="no longer part"):
        replan_budget(
            owner_id=owner.pk,
            scenario_id=scenario.pk,
            expected_version=scenario.updated_at.isoformat(),
            travelers=3,
            duration_days=7,
            budget_item_changes={foreign.pk: Decimal("2")},
        )
    scenario.refresh_from_db()
    assert scenario.travelers == 2
    assert not scenario.plan_revisions.exists()


@pytest.mark.django_db
def test_category_change_only_updates_timestamp_and_revision(budget):
    owner, _other, scenario, _obs, _spend = budget
    coffee = SavedScenarioBudgetItem.objects.create(
        scenario=scenario, category="coffee", units_per_person_per_day=Decimal("1")
    )
    original_version = scenario.updated_at.isoformat()
    assert (
        replan_budget(
            owner_id=owner.pk,
            scenario_id=scenario.pk,
            expected_version=original_version,
            travelers=2,
            duration_days=6,
            budget_item_changes={coffee.pk: Decimal("2")},
        )
        is True
    )
    scenario.refresh_from_db()
    coffee.refresh_from_db()
    assert scenario.updated_at.isoformat() != original_version
    assert coffee.units_per_person_per_day == Decimal("2")
    assert scenario.plan_revisions.count() == 2


@pytest.mark.django_db
def test_existing_pre_category_revision_is_not_reconstructed(budget):
    owner, _other, scenario, _obs, _spend = budget
    from apps.travel.models import SavedScenarioPlanRevision

    SavedScenarioPlanRevision.objects.create(
        scenario=scenario, revision=0, travelers=2, duration_days=6
    )
    coffee = SavedScenarioBudgetItem.objects.create(
        scenario=scenario, category="coffee", units_per_person_per_day=Decimal("1")
    )
    assert replan_budget(
        owner_id=owner.pk,
        scenario_id=scenario.pk,
        expected_version=scenario.updated_at.isoformat(),
        travelers=2,
        duration_days=6,
        budget_item_changes={coffee.pk: Decimal("2")},
    )
    revisions = list(scenario.plan_revisions.order_by("revision"))
    assert revisions[0].category_snapshot is None
    assert revisions[1].category_snapshot == [
        {"category": "coffee", "units_per_person_per_day": "2.00"}
    ]
