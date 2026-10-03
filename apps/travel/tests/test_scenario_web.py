from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import Mock, patch

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.countries.models import City, Country, CountryCurrency, Currency
from apps.culture.services import DestinationContext
from apps.exchange.budget_snapshot import build_budget_context_snapshot_token
from apps.exchange.domain import DEFAULT_SOURCE_POLICY, ConversionResult, RateQuote
from apps.exchange.money_context import MoneyContext, MoneyContextState
from apps.exchange.payment_budget_snapshot import build_payment_budget_handoff_token
from apps.exchange.payment_estimate import estimate_payment_value
from apps.exchange.providers.base import FxProviderUnavailable
from apps.travel.models import SavedScenario, SavedScenarioBudgetBasis, SavedScenarioKind

User = get_user_model()


@pytest.fixture(autouse=True)
def use_vite_dev_mode(settings):
    settings.VITE_DEV_SERVER_ENABLED = True


@pytest.fixture
def scenario_reference_data(db):
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
    return eur, jpy, fi, jp, tokyo


def _conversion() -> ConversionResult:
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


class FakeLatestGateway:
    def __init__(
        self,
        *,
        rate: Decimal = Decimal("180"),
        effective_date: date = date(2026, 10, 1),
    ) -> None:
        self.rate = rate
        self.effective_date = effective_date
        self.calls = 0

    def get(self, base, quote, policy, *, now):
        self.calls += 1
        return (
            RateQuote(
                base_currency=base,
                quote_currency=quote,
                rate=self.rate,
                requested_date=None,
                effective_date=self.effective_date,
                fetched_at=datetime(2026, 10, 1, 8, tzinfo=UTC),
                provider_policy=policy,
                provider_keys=("ecb",),
                historical=False,
            ),
            False,
        )


class UnavailableLatestGateway:
    def get(self, base, quote, policy, *, now):
        raise FxProviderUnavailable("provider unavailable")


def _payment_budget_token(*, budget_context_token: str) -> str:
    conversion = _conversion()
    estimate = estimate_payment_value(
        source_budget=conversion.input_amount,
        reference_destination_amount=conversion.output_amount,
        rate=conversion.quote.rate,
        fx_markup_percent=Decimal("2"),
        source_fixed_fee=Decimal("5"),
        destination_fixed_fee=Decimal("500"),
        destination_minor_units=0,
    )
    return build_payment_budget_handoff_token(
        budget_context_token=budget_context_token,
        estimate=estimate,
    )


def _budget_token() -> str:
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
            conversion=_conversion(),
            destination_country_code="JP",
            destination_city_slug="tokyo",
            as_of=date(2026, 9, 30),
            destination_context=destination,
            destination_state=MoneyContextState.EMPTY,
        )
    )


@pytest.mark.django_db
def test_signed_in_user_can_save_budget_without_second_live_price_lookup(
    client,
    scenario_reference_data,
):
    _eur, _jpy, _fi, _jp, tokyo = scenario_reference_data
    user = User.objects.create_user(username="owner", password="StrongPass-482!")
    client.force_login(user)

    response = client.post(
        reverse("save_budget_scenario"),
        {
            "budget_context_token": _budget_token(),
            "title": "Tokyo food and transit",
            "duration_days": "5",
            "travelers": "2",
            "travel_start_date": "2027-04-12",
            "travel_end_date": "2027-04-18",
            "units_coffee": "1",
            "units_casual_meal": "2",
            "units_transit": "2",
        },
    )

    scenario = SavedScenario.objects.get(user=user)
    assert response.status_code == 302
    assert response.url == reverse("saved_scenario_detail", args=(scenario.pk,))
    assert scenario.kind == SavedScenarioKind.BUDGET
    assert scenario.title == "Tokyo food and transit"
    assert scenario.destination_city == tokyo
    assert scenario.destination_country.iso2 == "JP"
    assert scenario.source_country is None
    assert scenario.source_amount == Decimal("600.000000000000")
    assert scenario.duration_days == 5
    assert scenario.travelers == 2
    assert scenario.travel_start_date == date(2027, 4, 12)
    assert scenario.travel_end_date == date(2027, 4, 18)
    assert list(scenario.budget_items.values_list("category", "units_per_person_per_day")) == [
        ("casual_meal", Decimal("2.00")),
        ("coffee", Decimal("1.00")),
        ("transit", Decimal("2.00")),
    ]
    observation = scenario.observations.get()
    assert observation.output_amount == Decimal("104700.000000000000")
    assert observation.effective_date == date(2026, 9, 30)
    assert observation.provider_keys == ["ecb"]


