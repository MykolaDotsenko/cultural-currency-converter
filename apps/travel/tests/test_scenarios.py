from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from apps.countries.models import City, Country, CountryCurrency, Currency
from apps.exchange.budget import BudgetCategoryAssumption
from apps.exchange.domain import DEFAULT_SOURCE_POLICY, ConversionResult, RateQuote
from apps.travel.models import (
    SavedScenario,
    SavedScenarioBudgetItem,
    SavedScenarioKind,
    SavedScenarioObservation,
    SavedScenarioObservationKind,
    SavedScenarioSpendEntry,
    SavedScenarioSpendSource,
)
from apps.travel.scenarios import (
    SavedScenarioError,
    SavedScenarioSpec,
    create_saved_scenario,
    record_scenario_recheck,
    record_scenario_spend,
)

User = get_user_model()


@pytest.fixture
def reference_data(db):
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
    helsinki = City.objects.create(country=fi, slug="helsinki", name="Helsinki")
    return eur, jpy, fi, jp, tokyo, helsinki


def _conversion(
    *,
    amount: Decimal = Decimal("100.00"),
    output: Decimal = Decimal("17450"),
    rate: Decimal = Decimal("174.50"),
    base: str = "EUR",
    quote: str = "JPY",
    historical: bool = False,
) -> ConversionResult:
    requested_date = date(2020, 1, 2) if historical else None
    return ConversionResult(
        input_amount=amount,
        output_amount=output,
        quote=RateQuote(
            base_currency=base,
            quote_currency=quote,
            rate=rate,
            requested_date=requested_date,
            effective_date=requested_date or date(2026, 9, 30),
            fetched_at=datetime(2026, 9, 30, 18, tzinfo=UTC),
            provider_policy=DEFAULT_SOURCE_POLICY,
            provider_keys=("ecb",),
            historical=historical,
        ),
        stale=False,
    )


@pytest.mark.django_db
def test_create_saved_trip_persists_normalized_assumptions_and_initial_observation(reference_data):
    eur, jpy, fi, jp, tokyo, _ = reference_data
    user = User.objects.create_user(username="owner", password="StrongPass-482!")
    spec = SavedScenarioSpec(
        kind=SavedScenarioKind.TRIP,
        title="Tokyo spring trip",
        source_currency=eur,
        destination_currency=jpy,
        source_country=fi,
        destination_country=jp,
        destination_city=tokyo,
        source_amount=Decimal("100.00"),
        duration_days=5,
        travelers=2,
        travel_start_date=date(2027, 4, 12),
        travel_end_date=date(2027, 4, 18),
        budget_categories=(
            BudgetCategoryAssumption("coffee", Decimal("1")),
            BudgetCategoryAssumption("casual_meal", Decimal("2")),
        ),
    )

    scenario = create_saved_scenario(user, spec=spec, conversion=_conversion())

    assert scenario.user == user
    assert scenario.kind == SavedScenarioKind.TRIP
    assert scenario.destination_city == tokyo
    assert scenario.duration_days == 5
    assert scenario.travelers == 2
    assert list(scenario.budget_items.values_list("category", "units_per_person_per_day")) == [
        ("casual_meal", Decimal("2.00")),
        ("coffee", Decimal("1.00")),
    ]
    observation = scenario.observations.get()
    assert observation.kind == SavedScenarioObservationKind.INITIAL
    assert observation.input_amount == Decimal("100.000000000000")
    assert observation.output_amount == Decimal("17450.000000000000")
    assert observation.rate == Decimal("174.500000000000000000")
    assert observation.effective_date == date(2026, 9, 30)
    assert observation.provider_keys == ["ecb"]
    assert observation.stale is False


