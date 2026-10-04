from __future__ import annotations

from datetime import date

import pytest
from django.contrib.auth import get_user_model

from apps.countries.models import Country, Currency
from apps.travel.models import (
    SavedScenario,
    SavedScenarioKind,
    ScenarioNotificationCadence,
    ScenarioNotificationDeliveryChannel,
    ScenarioNotificationPreference,
    ScenarioNotificationType,
)
from apps.travel.notification_preferences import (
    ScenarioNotificationPreferenceError,
    delete_scenario_notification_preference,
    notification_preferences_for_scenario,
    upsert_scenario_notification_preference,
)

User = get_user_model()


@pytest.fixture
def notification_scenarios(db):
    fi = Country.objects.create(iso2="FI", iso3="FIN", name="Finland")
    jp = Country.objects.create(iso2="JP", iso3="JPN", name="Japan")
    eur = Currency.objects.create(code="EUR", name="Euro", minor_units=2)
    jpy = Currency.objects.create(code="JPY", name="Japanese yen", minor_units=0)
    owner = User.objects.create_user(username="notify-owner", password="StrongPass-482!")
    other = User.objects.create_user(username="notify-other", password="StrongPass-482!")
    with_date = SavedScenario.objects.create(
        user=owner,
        kind=SavedScenarioKind.BUDGET,
        title="Tokyo trip",
        source_currency=eur,
        destination_currency=jpy,
        source_country=fi,
        destination_country=jp,
        source_amount="1000",
        duration_days=5,
        travelers=1,
        travel_start_date=date(2026, 11, 10),
        travel_end_date=date(2026, 11, 15),
    )
    without_date = SavedScenario.objects.create(
        user=owner,
        kind=SavedScenarioKind.BUDGET,
        title="Unscheduled trip",
        source_currency=eur,
        destination_currency=jpy,
        source_country=fi,
        destination_country=jp,
        source_amount="500",
        duration_days=3,
        travelers=1,
    )
    return owner, other, with_date, without_date


@pytest.mark.django_db
def test_notification_preference_is_explicit_owner_scoped_and_upserts_same_type(
    notification_scenarios,
):
    owner, other, scenario, _without_date = notification_scenarios

    preference = upsert_scenario_notification_preference(
        owner,
        scenario_id=scenario.pk,
        notification_type=ScenarioNotificationType.PRE_TRIP,
        enabled=True,
        timezone_name="Europe/Helsinki",
        cadence=ScenarioNotificationCadence.ONCE,
    )

    assert preference.enabled is True
    assert preference.timezone == "Europe/Helsinki"
    assert preference.cadence == ScenarioNotificationCadence.ONCE
    assert preference.delivery_channel == ScenarioNotificationDeliveryChannel.IN_APP
    assert notification_preferences_for_scenario(
        owner,
        scenario_id=scenario.pk,
    ) == (preference,)
    assert notification_preferences_for_scenario(
        other,
        scenario_id=scenario.pk,
    ) == ()

    updated = upsert_scenario_notification_preference(
        owner,
        scenario_id=scenario.pk,
        notification_type=ScenarioNotificationType.PRE_TRIP,
        enabled=False,
        timezone_name="UTC",
        cadence=ScenarioNotificationCadence.WEEKLY,
    )

    assert updated.pk == preference.pk
    assert updated.enabled is False
    assert updated.timezone == "UTC"
    assert updated.cadence == ScenarioNotificationCadence.WEEKLY
    assert (
        ScenarioNotificationPreference.objects.filter(
            scenario=scenario,
            notification_type=ScenarioNotificationType.PRE_TRIP,
        ).count()
        == 1
    )


@pytest.mark.django_db
def test_pretrip_opt_in_requires_saved_travel_start_date(notification_scenarios):
    owner, _other, _with_date, without_date = notification_scenarios

    with pytest.raises(
        ScenarioNotificationPreferenceError,
        match="requires a saved travel start date",
    ):
        upsert_scenario_notification_preference(
            owner,
            scenario_id=without_date.pk,
            notification_type=ScenarioNotificationType.PRE_TRIP,
            enabled=True,
            timezone_name="Europe/Helsinki",
            cadence=ScenarioNotificationCadence.ONCE,
        )

    disabled = upsert_scenario_notification_preference(
        owner,
        scenario_id=without_date.pk,
        notification_type=ScenarioNotificationType.PRE_TRIP,
        enabled=False,
        timezone_name="Europe/Helsinki",
        cadence=ScenarioNotificationCadence.ONCE,
    )
    assert disabled.enabled is False


