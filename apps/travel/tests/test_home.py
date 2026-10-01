from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.db import DatabaseError
from django.urls import reverse

from apps.countries.models import City, Country, CountryCurrency, Currency
from apps.culture.services import DestinationContext
from apps.exchange.domain import DEFAULT_SOURCE_POLICY, ConversionResult, RateQuote
from apps.travel.home import build_returning_trip_home
from apps.travel.models import SavedScenarioKind
from apps.travel.scenario_schedule import TripScheduleState
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
def home_reference_data(db):
    eur = Currency.objects.create(code="EUR", name="Euro", minor_units=2)
    jpy = Currency.objects.create(code="JPY", name="Japanese yen", minor_units=0)
    fi = Country.objects.create(iso2="FI", iso3="FIN", name="Finland")
    jp = Country.objects.create(iso2="JP", iso3="JPN", name="Japan")
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
    tokyo = City.objects.create(country=jp, slug="tokyo", name="Tokyo")
    return eur, jpy, fi, jp, tokyo


def _conversion(
    *,
    amount: Decimal = Decimal("600"),
    rate: Decimal = Decimal("174.5"),
    effective_date: date = date(2026, 9, 30),
) -> ConversionResult:
    return ConversionResult(
        input_amount=amount,
        output_amount=amount * rate,
        quote=RateQuote(
            base_currency="EUR",
            quote_currency="JPY",
            rate=rate,
            requested_date=None,
            effective_date=effective_date,
            fetched_at=datetime(2026, 10, 1, 8, tzinfo=UTC),
            provider_policy=DEFAULT_SOURCE_POLICY,
            provider_keys=("ecb",),
            historical=False,
        ),
        stale=False,
    )


def _scenario(
    user,
    reference_data,
    *,
    title: str,
    start: date | None,
    end: date | None,
):
    eur, jpy, fi, jp, tokyo = reference_data
    return create_saved_scenario(
        user,
        spec=SavedScenarioSpec(
            kind=SavedScenarioKind.BUDGET,
            title=title,
            source_currency=eur,
            destination_currency=jpy,
            source_country=fi,
            destination_country=jp,
            destination_city=tokyo,
            source_amount=Decimal("600"),
            duration_days=6,
            travelers=1,
            travel_start_date=start,
            travel_end_date=end,
        ),
        conversion=_conversion(),
    )


@pytest.mark.django_db
def test_anonymous_user_has_no_returning_trip_home(home_reference_data):
    class AnonymousOwner:
        pk = None
        is_authenticated = False

    assert build_returning_trip_home(AnonymousOwner(), as_of=date(2026, 10, 1)) is None


@pytest.mark.django_db
def test_active_trip_wins_over_upcoming_and_uses_saved_money_state(home_reference_data):
    user = User.objects.create_user(username="owner", password="StrongPass-482!")
    _scenario(
        user,
        home_reference_data,
        title="Later Tokyo",
        start=date(2026, 10, 20),
        end=date(2026, 10, 25),
    )
    active = _scenario(
        user,
        home_reference_data,
        title="Tokyo now",
        start=date(2026, 9, 30),
        end=date(2026, 10, 5),
    )
    record_scenario_spend(active, amount=Decimal("4700"))
    record_scenario_recheck(
        active,
        conversion=_conversion(
            rate=Decimal("180"),
            effective_date=date(2026, 10, 1),
        ),
    )
    destination = DestinationContext(
        country_code="JP",
        country_name="Japan",
        as_of=date(2026, 10, 1),
        payment=None,
        prices=(),
        city_slug="tokyo",
        city_name="Tokyo",
    )

    with patch("apps.travel.home.build_destination_context", return_value=destination) as builder:
        home = build_returning_trip_home(
            user,
            as_of=date(2026, 10, 1),
            camera_enabled=True,
        )

    assert home is not None
    assert home.scenario == active
    assert home.schedule.state is TripScheduleState.ACTIVE
    assert home.destination_label == "Tokyo, Japan"
    assert home.trip_budget is not None
    assert home.trip_budget.reference_budget == Decimal("104700")
    assert home.trip_budget.confirmed_spend == Decimal("4700")
    assert home.trip_budget.remaining == Decimal("100000")
    assert home.trip_budget.days == 5
    assert home.trip_budget.remaining_per_day == Decimal("20000")
    assert home.budget_day_label == "per remaining trip day"
    assert home.rate_comparison is not None
    assert home.rate_change_phrase == "3300 JPY more than the saved baseline"
    assert home.camera_url.endswith(f"/saved/scenarios/{active.pk}/camera/")
    assert home.offline_pack_url.endswith(f"/saved/scenarios/{active.pk}/offline-pack/")
    builder.assert_called_once_with(
        country_code="JP",
        converted_amount=Decimal("108000"),
        quote_currency="JPY",
        as_of=date(2026, 10, 1),
        price_limit=3,
        city_slug="tokyo",
    )