@pytest.mark.django_db
def test_saved_scenario_preserves_multi_provider_attribution_within_shared_bound(reference_data):
    eur, jpy, fi, jp, tokyo, _ = reference_data
    user = User.objects.create_user(username="multi-provider-owner", password="StrongPass-482!")
    provider_keys = tuple(f"source-{index}" for index in range(12))
    conversion = _conversion()
    conversion = ConversionResult(
        input_amount=conversion.input_amount,
        output_amount=conversion.output_amount,
        quote=RateQuote(
            base_currency=conversion.quote.base_currency,
            quote_currency=conversion.quote.quote_currency,
            rate=conversion.quote.rate,
            requested_date=None,
            effective_date=conversion.quote.effective_date,
            fetched_at=conversion.quote.fetched_at,
            provider_policy=conversion.quote.provider_policy,
            provider_keys=provider_keys,
            historical=False,
        ),
        stale=conversion.stale,
    )

    scenario = create_saved_scenario(
        user,
        spec=SavedScenarioSpec(
            kind=SavedScenarioKind.BUDGET,
            source_currency=eur,
            destination_currency=jpy,
            source_country=fi,
            destination_country=jp,
            destination_city=tokyo,
            source_amount=Decimal("100.00"),
        ),
        conversion=conversion,
    )

    assert scenario.observations.get().provider_keys == sorted(provider_keys)


@pytest.mark.django_db
def test_scenario_creation_requires_authenticated_owner(reference_data):
    eur, jpy, fi, jp, tokyo, _ = reference_data

    with pytest.raises(SavedScenarioError, match="Authentication"):
        create_saved_scenario(
            User(),
            spec=SavedScenarioSpec(
                kind=SavedScenarioKind.TRIP,
                source_currency=eur,
                destination_currency=jpy,
                source_country=fi,
                destination_country=jp,
                destination_city=tokyo,
                source_amount=Decimal("100"),
            ),
            conversion=_conversion(),
        )

    assert SavedScenario.objects.count() == 0


@pytest.mark.django_db
def test_scenario_rejects_destination_city_from_another_country(reference_data):
    eur, jpy, fi, jp, _, helsinki = reference_data
    user = User.objects.create_user(username="owner", password="StrongPass-482!")

    with pytest.raises(SavedScenarioError, match="Destination city"):
        create_saved_scenario(
            user,
            spec=SavedScenarioSpec(
                kind=SavedScenarioKind.TRIP,
                source_currency=eur,
                destination_currency=jpy,
                source_country=fi,
                destination_country=jp,
                destination_city=helsinki,
                source_amount=Decimal("100"),
            ),
            conversion=_conversion(),
        )

    assert SavedScenario.objects.count() == 0


@pytest.mark.django_db
def test_scenario_rejects_non_current_country_currency_context(reference_data):
    eur, _jpy, fi, jp, tokyo, _ = reference_data
    user = User.objects.create_user(username="owner", password="StrongPass-482!")

    with pytest.raises(SavedScenarioError, match="current destination currency context"):
        create_saved_scenario(
            user,
            spec=SavedScenarioSpec(
                kind=SavedScenarioKind.TRIP,
                source_currency=eur,
                destination_currency=eur,
                source_country=fi,
                destination_country=jp,
                destination_city=tokyo,
                source_amount=Decimal("100"),
            ),
            conversion=_conversion(output=Decimal("100"), rate=Decimal("1"), quote="EUR"),
        )


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("conversion", "message"),
    [
        (_conversion(historical=True), "current conversion"),
        (_conversion(amount=Decimal("200")), "source amount"),
        (_conversion(base="USD"), "source currency"),
        (_conversion(quote="USD"), "destination currency"),
    ],
)
def test_scenario_requires_conversion_identity_to_match(reference_data, conversion, message):
    eur, jpy, fi, jp, tokyo, _ = reference_data
    user = User.objects.create_user(username=f"owner-{message}", password="StrongPass-482!")
    spec = SavedScenarioSpec(
        kind=SavedScenarioKind.TRIP,
        source_currency=eur,
        destination_currency=jpy,
        source_country=fi,
        destination_country=jp,
        destination_city=tokyo,
        source_amount=Decimal("100"),
    )

    with pytest.raises(SavedScenarioError, match=message):
        create_saved_scenario(user, spec=spec, conversion=conversion)

    assert not SavedScenario.objects.filter(user=user).exists()


