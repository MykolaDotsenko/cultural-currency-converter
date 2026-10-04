from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.countries.models import Country, Currency
from apps.travel.models import (
    SavedScenario,
    SavedScenarioKind,
    SavedScenarioObservation,
    SavedScenarioObservationKind,
    ScenarioNotificationCadence,
    ScenarioNotificationDelivery,
    ScenarioNotificationPreference,
    ScenarioNotificationType,
)
from apps.travel.notification_delivery import (
    RateAlertProbe,
    generate_due_notifications,
)
from apps.travel.notification_preferences import (
    ScenarioNotificationPreferenceError,
    upsert_scenario_notification_preference,
)

User = get_user_model()


@pytest.fixture
def notification_delivery_scenario(db):
    fi = Country.objects.create(iso2="FI", iso3="FIN", name="Finland")
    jp = Country.objects.create(iso2="JP", iso3="JPN", name="Japan")
    eur = Currency.objects.create(code="EUR", name="Euro", minor_units=2)
    jpy = Currency.objects.create(code="JPY", name="Japanese yen", minor_units=0)
    owner = User.objects.create_user(username="notify-delivery", password="StrongPass-482!")
    scenario = SavedScenario.objects.create(
        user=owner,
        kind=SavedScenarioKind.BUDGET,
        title="Tokyo trip",
        source_currency=eur,
        destination_currency=jpy,
        source_country=fi,
        destination_country=jp,
        source_amount=Decimal("1000"),
        duration_days=5,
        travelers=1,
        travel_start_date=date(2026, 10, 10),
        travel_end_date=date(2026, 10, 15),
    )
    SavedScenarioObservation.objects.create(
        scenario=scenario,
        kind=SavedScenarioObservationKind.INITIAL,
        input_amount=Decimal("1000"),
        output_amount=Decimal("174500"),
        rate=Decimal("174.5"),
        effective_date=date(2026, 9, 20),
        fetched_at=datetime(2026, 9, 20, 9, tzinfo=UTC),
        provider_keys=["ecb"],
        stale=False,
    )
    return owner, scenario


@pytest.mark.django_db
def test_pre_trip_notification_is_due_once_and_scheduler_retry_is_idempotent(
    notification_delivery_scenario,
):
    owner, scenario = notification_delivery_scenario
    preference = upsert_scenario_notification_preference(
        owner,
        scenario_id=scenario.pk,
        notification_type=ScenarioNotificationType.PRE_TRIP,
        enabled=True,
        timezone_name="Europe/Helsinki",
        cadence=ScenarioNotificationCadence.ONCE,
    )
    now = datetime(2026, 10, 4, 9, tzinfo=UTC)

    first = generate_due_notifications(now=now)
    second = generate_due_notifications(now=now)

    assert len(first) == 1
    assert second == ()
    assert ScenarioNotificationDelivery.objects.filter(preference=preference).count() == 1
    preference.refresh_from_db()
    assert preference.last_delivered_at is not None
    assert "starts in 6 days" in first[0].title


@pytest.mark.django_db
def test_context_freshness_reminder_requires_old_or_stale_saved_reference(
    notification_delivery_scenario,
):
    owner, scenario = notification_delivery_scenario
    upsert_scenario_notification_preference(
        owner,
        scenario_id=scenario.pk,
        notification_type=ScenarioNotificationType.CONTEXT_FRESHNESS,
        enabled=True,
        timezone_name="Europe/Helsinki",
        cadence=ScenarioNotificationCadence.WEEKLY,
    )

    deliveries = generate_due_notifications(
        now=datetime(2026, 10, 4, 9, tzinfo=UTC),
    )

    assert len(deliveries) == 1
    assert "Refresh Tokyo trip before travel" == deliveries[0].title
    assert "Stored values remain references, not live rates." in deliveries[0].body


@pytest.mark.django_db
def test_rate_alert_uses_explicit_threshold_and_never_persists_probe_as_observation(
    notification_delivery_scenario,
):
    owner, scenario = notification_delivery_scenario
    upsert_scenario_notification_preference(
        owner,
        scenario_id=scenario.pk,
        notification_type=ScenarioNotificationType.RATE_ALERT,
        enabled=True,
        timezone_name="Europe/Helsinki",
        cadence=ScenarioNotificationCadence.DAILY,
        rate_change_threshold_percent=Decimal("2.0"),
    )

    deliveries = generate_due_notifications(
        now=datetime(2026, 10, 4, 9, tzinfo=UTC),
        rate_probe=lambda _scenario, _now: RateAlertProbe(
            rate=Decimal("180"),
            output_amount=Decimal("180000"),
            effective_date=date(2026, 10, 4),
            stale=False,
        ),
    )

    assert len(deliveries) == 1
    assert "3.2%" in deliveries[0].title
    assert "informational, not a recommendation" in deliveries[0].body
    assert scenario.observations.count() == 1