@pytest.mark.django_db
def test_nearest_upcoming_trip_is_selected(home_reference_data):
    user = User.objects.create_user(username="owner", password="StrongPass-482!")
    far = _scenario(
        user,
        home_reference_data,
        title="Far trip",
        start=date(2026, 12, 1),
        end=date(2026, 12, 5),
    )
    near = _scenario(
        user,
        home_reference_data,
        title="Near trip",
        start=date(2026, 10, 8),
        end=date(2026, 10, 12),
    )

    with patch("apps.travel.home.build_destination_context", return_value=None):
        home = build_returning_trip_home(user, as_of=date(2026, 10, 1))

    assert home is not None
    assert home.scenario == near
    assert home.scenario != far
    assert home.schedule.state is TripScheduleState.UPCOMING
    assert home.schedule.days_until_start == 7
    assert home.primary_action_label == "Re-check trip"
    assert home.budget_day_label == "per trip day"


@pytest.mark.django_db
def test_ended_unscheduled_and_other_users_scenarios_do_not_take_home(
    home_reference_data,
):
    owner = User.objects.create_user(username="owner", password="StrongPass-482!")
    other = User.objects.create_user(username="other", password="StrongPass-482!")
    _scenario(
        owner,
        home_reference_data,
        title="Ended",
        start=date(2026, 9, 1),
        end=date(2026, 9, 5),
    )
    _scenario(
        owner,
        home_reference_data,
        title="Unscheduled",
        start=None,
        end=None,
    )
    _scenario(
        other,
        home_reference_data,
        title="Someone else's active trip",
        start=date(2026, 9, 30),
        end=date(2026, 10, 5),
    )

    assert build_returning_trip_home(owner, as_of=date(2026, 10, 1)) is None


@pytest.mark.django_db
def test_destination_context_failure_does_not_remove_saved_trip_continuity(
    home_reference_data,
):
    user = User.objects.create_user(username="owner", password="StrongPass-482!")
    scenario = _scenario(
        user,
        home_reference_data,
        title="Tokyo",
        start=date(2026, 10, 10),
        end=date(2026, 10, 15),
    )

    with patch(
        "apps.travel.home.build_destination_context",
        side_effect=DatabaseError("context unavailable"),
    ):
        home = build_returning_trip_home(user, as_of=date(2026, 10, 1))

    assert home is not None
    assert home.scenario == scenario
    assert home.destination_context is None
    assert home.initial_observation is not None


@pytest.mark.django_db
def test_clean_converter_home_surfaces_upcoming_saved_trip_without_live_fx(
    client,
    home_reference_data,
):
    user = User.objects.create_user(username="web-owner", password="StrongPass-482!")
    scenario = _scenario(
        user,
        home_reference_data,
        title="Tokyo spring",
        start=date(2099, 4, 12),
        end=date(2099, 4, 18),
    )
    client.force_login(user)

    with patch("apps.exchange.views.build_latest_quote_gateway") as gateway_factory:
        response = client.get("/")

    assert response.status_code == 200
    assert b"qa-returning-trip-home" in response.content
    assert b"Tokyo spring" in response.content
    assert b"Upcoming trip" in response.content
    assert reverse("saved_scenario_detail", args=(scenario.pk,)).encode() in response.content
    gateway_factory.assert_not_called()


@pytest.mark.django_db
def test_loaded_converter_pair_keeps_focus_on_requested_pair_not_trip_home(
    client,
    home_reference_data,
):
    user = User.objects.create_user(username="load-owner", password="StrongPass-482!")
    _scenario(
        user,
        home_reference_data,
        title="Tokyo spring",
        start=date(2099, 4, 12),
        end=date(2099, 4, 18),
    )
    client.force_login(user)

    response = client.get(
        "/",
        {
            "load": "1",
            "source_currency": "EUR",
            "destination_currency": "JPY",
            "source_country": "FI",
            "destination_country": "JP",
        },
    )

    assert response.status_code == 200
    assert b"qa-returning-trip-home" not in response.content
