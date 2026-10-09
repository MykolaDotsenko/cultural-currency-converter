from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import ANY, Mock, patch

import pytest
from django.contrib.auth import get_user_model
from django.db import DatabaseError
from django.urls import reverse

from apps.countries.models import City, Country, CountryCurrency, Currency
from apps.culture.calendar import CalendarContext, PublicHolidayContextItem
from apps.culture.models import PublicHolidayObservation
from apps.culture.services import DestinationContext, PaymentContext
from apps.exchange.budget_snapshot import build_budget_context_snapshot_token
from apps.exchange.domain import DEFAULT_SOURCE_POLICY, ConversionResult, RateQuote
from apps.exchange.money_context import MoneyContext, MoneyContextState
from apps.exchange.payment_budget_snapshot import build_payment_budget_handoff_token
from apps.exchange.payment_estimate import estimate_payment_value
from apps.exchange.providers.base import FxProviderUnavailable
from apps.travel.models import SavedScenario, SavedScenarioBudgetBasis, SavedScenarioKind
from apps.travel.trip_readiness import (
    TripCalendarReview,
    build_trip_calendar_review,
    build_trip_readiness,
)

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
def test_saved_scenario_detail_does_not_refresh_local_context_by_default(
    client,
    scenario_reference_data,
):
    user = User.objects.create_user(username="context-idle-owner", password="StrongPass-482!")
    client.force_login(user)
    client.post(
        reverse("save_budget_scenario"),
        {
            "budget_context_token": _budget_token(),
            "title": "Tokyo context idle",
            "duration_days": "5",
            "travelers": "1",
            "units_coffee": "1",
        },
    )
    scenario = SavedScenario.objects.get(user=user)

    with patch("apps.travel.scenario_web.build_destination_context") as builder:
        response = client.get(reverse("saved_scenario_detail", args=(scenario.pk,)))

    assert response.status_code == 200
    builder.assert_not_called()
    assert b"Refresh local money guide" in response.content
    assert b'data-saved-local-context-state="idle"' in response.content
    assert b"No current local-price lookup runs when this saved page opens." in response.content


@pytest.mark.django_db
def test_saved_scenario_explicit_local_context_refresh_uses_latest_stored_observation(
    client,
    scenario_reference_data,
):
    user = User.objects.create_user(username="context-refresh-owner", password="StrongPass-482!")
    client.force_login(user)
    client.post(
        reverse("save_budget_scenario"),
        {
            "budget_context_token": _budget_token(),
            "title": "Tokyo context refresh",
            "duration_days": "5",
            "travelers": "1",
            "units_coffee": "1",
        },
    )
    scenario = SavedScenario.objects.get(user=user)
    with patch(
        "apps.travel.scenario_web.build_latest_quote_gateway",
        return_value=FakeLatestGateway(),
    ):
        recheck = client.post(reverse("recheck_saved_scenario", args=(scenario.pk,)))
    assert recheck.status_code == 302
    assert scenario.observations.count() == 2

    payment = PaymentContext(
        summary="Cards are widely accepted.",
        payment_customs="Cards are common.",
        cash_usage="Carry some cash for small purchases.",
        tipping="Tipping is not generally expected.",
        atm_notes="Use bank ATMs where practical.",
        dcc_warning="Decline dynamic currency conversion when offered.",
        source_name="Reviewed payments",
        source_url="https://example.test/japan-payments",
        verified_at=datetime(2026, 10, 2, 9, tzinfo=UTC),
    )
    destination = DestinationContext(
        country_code="JP",
        country_name="Japan",
        as_of=date(2026, 10, 4),
        payment=payment,
        prices=(),
        city_slug="tokyo",
        city_name="Tokyo",
    )

    with patch(
        "apps.travel.scenario_web.build_destination_context",
        return_value=destination,
    ) as builder:
        response = client.get(
            reverse("saved_scenario_detail", args=(scenario.pk,)),
            {"local_context": "1"},
        )

    assert response.status_code == 200
    builder.assert_called_once_with(
        country_code="JP",
        converted_amount=Decimal("108000.000000000000"),
        quote_currency="JPY",
        as_of=ANY,
        price_limit=3,
        city_slug="tokyo",
    )
    assert b'data-saved-local-context-state="available"' in response.content
    assert b"108000 JPY" in response.content
    assert b"effective 1 Oct 2026" in response.content
    assert b"104700" in response.content
    assert b"Cards are widely accepted." in response.content
    assert b"Reviewed payments" in response.content
    assert b"does not refresh the FX rate" in response.content