@pytest.mark.django_db
def test_payment_adjusted_budget_can_be_saved_and_reopens_with_adjusted_baseline(
    client,
    scenario_reference_data,
):
    _eur, _jpy, _fi, _jp, _tokyo = scenario_reference_data
    user = User.objects.create_user(username="payment-save-owner", password="StrongPass-482!")
    client.force_login(user)

    budget_context_token = _budget_token()
    response = client.post(
        reverse("save_budget_scenario"),
        {
            "budget_context_token": budget_context_token,
            "payment_budget_token": _payment_budget_token(
                budget_context_token=budget_context_token
            ),
            "title": "Tokyo payment budget",
            "duration_days": "5",
            "travelers": "1",
            "units_coffee": "1",
        },
    )

    scenario = SavedScenario.objects.get(user=user)
    assert response.status_code == 302
    assert response.url == reverse("saved_scenario_detail", args=(scenario.pk,))
    assert scenario.budget_basis == SavedScenarioBudgetBasis.PAYMENT_ESTIMATE
    assert scenario.planning_destination_amount == Decimal("101292.000000000000")
    assert scenario.fx_markup_percent == Decimal("2.00")
    assert scenario.source_fixed_fee == Decimal("5.000000000000")
    assert scenario.destination_fixed_fee == Decimal("500.000000000000")
    assert scenario.observations.get().output_amount == Decimal("104700.000000000000")

    detail = client.get(reverse("saved_scenario_detail", args=(scenario.pk,)))
    assert detail.status_code == 200
    assert b"Payment-adjusted trip budget" not in detail.content
    assert b"payment-adjusted amount you explicitly saved" in detail.content
    assert b"101292 JPY remaining" in detail.content
    assert b"Saved payment assumptions" in detail.content
    assert b"104700" in detail.content

    offline = client.get(reverse("download_offline_destination_pack", args=(scenario.pk,)))
    assert offline.status_code == 200
    offline_text = " ".join(offline.content.decode("utf-8").split())
    assert "Payment-adjusted Trip Budget Remaining" in offline_text
    assert "Saved planning basis 101292 JPY" in offline_text
    assert "stored FX reference remains separate" in offline_text


@pytest.mark.django_db
def test_blank_title_gets_destination_aware_default(client, scenario_reference_data):
    user = User.objects.create_user(username="owner", password="StrongPass-482!")
    client.force_login(user)

    response = client.post(
        reverse("save_budget_scenario"),
        {
            "budget_context_token": _budget_token(),
            "title": "   ",
            "duration_days": "3",
            "travelers": "1",
            "units_coffee": "1",
        },
    )

    assert response.status_code == 302
    assert SavedScenario.objects.get(user=user).title == "Tokyo budget"


@pytest.mark.django_db
def test_budget_save_requires_authentication(client, scenario_reference_data):

    response = client.post(
        reverse("save_budget_scenario"),
        {
            "budget_context_token": _budget_token(),
            "duration_days": "3",
            "travelers": "1",
            "units_coffee": "1",
        },
    )

    assert response.status_code == 302
    assert reverse("login") in response.url
    assert SavedScenario.objects.count() == 0


@pytest.mark.django_db
def test_tampered_budget_snapshot_is_rejected(client, scenario_reference_data):
    user = User.objects.create_user(username="owner", password="StrongPass-482!")
    client.force_login(user)
    token = _budget_token()

    response = client.post(
        reverse("save_budget_scenario"),
        {
            "budget_context_token": f"{token}tampered",
            "duration_days": "3",
            "travelers": "1",
            "units_coffee": "1",
        },
    )

    assert response.status_code == 302
    assert response.url == reverse("converter")
    assert SavedScenario.objects.count() == 0


@pytest.mark.django_db
def test_invalid_budget_assumptions_are_not_saved(client, scenario_reference_data):
    user = User.objects.create_user(username="owner", password="StrongPass-482!")
    client.force_login(user)

    response = client.post(
        reverse("save_budget_scenario"),
        {
            "budget_context_token": _budget_token(),
            "duration_days": "0",
            "travelers": "1",
            "units_coffee": "1",
        },
    )

    assert response.status_code == 302
    assert response.url == reverse("converter")
    assert SavedScenario.objects.count() == 0