@pytest.mark.django_db
def test_rate_alert_requires_explicit_threshold(notification_delivery_scenario):
    owner, scenario = notification_delivery_scenario

    with pytest.raises(ScenarioNotificationPreferenceError, match="threshold"):
        upsert_scenario_notification_preference(
            owner,
            scenario_id=scenario.pk,
            notification_type=ScenarioNotificationType.RATE_ALERT,
            enabled=True,
            timezone_name="Europe/Helsinki",
            cadence=ScenarioNotificationCadence.DAILY,
        )


@pytest.mark.django_db
def test_daily_notification_waits_for_next_local_calendar_day(
    notification_delivery_scenario,
):
    owner, scenario = notification_delivery_scenario
    preference = upsert_scenario_notification_preference(
        owner,
        scenario_id=scenario.pk,
        notification_type=ScenarioNotificationType.PRE_TRIP,
        enabled=True,
        timezone_name="Europe/Helsinki",
        cadence=ScenarioNotificationCadence.DAILY,
    )
    first_now = datetime(2026, 10, 4, 9, tzinfo=UTC)
    first = generate_due_notifications(now=first_now)
    assert len(first) == 1

    same_local_day = generate_due_notifications(
        now=first_now + timedelta(hours=10),
    )
    next_local_day = generate_due_notifications(
        now=first_now + timedelta(days=1),
    )

    assert same_local_day == ()
    assert len(next_local_day) == 1
    assert ScenarioNotificationDelivery.objects.filter(preference=preference).count() == 2


@pytest.mark.django_db
def test_notification_web_is_owner_scoped_and_read_state_is_explicit(
    client,
    notification_delivery_scenario,
):
    owner, scenario = notification_delivery_scenario
    other = User.objects.create_user(username="notify-reader-other", password="StrongPass-482!")
    upsert_scenario_notification_preference(
        owner,
        scenario_id=scenario.pk,
        notification_type=ScenarioNotificationType.PRE_TRIP,
        enabled=True,
        timezone_name="Europe/Helsinki",
        cadence=ScenarioNotificationCadence.ONCE,
    )
    delivery = generate_due_notifications(
        now=datetime(2026, 10, 4, 9, tzinfo=UTC),
    )[0]

    client.force_login(other)
    other_inbox = client.get(reverse("notification_inbox"))
    assert other_inbox.status_code == 200
    assert b"Tokyo trip" not in other_inbox.content
    mark_other = client.post(reverse("mark_notification_read", args=(delivery.pk,)))
    assert mark_other.status_code == 302
    delivery.refresh_from_db()
    assert delivery.read_at is None

    client.force_login(owner)
    inbox = client.get(reverse("notification_inbox"))
    assert inbox.status_code == 200
    assert b"Tokyo trip" in inbox.content
    assert b"1 unread" in inbox.content

    marked = client.post(reverse("mark_notification_read", args=(delivery.pk,)))
    assert marked.status_code == 302
    delivery.refresh_from_db()
    assert delivery.read_at is not None


@pytest.mark.django_db
def test_scenario_detail_exposes_notification_configuration(
    client,
    notification_delivery_scenario,
):
    owner, scenario = notification_delivery_scenario
    client.force_login(owner)

    response = client.get(reverse("saved_scenario_detail", args=(scenario.pk,)))

    assert response.status_code == 200
    assert b"Trip notifications" in response.content
    assert b"Pre-trip reminder" in response.content
    assert b"Context &amp; offline freshness" in response.content
    assert b"Scenario rate alert" in response.content
    assert reverse("notification_inbox").encode() in response.content


@pytest.mark.django_db
def test_notification_configuration_post_persists_explicit_rate_threshold(
    client,
    notification_delivery_scenario,
):
    owner, scenario = notification_delivery_scenario
    client.force_login(owner)

    response = client.post(
        reverse("configure_saved_scenario_notification", args=(scenario.pk,)),
        {
            "notification_type": ScenarioNotificationType.RATE_ALERT,
            "enabled": "1",
            "timezone": "Europe/Helsinki",
            "cadence": ScenarioNotificationCadence.DAILY,
            "rate_change_threshold_percent": "2.5",
        },
    )

    assert response.status_code == 302
    preference = ScenarioNotificationPreference.objects.get(
        scenario=scenario,
        notification_type=ScenarioNotificationType.RATE_ALERT,
    )
    assert preference.enabled is True
    assert preference.rate_change_threshold_percent == Decimal("2.50")