@pytest.mark.django_db
def test_saved_scenario_local_context_refresh_degrades_without_mutating_scenario(
    client,
    scenario_reference_data,
    caplog,
):
    user = User.objects.create_user(username="context-degraded-owner", password="StrongPass-482!")
    client.force_login(user)
    client.post(
        reverse("save_budget_scenario"),
        {
            "budget_context_token": _budget_token(),
            "title": "Tokyo context degraded",
            "duration_days": "5",
            "travelers": "1",
            "units_coffee": "1",
        },
    )
    scenario = SavedScenario.objects.get(user=user)
    observation_ids = list(scenario.observations.values_list("pk", flat=True))

    with (
        patch(
            "apps.travel.scenario_web.build_destination_context",
            side_effect=DatabaseError("context unavailable"),
        ),
        caplog.at_level("WARNING", logger="cultural_currency.travel"),
    ):
        response = client.get(
            reverse("saved_scenario_detail", args=(scenario.pk,)),
            {"local_context": "1"},
        )

    assert response.status_code == 200
    assert b'data-saved-local-context-state="degraded"' in response.content
    assert b"Local money guide is temporarily unavailable." in response.content
    assert list(scenario.observations.values_list("pk", flat=True)) == observation_ids
    assert any(
        record.msg == "saved_scenario_local_context_unavailable" for record in caplog.records
    )


@pytest.mark.django_db
def test_saved_scenario_local_context_refresh_has_explicit_empty_state(
    client,
    scenario_reference_data,
):
    user = User.objects.create_user(username="context-empty-owner", password="StrongPass-482!")
    client.force_login(user)
    client.post(
        reverse("save_budget_scenario"),
        {
            "budget_context_token": _budget_token(),
            "title": "Tokyo context empty",
            "duration_days": "5",
            "travelers": "1",
            "units_coffee": "1",
        },
    )
    scenario = SavedScenario.objects.get(user=user)
    destination = DestinationContext(
        country_code="JP",
        country_name="Japan",
        as_of=date(2026, 10, 4),
        payment=None,
        prices=(),
        city_slug="tokyo",
        city_name="Tokyo",
    )

    with patch(
        "apps.travel.scenario_web.build_destination_context",
        return_value=destination,
    ):
        response = client.get(
            reverse("saved_scenario_detail", args=(scenario.pk,)),
            {"local_context": "1"},
        )

    assert response.status_code == 200
    assert b'data-saved-local-context-state="empty"' in response.content
    assert b"No current reviewed price or payment context is available" in response.content


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
    assert detail.content.count(b"fetched ") >= 2
    assert b"Travel money mode" in detail.content
    assert b"What the offline money pack contains" in detail.content
    assert b"Download portable HTML pack" in detail.content
    assert b"Save trip for offline" in detail.content
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


def _readiness_destination() -> DestinationContext:
    return DestinationContext(
        country_code="JP",
        country_name="Japan",
        as_of=date(2026, 10, 9),
        payment=PaymentContext(
            summary="Reviewed country payment guidance.",
            payment_customs="Cards are accepted.",
            cash_usage="Carry some local cash.",
            tipping="Not usually expected.",
            atm_notes="Check the ATM fee screen.",
            dcc_warning="Choose the local currency, not DCC.",
            source_name="Reviewed bank guide",
            source_url="https://example.test/payment-guide",
            verified_at=datetime(2026, 10, 1, tzinfo=UTC),
        ),
        prices=(),
        calendar=CalendarContext(
            as_of=date(2026, 10, 9),
            today=(),
            upcoming=(
                PublicHolidayContextItem(
                    date=date(2026, 10, 15),
                    name="National holiday within trip",
                    holiday_types=("Public",),
                    source_name="Nager.Date",
                    source_url="https://example.test/national-holiday",
                ),
                PublicHolidayContextItem(
                    date=date(2026, 10, 25),
                    name="Holiday outside trip",
                    holiday_types=("Public",),
                    source_name="Nager.Date",
                    source_url="https://example.test/holiday-outside-trip",
                ),
            ),
            window_days=30,
        ),
    )


