"""Saved budget trips expose real, owner-scoped task navigation without side effects."""

import pytest
from django.urls import reverse

from apps.travel.tests.test_trip_budget_web import trip_budget_scenario as trip_budget_scenario


@pytest.fixture(autouse=True)
def use_vite_dev_mode(settings):
    settings.VITE_DEV_SERVER_ENABLED = True


@pytest.mark.django_db
def test_trip_workspace_index_navigates_real_sections_without_mutation(
    client, trip_budget_scenario
):
    owner, scenario = trip_budget_scenario
    client.force_login(owner)

    response = client.get(reverse("saved_scenario_detail", args=(scenario.pk,)))

    assert response.status_code == 200
    body = response.content.decode()
    assert "data-trip-command-index" in body
    assert 'aria-label="Saved trip actions"' in body
    for action, target in (
        ("spend", "scenario-trip-budget-title"),
        ("rate", "scenario-observation-title"),
        ("guide", "scenario-local-context-title"),
        ("offline", "offline-trip-tools"),
    ):
        assert f'data-trip-command-action="{action}"' in body
        assert f'href="#{target}"' in body
        assert f'id="{target}"' in body
    assert scenario.spend_entries.count() == 0
    assert scenario.observations.count() == 1


@pytest.mark.django_db
def test_trip_workspace_index_is_owner_scoped(client, trip_budget_scenario):
    _owner, scenario = trip_budget_scenario
    response = client.get(reverse("saved_scenario_detail", args=(scenario.pk,)))

    assert response.status_code == 302
    assert b"data-trip-command-index" not in response.content


@pytest.mark.django_db
def test_active_trip_detail_exposes_owner_scoped_mobile_shortcuts(
    client, trip_budget_scenario, settings, monkeypatch
):
    from datetime import date

    owner, scenario = trip_budget_scenario
    scenario.travel_start_date = date(2026, 9, 30)
    scenario.travel_end_date = date(2026, 10, 5)
    scenario.save(update_fields=["travel_start_date", "travel_end_date"])
    settings.AI_CAMERA_EXTRACTION_ENABLED = True
    monkeypatch.setattr("apps.travel.scenario_web.timezone.localdate", lambda: date(2026, 10, 1))
    client.force_login(owner)

    response = client.get(reverse("saved_scenario_detail", args=(scenario.pk,)))

    assert response.status_code == 200
    html = response.content.decode()
    assert html.count("data-mobile-trip-actions") == 1
    for action in ("convert", "scan", "budget", "trip"):
        assert f'data-trip-quick-action="{action}"' in html
    assert 'href="#trip-money-pass-title"' in html
    assert 'href="#saved-scenario-title"' in html
    assert scenario.spend_entries.count() == 0
    assert scenario.observations.count() == 1
