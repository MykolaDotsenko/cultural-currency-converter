from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from apps.countries.models import Country, Currency
from apps.travel.models import SavedScenario, SavedScenarioKind, SavedScenarioObservation
from apps.travel.scenario_comparison import (
    ScenarioRateDirection,
    compare_scenario_observations,
)

User = get_user_model()


@pytest.fixture
def scenario(db):
    user = User.objects.create_user(username="owner", password="StrongPass-482!")
    eur = Currency.objects.create(code="EUR", name="Euro", minor_units=2)
    jpy = Currency.objects.create(code="JPY", name="Japanese yen", minor_units=0)
    jp = Country.objects.create(iso2="JP", iso3="JPN", name="Japan")
    return SavedScenario.objects.create(
        user=user,
        kind=SavedScenarioKind.BUDGET,
        title="Tokyo budget",
        source_currency=eur,
        destination_currency=jpy,
        destination_country=jp,
        source_amount=Decimal("600"),
    )


def _observation(
    scenario,
    *,
    output: str,
    rate: str,
    kind: str,
) -> SavedScenarioObservation:
    return SavedScenarioObservation.objects.create(
        scenario=scenario,
        kind=kind,
        input_amount=Decimal("600"),
        output_amount=Decimal(output),
        rate=Decimal(rate),
        effective_date=date(2026, 9, 30),
        fetched_at=datetime(2026, 9, 30, 18, tzinfo=UTC),
        provider_keys=["ecb"],
        stale=False,
    )


@pytest.mark.django_db
def test_comparison_reports_neutral_positive_reference_change(scenario):
    initial = _observation(scenario, output="104700", rate="174.50", kind="initial")
    latest = _observation(scenario, output="108000", rate="180", kind="recheck")

    comparison = compare_scenario_observations(initial, latest)

    assert comparison.output_amount_difference == Decimal("3300.000000000000")
    assert comparison.rate_difference == Decimal("5.500000000000000000")
    assert comparison.rate_difference_percent == Decimal("3.2")
    assert comparison.direction is ScenarioRateDirection.HIGHER
    assert comparison.changed is True


@pytest.mark.django_db
def test_comparison_reports_lower_and_unchanged_without_value_judgement(scenario):
    initial = _observation(scenario, output="104700", rate="174.50", kind="initial")
    lower = _observation(scenario, output="102000", rate="170", kind="recheck")

    lower_comparison = compare_scenario_observations(initial, lower)

    assert lower_comparison.output_amount_difference == Decimal("-2700.000000000000")
    assert lower_comparison.rate_difference_percent == Decimal("-2.6")
    assert lower_comparison.direction is ScenarioRateDirection.LOWER

    same = compare_scenario_observations(initial, initial)
    assert same.output_amount_difference == Decimal("0E-12")
    assert same.rate_difference_percent == Decimal("0.0")
    assert same.direction is ScenarioRateDirection.UNCHANGED
    assert same.changed is False


@pytest.mark.django_db
def test_comparison_rejects_observations_from_different_scenarios(scenario):
    other = SavedScenario.objects.create(
        user=scenario.user,
        kind=SavedScenarioKind.BUDGET,
        title="Other",
        source_currency=scenario.source_currency,
        destination_currency=scenario.destination_currency,
        destination_country=scenario.destination_country,
        source_amount=Decimal("600"),
    )
    initial = _observation(scenario, output="104700", rate="174.50", kind="initial")
    latest = _observation(other, output="108000", rate="180", kind="recheck")

    with pytest.raises(ValueError, match="same saved scenario"):
        compare_scenario_observations(initial, latest)