@pytest.mark.django_db
def test_invalid_budget_item_rolls_back_scenario_and_observation(reference_data):
    eur, jpy, fi, jp, tokyo, _ = reference_data
    user = User.objects.create_user(username="owner", password="StrongPass-482!")
    spec = SavedScenarioSpec(
        kind=SavedScenarioKind.BUDGET,
        source_currency=eur,
        destination_currency=jpy,
        source_country=fi,
        destination_country=jp,
        destination_city=tokyo,
        source_amount=Decimal("100"),
        budget_categories=(BudgetCategoryAssumption("x" * 25, Decimal("1")),),
    )

    with pytest.raises(SavedScenarioError):
        create_saved_scenario(user, spec=spec, conversion=_conversion())

    assert SavedScenario.objects.count() == 0
    assert SavedScenarioBudgetItem.objects.count() == 0
    assert SavedScenarioObservation.objects.count() == 0


@pytest.mark.django_db
def test_recheck_records_new_immutable_observation(reference_data):
    eur, jpy, fi, jp, tokyo, _ = reference_data
    user = User.objects.create_user(username="owner", password="StrongPass-482!")
    scenario = create_saved_scenario(
        user,
        spec=SavedScenarioSpec(
            kind=SavedScenarioKind.TRIP,
            source_currency=eur,
            destination_currency=jpy,
            source_country=fi,
            destination_country=jp,
            destination_city=tokyo,
            source_amount=Decimal("100"),
        ),
        conversion=_conversion(),
    )

    observation = record_scenario_recheck(
        scenario,
        conversion=_conversion(output=Decimal("18000"), rate=Decimal("180")),
    )

    assert scenario.observations.count() == 2
    assert observation.kind == SavedScenarioObservationKind.RECHECK
    assert observation.output_amount == Decimal("18000.000000000000")

    observation.stale = True
    with pytest.raises(ValidationError, match="immutable"):
        observation.save()


@pytest.mark.django_db
def test_recheck_rejects_mismatched_amount_or_pair(reference_data):
    eur, jpy, fi, jp, tokyo, _ = reference_data
    user = User.objects.create_user(username="owner", password="StrongPass-482!")
    scenario = create_saved_scenario(
        user,
        spec=SavedScenarioSpec(
            kind=SavedScenarioKind.TRIP,
            source_currency=eur,
            destination_currency=jpy,
            source_country=fi,
            destination_country=jp,
            destination_city=tokyo,
            source_amount=Decimal("100"),
        ),
        conversion=_conversion(),
    )

    with pytest.raises(SavedScenarioError, match="amount"):
        record_scenario_recheck(
            scenario,
            conversion=_conversion(amount=Decimal("200"), output=Decimal("34900")),
        )

    with pytest.raises(SavedScenarioError, match="destination currency"):
        record_scenario_recheck(
            scenario,
            conversion=_conversion(output=Decimal("100"), rate=Decimal("1"), quote="USD"),
        )

    assert scenario.observations.count() == 1


@pytest.mark.django_db
def test_trip_and_budget_scenarios_require_destination_country(reference_data):
    eur, jpy, _, _, _, _ = reference_data
    user = User.objects.create_user(username="owner", password="StrongPass-482!")

    with pytest.raises(SavedScenarioError):
        create_saved_scenario(
            user,
            spec=SavedScenarioSpec(
                kind=SavedScenarioKind.BUDGET,
                source_currency=eur,
                destination_currency=jpy,
                source_amount=Decimal("100"),
            ),
            conversion=_conversion(),
        )


@pytest.mark.django_db
def test_duplicate_budget_categories_are_rejected_before_write(reference_data):
    eur, jpy, fi, jp, tokyo, _ = reference_data
    user = User.objects.create_user(username="owner", password="StrongPass-482!")

    with pytest.raises(SavedScenarioError, match="unique"):
        create_saved_scenario(
            user,
            spec=SavedScenarioSpec(
                kind=SavedScenarioKind.BUDGET,
                source_currency=eur,
                destination_currency=jpy,
                source_country=fi,
                destination_country=jp,
                destination_city=tokyo,
                source_amount=Decimal("100"),
                budget_categories=(
                    BudgetCategoryAssumption("coffee", Decimal("1")),
                    BudgetCategoryAssumption("coffee", Decimal("2")),
                ),
            ),
            conversion=_conversion(),
        )

    assert SavedScenario.objects.count() == 0