def test_readiness_uses_reviewed_data_and_filters_holidays_to_saved_trip_window():
    result = build_trip_readiness(
        _readiness_destination(),
        as_of=date(2026, 10, 9),
        travel_start_date=date(2026, 10, 13),
        travel_end_date=date(2026, 10, 18),
    )

    assert result is not None
    assert [item["name"] for item in result["holidays"]] == ["National holiday within trip"]
    assert result["tips"][0]["text"] == "Choose the local currency, not DCC."
    assert result["payment_source_url"] == "https://example.test/payment-guide"
    assert result["calendar_window_days"] == 30
    assert result["has_trip_dates"] is True


def test_readiness_does_not_invent_holidays_for_unscheduled_or_future_trip():
    destination = _readiness_destination()
    for start, end in (
        (None, None),
        (date(2026, 12, 1), date(2026, 12, 8)),
    ):
        result = build_trip_readiness(
            destination,
            as_of=date(2026, 10, 9),
            travel_start_date=start,
            travel_end_date=end,
        )
        assert result is not None
        assert result["holidays"] == ()
        assert result["tips"]


def test_readiness_does_not_invent_guidance_when_no_reviewed_evidence():
    destination = DestinationContext(
        country_code="JP",
        country_name="Japan",
        as_of=date(2026, 10, 9),
        payment=None,
        prices=(),
        calendar=None,
    )
    assert (
        build_trip_readiness(
            destination,
            as_of=date(2026, 10, 9),
            travel_start_date=date(2026, 10, 13),
            travel_end_date=date(2026, 10, 18),
        )
        is None
    )


@pytest.mark.django_db
def test_trip_readiness_is_opt_in_and_visible_with_provenance(client, scenario_reference_data):
    user = User.objects.create_user(username="readiness-owner", password="StrongPass-482!")
    client.force_login(user)
    japan = Country.objects.get(iso2="JP")
    PublicHolidayObservation.objects.create(
        country=japan,
        date=date(2026, 10, 15),
        name="National holiday within trip",
        national_holiday=True,
        subdivision_codes=[],
        holiday_types=["Public"],
        source_name="Nager.Date",
        source_url="https://example.test/national-holiday",
        source_retrieved_at=datetime(2026, 10, 9, tzinfo=UTC),
        is_published=True,
    )
    client.post(
        reverse("save_budget_scenario"),
        {
            "budget_context_token": _budget_token(),
            "title": "Tokyo readiness",
            "duration_days": "6",
            "travelers": "1",
            "travel_start_date": "2026-10-13",
            "travel_end_date": "2026-10-18",
            "units_coffee": "1",
        },
    )
    scenario = SavedScenario.objects.get(user=user)

    with patch("apps.travel.scenario_web.build_destination_context") as builder:
        idle = client.get(reverse("saved_scenario_detail", args=(scenario.pk,)))
    builder.assert_not_called()
    assert b"data-trip-readiness-evidence" not in idle.content

    with (
        patch("apps.travel.scenario_web.timezone.localdate", return_value=date(2026, 10, 9)),
        patch(
            "apps.travel.scenario_web.build_destination_context",
            return_value=_readiness_destination(),
        ),
    ):
        refreshed = client.get(
            reverse("saved_scenario_detail", args=(scenario.pk,)),
            {"local_context": "1"},
        )
    assert refreshed.status_code == 200
    assert b"data-trip-readiness-evidence" in refreshed.content
    assert b"National holiday within trip" in refreshed.content
    assert b"Holiday outside trip" in refreshed.content
    assert b"National holiday during saved travel dates" in refreshed.content
    assert b"Choose the local currency, not DCC." in refreshed.content
    assert b"Source: Reviewed bank guide" in refreshed.content
    assert b"Absence of a listed holiday does not mean" in refreshed.content
    assert b"does not refresh the FX rate" in refreshed.content