@pytest.mark.django_db
def test_invalid_trip_date_order_is_not_saved(client, scenario_reference_data):
    user = User.objects.create_user(username="date-owner", password="StrongPass-482!")
    client.force_login(user)

    response = client.post(
        reverse("save_budget_scenario"),
        {
            "budget_context_token": _budget_token(),
            "duration_days": "3",
            "travelers": "1",
            "travel_start_date": "2027-04-12",
            "travel_end_date": "2027-04-11",
            "units_coffee": "1",
        },
        follow=True,
    )

    assert response.status_code == 200
    assert SavedScenario.objects.filter(user=user).count() == 0
    assert b"Trip end date cannot be before the start date." in response.content


@pytest.mark.django_db
def test_trip_end_date_requires_start_date(client, scenario_reference_data):
    user = User.objects.create_user(username="date-owner-2", password="StrongPass-482!")
    client.force_login(user)

    response = client.post(
        reverse("save_budget_scenario"),
        {
            "budget_context_token": _budget_token(),
            "duration_days": "3",
            "travelers": "1",
            "travel_end_date": "2027-04-18",
            "units_coffee": "1",
        },
        follow=True,
    )

    assert response.status_code == 200
    assert SavedScenario.objects.filter(user=user).count() == 0
    assert b"Add a trip start date before setting an end date." in response.content


@pytest.mark.django_db
def test_saved_scenario_detail_is_owner_scoped(client, scenario_reference_data):
    eur, jpy, _fi, jp, tokyo = scenario_reference_data
    owner = User.objects.create_user(username="owner", password="StrongPass-482!")
    other = User.objects.create_user(username="other", password="StrongPass-482!")
    scenario = SavedScenario.objects.create(
        user=owner,
        kind=SavedScenarioKind.BUDGET,
        title="Tokyo budget",
        source_currency=eur,
        destination_currency=jpy,
        destination_country=jp,
        destination_city=tokyo,
        source_amount=Decimal("600"),
        duration_days=5,
        travelers=2,
    )

    client.force_login(other)
    response = client.get(reverse("saved_scenario_detail", args=(scenario.pk,)))

    assert response.status_code == 404


@pytest.mark.django_db
def test_saved_scenario_detail_renders_explicit_budget_and_converter_return(
    client,
    scenario_reference_data,
):
    user = User.objects.create_user(username="owner", password="StrongPass-482!")
    client.force_login(user)
    client.post(
        reverse("save_budget_scenario"),
        {
            "budget_context_token": _budget_token(),
            "title": "Tokyo spring budget",
            "duration_days": "5",
            "travelers": "2",
            "units_casual_meal": "2",
        },
    )
    scenario = SavedScenario.objects.get(user=user)

    response = client.get(reverse("saved_scenario_detail", args=(scenario.pk,)))

    assert response.status_code == 200
    assert "no-store" in response.headers["Cache-Control"]
    assert "max-age=0" in response.headers["Cache-Control"]
    assert b'<meta name="robots" content="noindex">' in response.content
    assert b"Tokyo spring budget" in response.content
    assert b"Casual Meal" in response.content
    assert b"2 per person / day" in response.content
    assert b"104700" in response.content
    assert b"effective 30 Sep 2026" in response.content
    assert b"Re-run conversion" in response.content
    assert b"amount=600" in response.content
    assert b"source_currency=EUR" in response.content
    assert b"destination_currency=JPY" in response.content
    assert b"destination_city_slug=tokyo" in response.content


@pytest.mark.django_db
def test_saved_state_lists_only_current_users_scenarios(client, scenario_reference_data):
    eur, jpy, _fi, jp, tokyo = scenario_reference_data
    owner = User.objects.create_user(username="owner", password="StrongPass-482!")
    other = User.objects.create_user(username="other", password="StrongPass-482!")
    SavedScenario.objects.create(
        user=owner,
        kind=SavedScenarioKind.BUDGET,
        title="Owner Tokyo plan",
        source_currency=eur,
        destination_currency=jpy,
        destination_country=jp,
        destination_city=tokyo,
        source_amount=Decimal("600"),
    )
    SavedScenario.objects.create(
        user=other,
        kind=SavedScenarioKind.BUDGET,
        title="Other private plan",
        source_currency=eur,
        destination_currency=jpy,
        destination_country=jp,
        destination_city=tokyo,
        source_amount=Decimal("800"),
    )

    client.force_login(owner)
    response = client.get(reverse("saved_state"))

    assert response.status_code == 200
    assert "no-store" in response.headers["Cache-Control"]
    assert "max-age=0" in response.headers["Cache-Control"]
    assert b'<meta name="robots" content="noindex">' in response.content
    assert b"Owner Tokyo plan" in response.content
    assert b"Other private plan" not in response.content
    assert (
        b'aria-label="Compare destination from saved scenario: Owner Tokyo plan"'
        in response.content
    )
    assert b'href="/compare/?left_destination=JP%3Atokyo"' in response.content