@pytest.mark.django_db
def test_recheck_reuses_latest_identical_provider_observation(reference_data):
    eur, jpy, fi, jp, tokyo, _ = reference_data
    user = User.objects.create_user(username="dedupe-owner", password="StrongPass-482!")
    scenario = create_saved_scenario(
        user,
        spec=SavedScenarioSpec(
            kind=SavedScenarioKind.TRIP,
            source_currency=eur,
            destination_currency=jpy,
            source_country=fi,
            destination_country=jp,
            destination_city=tokyo,
            source_amount=Decimal("100"),
        ),
        conversion=_conversion(),
    )
    initial = scenario.observations.get()

    result = record_scenario_recheck(scenario, conversion=_conversion())

    assert result.pk == initial.pk
    assert scenario.observations.count() == 1


@pytest.mark.django_db
def test_recheck_observation_limit_is_enforced_without_deleting_history(
    reference_data,
    monkeypatch,
):
    eur, jpy, fi, jp, tokyo, _ = reference_data
    user = User.objects.create_user(username="bounded-owner", password="StrongPass-482!")
    scenario = create_saved_scenario(
        user,
        spec=SavedScenarioSpec(
            kind=SavedScenarioKind.TRIP,
            source_currency=eur,
            destination_currency=jpy,
            source_country=fi,
            destination_country=jp,
            destination_city=tokyo,
            source_amount=Decimal("100"),
        ),
        conversion=_conversion(),
    )
    record_scenario_recheck(
        scenario,
        conversion=_conversion(output=Decimal("18000"), rate=Decimal("180")),
    )
    monkeypatch.setattr("apps.travel.scenarios.MAX_SCENARIO_OBSERVATIONS", 2)

    with pytest.raises(SavedScenarioError, match="at most 2 FX observations"):
        record_scenario_recheck(
            scenario,
            conversion=_conversion(output=Decimal("18100"), rate=Decimal("181")),
        )

    assert scenario.observations.count() == 2
    assert scenario.observations.filter(kind=SavedScenarioObservationKind.INITIAL).count() == 1


@pytest.mark.django_db
def test_scenario_rejects_end_date_without_start_date(reference_data):
    eur, jpy, fi, jp, tokyo, _ = reference_data
    user = User.objects.create_user(username="date-contract-owner", password="StrongPass-482!")

    with pytest.raises(SavedScenarioError, match="start date is required"):
        create_saved_scenario(
            user,
            spec=SavedScenarioSpec(
                kind=SavedScenarioKind.TRIP,
                source_currency=eur,
                destination_currency=jpy,
                source_country=fi,
                destination_country=jp,
                destination_city=tokyo,
                source_amount=Decimal("100"),
                travel_end_date=date(2027, 4, 18),
            ),
            conversion=_conversion(),
        )

    assert not SavedScenario.objects.filter(user=user).exists()


@pytest.mark.django_db(transaction=True)
def test_database_rejects_trip_end_without_start_date(reference_data):
    eur, jpy, _fi, jp, tokyo, _ = reference_data
    user = User.objects.create_user(username="db-date-owner", password="StrongPass-482!")

    with pytest.raises(IntegrityError):
        SavedScenario.objects.create(
            user=user,
            kind=SavedScenarioKind.BUDGET,
            title="Invalid database dates",
            source_currency=eur,
            destination_currency=jpy,
            destination_country=jp,
            destination_city=tokyo,
            source_amount=Decimal("100"),
            travel_end_date=date(2027, 4, 18),
        )