@pytest.mark.django_db
def test_future_saved_trip_uses_reviewed_holidays_from_its_dates_without_provider_calls(
    client, scenario_reference_data
):
    user = User.objects.create_user(username="future-calendar-owner", password="StrongPass-482!")
    client.force_login(user)
    japan = Country.objects.get(iso2="JP")
    PublicHolidayObservation.objects.create(
        country=japan,
        date=date(2026, 12, 6),
        name="Future reviewed national holiday",
        national_holiday=True,
        subdivision_codes=[],
        holiday_types=["Public"],
        source_name="Nager.Date",
        source_url="https://example.test/jp-future-national",
        source_retrieved_at=datetime(2026, 10, 9, tzinfo=UTC),
        is_published=True,
    )
    PublicHolidayObservation.objects.create(
        country=japan,
        date=date(2026, 12, 7),
        name="Unrelated regional-only holiday",
        national_holiday=False,
        subdivision_codes=["JP-01"],
        holiday_types=["Public"],
        source_name="Nager.Date",
        source_url="https://example.test/jp-regional",
        source_retrieved_at=datetime(2026, 10, 9, tzinfo=UTC),
        is_published=True,
    )
    client.post(
        reverse("save_budget_scenario"),
        {
            "budget_context_token": _budget_token(),
            "title": "Future Tokyo holiday",
            "duration_days": "7",
            "travelers": "1",
            "travel_start_date": "2026-12-03",
            "travel_end_date": "2026-12-09",
            "units_coffee": "1",
        },
    )
    scenario = SavedScenario.objects.get(user=user)
    with (
        patch("apps.travel.scenario_web.timezone.localdate", return_value=date(2026, 10, 9)),
        patch(
            "apps.travel.scenario_web.build_destination_context",
            return_value=_readiness_destination(),
        ) as context_builder,
        patch("apps.exchange.providers.frankfurter.FrankfurterProvider") as provider,
    ):
        response = client.get(
            reverse("saved_scenario_detail", args=(scenario.pk,)),
            {"local_context": "1"},
        )
    assert response.status_code == 200
    assert b"Future reviewed national holiday" in response.content
    assert b"Unrelated regional-only holiday" not in response.content
    # The refreshed Money Context Lens may separately include today's
    # 30-day calendar. Only the trip-readiness section must use trip dates.
    readiness = response.context["local_context"]["trip_readiness"]
    assert [holiday["name"] for holiday in readiness["holidays"]] == [
        "Future reviewed national holiday"
    ]
    assert b"3 Dec 2026" in response.content
    assert b"9 Dec 2026" in response.content
    assert b"A missing record does not establish" in response.content
    context_builder.assert_called_once()
    provider.assert_not_called()


@pytest.mark.django_db
def test_trip_calendar_review_is_bounded_to_first_90_days_and_excludes_past_dates(
    scenario_reference_data,
):
    japan = Country.objects.get(iso2="JP")
    with patch("apps.travel.trip_readiness.build_calendar_context") as builder:
        builder.return_value = None
        review = build_trip_calendar_review(
            country=japan,
            as_of=date(2026, 10, 9),
            travel_start_date=date(2026, 11, 1),
            travel_end_date=date(2027, 3, 1),
        )
    assert review is not None
    assert review.window_start == date(2026, 11, 1)
    assert review.window_end == date(2027, 1, 29)
    assert review.truncated is True
    builder.assert_called_once_with(country=japan, as_of=date(2026, 11, 1), window_days=89, limit=6)

    assert (
        build_trip_calendar_review(
            country=japan,
            as_of=date(2026, 10, 9),
            travel_start_date=date(2026, 9, 1),
            travel_end_date=date(2026, 9, 10),
        )
        is None
    )
    assert (
        build_trip_calendar_review(
            country=japan,
            as_of=date(2026, 10, 9),
            travel_start_date=None,
            travel_end_date=None,
        )
        is None
    )