@pytest.mark.django_db
@pytest.mark.parametrize("timezone_name", ["", "Not/A_Timezone", "x" * 65])
def test_notification_preference_rejects_invalid_timezone(
    notification_scenarios,
    timezone_name,
):
    owner, _other, scenario, _without_date = notification_scenarios

    with pytest.raises(ScenarioNotificationPreferenceError, match="IANA timezone"):
        upsert_scenario_notification_preference(
            owner,
            scenario_id=scenario.pk,
            notification_type=ScenarioNotificationType.CONTEXT_FRESHNESS,
            enabled=True,
            timezone_name=timezone_name,
            cadence=ScenarioNotificationCadence.WEEKLY,
        )


@pytest.mark.django_db
def test_notification_preference_rejects_unsupported_configuration(notification_scenarios):
    owner, _other, scenario, _without_date = notification_scenarios

    with pytest.raises(ScenarioNotificationPreferenceError, match="notification type"):
        upsert_scenario_notification_preference(
            owner,
            scenario_id=scenario.pk,
            notification_type="generic_market_noise",
            enabled=True,
            timezone_name="Europe/Helsinki",
            cadence=ScenarioNotificationCadence.DAILY,
        )

    with pytest.raises(ScenarioNotificationPreferenceError, match="notification cadence"):
        upsert_scenario_notification_preference(
            owner,
            scenario_id=scenario.pk,
            notification_type=ScenarioNotificationType.RATE_ALERT,
            enabled=True,
            timezone_name="Europe/Helsinki",
            cadence="hourly",
        )

    with pytest.raises(ScenarioNotificationPreferenceError, match="delivery channel"):
        upsert_scenario_notification_preference(
            owner,
            scenario_id=scenario.pk,
            notification_type=ScenarioNotificationType.RATE_ALERT,
            enabled=True,
            timezone_name="Europe/Helsinki",
            cadence=ScenarioNotificationCadence.DAILY,
            delivery_channel="email",
        )


@pytest.mark.django_db
def test_notification_preference_cannot_cross_scenario_ownership(notification_scenarios):
    owner, other, scenario, _without_date = notification_scenarios

    with pytest.raises(ScenarioNotificationPreferenceError, match="no longer available"):
        upsert_scenario_notification_preference(
            other,
            scenario_id=scenario.pk,
            notification_type=ScenarioNotificationType.RATE_ALERT,
            enabled=True,
            timezone_name="Europe/Helsinki",
            cadence=ScenarioNotificationCadence.DAILY,
        )

    preference = upsert_scenario_notification_preference(
        owner,
        scenario_id=scenario.pk,
        notification_type=ScenarioNotificationType.RATE_ALERT,
        enabled=True,
        timezone_name="Europe/Helsinki",
        cadence=ScenarioNotificationCadence.DAILY,
    )
    assert delete_scenario_notification_preference(
        other,
        scenario_id=scenario.pk,
        notification_type=ScenarioNotificationType.RATE_ALERT,
    ) is False
    assert ScenarioNotificationPreference.objects.filter(pk=preference.pk).exists()


@pytest.mark.django_db
def test_notification_preference_disable_and_delete_are_explicit(notification_scenarios):
    owner, _other, scenario, _without_date = notification_scenarios
    preference = upsert_scenario_notification_preference(
        owner,
        scenario_id=scenario.pk,
        notification_type=ScenarioNotificationType.CONTEXT_FRESHNESS,
        enabled=True,
        timezone_name="Europe/Helsinki",
        cadence=ScenarioNotificationCadence.WEEKLY,
    )

    disabled = upsert_scenario_notification_preference(
        owner,
        scenario_id=scenario.pk,
        notification_type=ScenarioNotificationType.CONTEXT_FRESHNESS,
        enabled=False,
        timezone_name="Europe/Helsinki",
        cadence=ScenarioNotificationCadence.WEEKLY,
    )
    assert disabled.pk == preference.pk
    assert disabled.enabled is False

    assert delete_scenario_notification_preference(
        owner,
        scenario_id=scenario.pk,
        notification_type=ScenarioNotificationType.CONTEXT_FRESHNESS,
    ) is True
    assert delete_scenario_notification_preference(
        owner,
        scenario_id=scenario.pk,
        notification_type=ScenarioNotificationType.CONTEXT_FRESHNESS,
    ) is False


@pytest.mark.django_db
def test_notification_preferences_are_cascade_deleted_with_scenario(notification_scenarios):
    owner, _other, scenario, _without_date = notification_scenarios
    upsert_scenario_notification_preference(
        owner,
        scenario_id=scenario.pk,
        notification_type=ScenarioNotificationType.RATE_ALERT,
        enabled=True,
        timezone_name="Europe/Helsinki",
        cadence=ScenarioNotificationCadence.DAILY,
    )

    scenario.delete()

    assert ScenarioNotificationPreference.objects.count() == 0