@pytest.mark.django_db
def test_budget_scenario_records_minimal_immutable_confirmed_spend(reference_data):
    eur, jpy, fi, jp, tokyo, _ = reference_data
    user = User.objects.create_user(username="spend-owner", password="StrongPass-482!")
    scenario = create_saved_scenario(
        user,
        spec=SavedScenarioSpec(
            kind=SavedScenarioKind.BUDGET,
            source_currency=eur,
            destination_currency=jpy,
            source_country=fi,
            destination_country=jp,
            destination_city=tokyo,
            source_amount=Decimal("100"),
        ),
        conversion=_conversion(),
    )

    entry = record_scenario_spend(scenario, amount=Decimal("1200"))

    assert scenario.spend_entries.count() == 1
    assert entry.amount == Decimal("1200")
    assert entry.source == SavedScenarioSpendSource.MANUAL

    entry.amount = Decimal("1300")
    with pytest.raises(ValidationError, match="immutable"):
        entry.save()


@pytest.mark.django_db
def test_confirmed_spend_submission_key_is_idempotent(reference_data):
    eur, jpy, fi, jp, tokyo, _ = reference_data
    user = User.objects.create_user(username="spend-idempotent-owner", password="StrongPass-482!")
    scenario = create_saved_scenario(
        user,
        spec=SavedScenarioSpec(
            kind=SavedScenarioKind.BUDGET,
            source_currency=eur,
            destination_currency=jpy,
            source_country=fi,
            destination_country=jp,
            destination_city=tokyo,
            source_amount=Decimal("100"),
        ),
        conversion=_conversion(),
    )
    submission_key = uuid4()

    first = record_scenario_spend(
        scenario,
        amount=Decimal("1200"),
        submission_key=submission_key,
    )
    replay = record_scenario_spend(
        scenario,
        amount=Decimal("1200"),
        submission_key=submission_key,
    )

    assert replay.pk == first.pk
    assert scenario.spend_entries.count() == 1

    with pytest.raises(SavedScenarioError, match="already bound"):
        record_scenario_spend(
            scenario,
            amount=Decimal("1300"),
            submission_key=submission_key,
        )



@pytest.mark.django_db
def test_confirmed_spend_source_is_normalized_and_validated(reference_data):
    eur, jpy, fi, jp, tokyo, _ = reference_data
    user = User.objects.create_user(username="spend-source-owner", password="StrongPass-482!")
    scenario = create_saved_scenario(
        user,
        spec=SavedScenarioSpec(
            kind=SavedScenarioKind.BUDGET,
            source_currency=eur,
            destination_currency=jpy,
            source_country=fi,
            destination_country=jp,
            destination_city=tokyo,
            source_amount=Decimal("100"),
        ),
        conversion=_conversion(),
    )

    camera_entry = record_scenario_spend(
        scenario,
        amount=Decimal("100"),
        source="camera",
    )
    assert camera_entry.source == SavedScenarioSpendSource.CAMERA

    with pytest.raises(SavedScenarioError, match="source is invalid"):
        record_scenario_spend(
            scenario,
            amount=Decimal("100"),
            source="untrusted",
        )


@pytest.mark.django_db
def test_confirmed_spend_rejects_non_budget_scenario_and_invalid_amount(reference_data):
    eur, jpy, fi, jp, tokyo, _ = reference_data
    user = User.objects.create_user(username="spend-contract-owner", password="StrongPass-482!")
    scenario = create_saved_scenario(
        user,
        spec=SavedScenarioSpec(
            kind=SavedScenarioKind.TRIP,
            source_currency=eur,
            destination_currency=jpy,
            source_country=fi,
            destination_country=jp,
            destination_city=tokyo,
            source_amount=Decimal("100"),
        ),
        conversion=_conversion(),
    )

    with pytest.raises(SavedScenarioError, match="saved budget scenario"):
        record_scenario_spend(scenario, amount=Decimal("10"))

    scenario.kind = SavedScenarioKind.BUDGET
    with pytest.raises(SavedScenarioError, match="greater than zero"):
        record_scenario_spend(scenario, amount=Decimal("0"))
    with pytest.raises(SavedScenarioError, match="greater than zero"):
        record_scenario_spend(scenario, amount=Decimal("NaN"))
    with pytest.raises(SavedScenarioError, match="no greater than 1,000,000,000"):
        record_scenario_spend(scenario, amount=Decimal("1000000000.01"))