@pytest.mark.django_db
def test_delete_saved_scenario_is_owner_scoped(client, scenario_reference_data):
    eur, jpy, _fi, jp, tokyo = scenario_reference_data
    owner = User.objects.create_user(username="owner", password="StrongPass-482!")
    other = User.objects.create_user(username="other", password="StrongPass-482!")
    scenario = SavedScenario.objects.create(
        user=owner,
        kind=SavedScenarioKind.BUDGET,
        title="Tokyo budget",
        source_currency=eur,
        destination_currency=jpy,
        destination_country=jp,
        destination_city=tokyo,
        source_amount=Decimal("600"),
    )

    client.force_login(other)
    denied = client.post(reverse("delete_saved_scenario", args=(scenario.pk,)))
    assert denied.status_code == 404
    assert SavedScenario.objects.filter(pk=scenario.pk).exists()

    client.force_login(owner)
    deleted = client.post(reverse("delete_saved_scenario", args=(scenario.pk,)))
    assert deleted.status_code == 302
    assert deleted.url == reverse("saved_state")
    assert not SavedScenario.objects.filter(pk=scenario.pk).exists()


@pytest.mark.django_db
def test_owner_can_recheck_scenario_without_overwriting_initial_observation(
    client,
    scenario_reference_data,
):
    user = User.objects.create_user(username="recheck-owner", password="StrongPass-482!")
    client.force_login(user)
    client.post(
        reverse("save_budget_scenario"),
        {
            "budget_context_token": _budget_token(),
            "title": "Tokyo re-check",
            "duration_days": "5",
            "travelers": "2",
            "units_casual_meal": "2",
        },
    )
    scenario = SavedScenario.objects.get(user=user)
    initial = scenario.observations.get()
    gateway = FakeLatestGateway()

    with patch(
        "apps.travel.scenario_web.build_latest_quote_gateway",
        return_value=gateway,
    ):
        response = client.post(reverse("recheck_saved_scenario", args=(scenario.pk,)))

    assert response.status_code == 302
    assert response.url == reverse("saved_scenario_detail", args=(scenario.pk,))
    assert gateway.calls == 1
    observations = list(scenario.observations.order_by("recorded_at", "id"))
    assert len(observations) == 2
    assert observations[0].pk == initial.pk
    assert observations[0].output_amount == Decimal("104700.000000000000")
    assert observations[1].output_amount == Decimal("108000.000000000000")
    assert observations[1].rate == Decimal("180.000000000000000000")

    detail = client.get(reverse("saved_scenario_detail", args=(scenario.pk,)))
    assert detail.status_code == 200
    assert b"3300 JPY more" in detail.content
    assert b"Reference-rate difference +3.2%" in detail.content
    assert b"104700 JPY" in detail.content
    assert b"108000 JPY" in detail.content
    assert b"Reference-rate history" in detail.content
    assert b"2 stored observations" in detail.content
    assert b"fetched" in detail.content
    assert b"Initial saved reference" in detail.content
    assert b"Re-check" in detail.content
    assert b"Travel money mode" in detail.content
    assert b"What the offline money pack contains" in detail.content
    assert b"Save offline copy" in detail.content
    assert b"never silently refreshes offline" in detail.content
    detail_text = " ".join(detail.content.decode("utf-8").split())
    assert "does not recommend when to exchange money" in detail_text