def test_explicit_trip_calendar_check_reports_missing_evidence_without_inventing_a_holiday():
    destination = DestinationContext(
        country_code="JP",
        country_name="Japan",
        as_of=date(2026, 10, 9),
        payment=None,
        prices=(),
        calendar=None,
    )
    reviewed = TripCalendarReview(
        calendar=None,
        window_start=date(2026, 12, 3),
        window_end=date(2026, 12, 9),
        truncated=False,
    )
    result = build_trip_readiness(
        destination,
        as_of=date(2026, 10, 9),
        travel_start_date=date(2026, 12, 3),
        travel_end_date=date(2026, 12, 9),
        calendar_review=reviewed,
    )
    assert result is not None
    assert result["holidays"] == ()
    assert result["tips"] == ()
    assert result["trip_calendar_checked"] is True
    assert result["has_calendar_evidence"] is False
    assert result["trip_calendar_window_start"] == "3 Dec 2026"
    assert result["trip_calendar_window_end"] == "9 Dec 2026"


@pytest.mark.django_db
def test_saved_trip_holiday_evidence_is_not_hidden_by_empty_current_money_context(
    client, scenario_reference_data
):
    user = User.objects.create_user(username="holiday-only-owner", password="StrongPass-482!")
    client.force_login(user)
    country = Country.objects.get(iso2="JP")
    PublicHolidayObservation.objects.create(
        country=country,
        date=date(2026, 12, 6),
        name="Only reviewed trip-window holiday",
        national_holiday=True,
        subdivision_codes=[],
        holiday_types=["Public"],
        source_name="Nager.Date",
        source_url="https://example.test/only-trip-holiday",
        source_retrieved_at=datetime(2026, 10, 9, tzinfo=UTC),
        is_published=True,
    )
    client.post(
        reverse("save_budget_scenario"),
        {
            "budget_context_token": _budget_token(),
            "title": "Holiday-only Tokyo trip",
            "duration_days": "7",
            "travelers": "1",
            "travel_start_date": "2026-12-03",
            "travel_end_date": "2026-12-09",
            "units_coffee": "1",
        },
    )
    scenario = SavedScenario.objects.get(user=user)
    with (
        patch("apps.travel.scenario_web.timezone.localdate", return_value=date(2026, 10, 9)),
        patch(
            "apps.travel.scenario_web.build_destination_context",
            return_value=None,
        ) as context_builder,
        patch("apps.exchange.providers.frankfurter.FrankfurterProvider") as provider,
    ):
        page = client.get(
            reverse("saved_scenario_detail", args=(scenario.pk,)),
            {"local_context": "1"},
        )
    assert page.status_code == 200
    assert page.context["local_context"]["state"] == "available"
    assert page.context["local_context"]["component"] is None
    assert b"Only reviewed trip-window holiday" in page.content
    assert b"No current reviewed everyday-price" in page.content
    assert b"3 Dec 2026" in page.content
    assert b"9 Dec 2026" in page.content
    assert b"does not change your saved financial figures" in page.content
    context_builder.assert_called_once()
    provider.assert_not_called()


@pytest.mark.django_db
def test_saved_trip_without_current_context_or_trip_dates_stays_empty(
    client, scenario_reference_data
):
    user = User.objects.create_user(username="no-context-owner", password="StrongPass-482!")
    client.force_login(user)
    client.post(
        reverse("save_budget_scenario"),
        {
            "budget_context_token": _budget_token(),
            "title": "Unscheduled Tokyo trip",
            "duration_days": "7",
            "travelers": "1",
            "units_coffee": "1",
        },
    )
    scenario = SavedScenario.objects.get(user=user)
    with (
        patch("apps.travel.scenario_web.build_destination_context", return_value=None),
        patch("apps.travel.scenario_web.build_trip_calendar_review", return_value=None) as builder,
    ):
        page = client.get(
            reverse("saved_scenario_detail", args=(scenario.pk,)),
            {"local_context": "1"},
        )
    assert page.status_code == 200
    assert page.context["local_context"]["state"] == "empty"
    assert b"Only reviewed trip-window holiday" not in page.content
    builder.assert_called_once()