@pytest.mark.django_db
def test_confirmed_spend_enforces_destination_currency_minor_units(reference_data):
    eur, jpy, fi, jp, tokyo, _ = reference_data
    user = User.objects.create_user(username="spend-precision-owner", password="StrongPass-482!")
    scenario = create_saved_scenario(
        user,
        spec=SavedScenarioSpec(
            kind=SavedScenarioKind.BUDGET,
            source_currency=eur,
            destination_currency=jpy,
            source_country=fi,
            destination_country=jp,
            destination_city=tokyo,
            source_amount=Decimal("100"),
        ),
        conversion=_conversion(),
    )

    with pytest.raises(SavedScenarioError, match="at most 0 decimal places"):
        record_scenario_spend(scenario, amount=Decimal("12.5"))

    assert scenario.spend_entries.count() == 0


@pytest.mark.django_db
def test_confirmed_spend_limit_is_enforced_without_deleting_existing_entries(
    reference_data,
    monkeypatch,
):
    eur, jpy, fi, jp, tokyo, _ = reference_data
    user = User.objects.create_user(username="spend-limit-owner", password="StrongPass-482!")
    scenario = create_saved_scenario(
        user,
        spec=SavedScenarioSpec(
            kind=SavedScenarioKind.BUDGET,
            source_currency=eur,
            destination_currency=jpy,
            source_country=fi,
            destination_country=jp,
            destination_city=tokyo,
            source_amount=Decimal("100"),
        ),
        conversion=_conversion(),
    )
    record_scenario_spend(scenario, amount=Decimal("100"))
    monkeypatch.setattr("apps.travel.scenarios.MAX_SCENARIO_SPEND_ENTRIES", 1)

    with pytest.raises(SavedScenarioError, match="at most 1 spend entries"):
        record_scenario_spend(scenario, amount=Decimal("200"))

    assert list(scenario.spend_entries.values_list("amount", flat=True)) == [
        Decimal("100.000000000000")
    ]


@pytest.mark.django_db(transaction=True)
def test_database_rejects_non_positive_confirmed_spend(reference_data):
    eur, jpy, _fi, jp, tokyo, _ = reference_data
    user = User.objects.create_user(username="spend-db-owner", password="StrongPass-482!")
    scenario = SavedScenario.objects.create(
        user=user,
        kind=SavedScenarioKind.BUDGET,
        title="Database spend constraint",
        source_currency=eur,
        destination_currency=jpy,
        destination_country=jp,
        destination_city=tokyo,
        source_amount=Decimal("100"),
    )

    with pytest.raises(IntegrityError):
        SavedScenarioSpendEntry.objects.create(
            scenario=scenario,
            submission_key=uuid4(),
            amount=Decimal("0"),
        )

    with pytest.raises(IntegrityError):
        SavedScenarioSpendEntry.objects.create(
            scenario=scenario,
            submission_key=uuid4(),
            amount=Decimal("1000000001"),
        )


@pytest.mark.django_db(transaction=True)
def test_database_allows_only_one_initial_observation_per_scenario(reference_data):
    eur, jpy, fi, jp, tokyo, _ = reference_data
    user = User.objects.create_user(username="initial-baseline-owner", password="StrongPass-482!")
    scenario = create_saved_scenario(
        user,
        spec=SavedScenarioSpec(
            kind=SavedScenarioKind.BUDGET,
            source_currency=eur,
            destination_currency=jpy,
            source_country=fi,
            destination_country=jp,
            destination_city=tokyo,
            source_amount=Decimal("100"),
        ),
        conversion=_conversion(),
    )
    initial = scenario.observations.get(kind=SavedScenarioObservationKind.INITIAL)

    with pytest.raises(IntegrityError):
        SavedScenarioObservation.objects.create(
            scenario=scenario,
            kind=SavedScenarioObservationKind.INITIAL,
            input_amount=initial.input_amount,
            output_amount=initial.output_amount,
            rate=initial.rate,
            effective_date=initial.effective_date,
            fetched_at=initial.fetched_at,
            provider_keys=initial.provider_keys,
            stale=initial.stale,
        )