@pytest.mark.django_db
def test_recheck_deduplicates_same_provider_observation(
    client,
    scenario_reference_data,
):
    user = User.objects.create_user(username="dedupe-owner", password="StrongPass-482!")
    client.force_login(user)
    client.post(
        reverse("save_budget_scenario"),
        {
            "budget_context_token": _budget_token(),
            "duration_days": "3",
            "travelers": "1",
            "units_coffee": "1",
        },
    )
    scenario = SavedScenario.objects.get(user=user)
    gateway = FakeLatestGateway(
        rate=Decimal("174.50"),
        effective_date=date(2026, 9, 30),
    )

    with patch(
        "apps.travel.scenario_web.build_latest_quote_gateway",
        return_value=gateway,
    ):
        response = client.post(
            reverse("recheck_saved_scenario", args=(scenario.pk,)),
            follow=True,
        )

    assert response.status_code == 200
    assert scenario.observations.count() == 1
    assert b"matches the most recent stored observation" in response.content
    assert b"No later distinct reference observation is stored yet" in response.content


@pytest.mark.django_db
def test_recheck_provider_failure_preserves_saved_observations(
    client,
    scenario_reference_data,
):
    user = User.objects.create_user(username="failure-owner", password="StrongPass-482!")
    client.force_login(user)
    client.post(
        reverse("save_budget_scenario"),
        {
            "budget_context_token": _budget_token(),
            "duration_days": "3",
            "travelers": "1",
            "units_coffee": "1",
        },
    )
    scenario = SavedScenario.objects.get(user=user)

    with patch(
        "apps.travel.scenario_web.build_latest_quote_gateway",
        return_value=UnavailableLatestGateway(),
    ):
        response = client.post(
            reverse("recheck_saved_scenario", args=(scenario.pk,)),
            follow=True,
        )

    assert response.status_code == 200
    assert scenario.observations.count() == 1
    assert b"temporarily unavailable" in response.content
    assert b"saved observation was not changed" in response.content


@pytest.mark.django_db
def test_recheck_is_owner_scoped_before_provider_access(client, scenario_reference_data):
    eur, jpy, _fi, jp, tokyo = scenario_reference_data
    owner = User.objects.create_user(username="recheck-owner-a", password="StrongPass-482!")
    other = User.objects.create_user(username="recheck-owner-b", password="StrongPass-482!")
    scenario = SavedScenario.objects.create(
        user=owner,
        kind=SavedScenarioKind.BUDGET,
        title="Private Tokyo budget",
        source_currency=eur,
        destination_currency=jpy,
        destination_country=jp,
        destination_city=tokyo,
        source_amount=Decimal("600"),
    )
    gateway_factory = Mock()
    client.force_login(other)

    with patch(
        "apps.travel.scenario_web.build_latest_quote_gateway",
        gateway_factory,
    ):
        response = client.post(reverse("recheck_saved_scenario", args=(scenario.pk,)))

    assert response.status_code == 404
    gateway_factory.assert_not_called()


@pytest.mark.django_db
def test_saved_scenario_detail_shows_upcoming_trip_readiness(
    client,
    scenario_reference_data,
):
    user = User.objects.create_user(username="timing-owner", password="StrongPass-482!")
    client.force_login(user)
    client.post(
        reverse("save_budget_scenario"),
        {
            "budget_context_token": _budget_token(),
            "title": "Tokyo departure",
            "duration_days": "5",
            "travelers": "1",
            "travel_start_date": "2026-10-08",
            "travel_end_date": "2026-10-12",
            "units_coffee": "1",
        },
    )
    scenario = SavedScenario.objects.get(user=user)

    with patch("apps.travel.scenario_web.timezone.localdate", return_value=date(2026, 10, 1)):
        response = client.get(reverse("saved_scenario_detail", args=(scenario.pk,)))

    assert response.status_code == 200
    assert b"Trip timing" in response.content
    assert b"Starts in 7 days" in response.content
    assert b"12 Oct 2026" in response.content
    assert b"7 days until start" in response.content
    assert b"Departure is close" in response.content


@pytest.mark.django_db
def test_unscheduled_scenario_does_not_invent_trip_timing(
    client,
    scenario_reference_data,
):
    eur, jpy, _fi, jp, tokyo = scenario_reference_data
    user = User.objects.create_user(username="unscheduled-owner", password="StrongPass-482!")
    scenario = SavedScenario.objects.create(
        user=user,
        kind=SavedScenarioKind.BUDGET,
        title="Unscheduled Tokyo",
        source_currency=eur,
        destination_currency=jpy,
        destination_country=jp,
        destination_city=tokyo,
        source_amount=Decimal("600"),
    )
    client.force_login(user)

    response = client.get(reverse("saved_scenario_detail", args=(scenario.pk,)))

    assert response.status_code == 200
    assert b'id="scenario-readiness-title"' not in response.content
