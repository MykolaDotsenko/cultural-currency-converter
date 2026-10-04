from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from apps.accounts.models import NotificationPreference
from apps.accounts.notification_preferences import (
    NotificationPreferenceError,
    delete_pre_trip_preference,
    pre_trip_preference_for_user,
    save_pre_trip_preference,
)

User = get_user_model()


class Anonymous:
    is_authenticated = False


@pytest.mark.django_db
def test_pre_trip_preference_defaults_to_no_row_and_anonymous_has_none():
    user = User.objects.create_user(username="notification-default", password="StrongPass-482!")

    assert pre_trip_preference_for_user(user) is None
    assert pre_trip_preference_for_user(Anonymous()) is None
    assert NotificationPreference.objects.count() == 0


@pytest.mark.django_db
def test_pre_trip_preference_enable_update_and_disable_are_explicit():
    user = User.objects.create_user(username="notification-owner", password="StrongPass-482!")

    enabled = save_pre_trip_preference(
        user,
        enabled=True,
        timezone_name="Europe/Helsinki",
        cadence=NotificationPreference.Cadence.ONCE,
        lead_days=3,
        delivery_channel=NotificationPreference.DeliveryChannel.IN_APP,
    )

    assert enabled is not None
    assert enabled.enabled is True
    assert enabled.timezone_name == "Europe/Helsinki"
    assert enabled.cadence == NotificationPreference.Cadence.ONCE
    assert enabled.lead_days == 3
    assert enabled.delivery_channel == NotificationPreference.DeliveryChannel.IN_APP

    updated = save_pre_trip_preference(
        user,
        enabled=True,
        timezone_name="America/Toronto",
        cadence=NotificationPreference.Cadence.DAILY,
        lead_days=5,
        delivery_channel=NotificationPreference.DeliveryChannel.IN_APP,
    )

    assert updated is not None
    assert updated.pk == enabled.pk
    assert updated.timezone_name == "America/Toronto"
    assert updated.cadence == NotificationPreference.Cadence.DAILY
    assert updated.lead_days == 5

    disabled = save_pre_trip_preference(
        user,
        enabled=False,
        timezone_name="America/Toronto",
        cadence=NotificationPreference.Cadence.DAILY,
        lead_days=5,
        delivery_channel=NotificationPreference.DeliveryChannel.IN_APP,
    )

    assert disabled is not None
    assert disabled.pk == enabled.pk
    assert disabled.enabled is False
    assert NotificationPreference.objects.filter(user=user).count() == 1


@pytest.mark.django_db
def test_disabling_without_existing_preference_does_not_create_row():
    user = User.objects.create_user(username="notification-no-row", password="StrongPass-482!")

    result = save_pre_trip_preference(
        user,
        enabled=False,
        timezone_name="UTC",
        cadence=NotificationPreference.Cadence.ONCE,
        lead_days=3,
        delivery_channel=NotificationPreference.DeliveryChannel.IN_APP,
    )

    assert result is None
    assert NotificationPreference.objects.count() == 0


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        (
            {
                "enabled": True,
                "timezone_name": "Not/A_Real_Timezone",
                "cadence": NotificationPreference.Cadence.ONCE,
                "lead_days": 3,
                "delivery_channel": NotificationPreference.DeliveryChannel.IN_APP,
            },
            "IANA timezone",
        ),
        (
            {
                "enabled": True,
                "timezone_name": "UTC",
                "cadence": "hourly",
                "lead_days": 3,
                "delivery_channel": NotificationPreference.DeliveryChannel.IN_APP,
            },
            "supported reminder cadence",
        ),
        (
            {
                "enabled": True,
                "timezone_name": "UTC",
                "cadence": NotificationPreference.Cadence.ONCE,
                "lead_days": 0,
                "delivery_channel": NotificationPreference.DeliveryChannel.IN_APP,
            },
            "greater than or equal to 1",
        ),
        (
            {
                "enabled": True,
                "timezone_name": "UTC",
                "cadence": NotificationPreference.Cadence.ONCE,
                "lead_days": 3,
                "delivery_channel": "email",
            },
            "supported notification delivery channel",
        ),
    ],
)
def test_pre_trip_preference_rejects_invalid_configuration(kwargs, message):
    user = User.objects.create_user(
        username=f"notification-invalid-{kwargs['lead_days']}-{kwargs['cadence']}",
        password="StrongPass-482!",
    )

    with pytest.raises(NotificationPreferenceError, match=message):
        save_pre_trip_preference(user, **kwargs)

    assert NotificationPreference.objects.filter(user=user).count() == 0


@pytest.mark.django_db
def test_pre_trip_preference_delete_is_owner_scoped_by_current_user():
    owner = User.objects.create_user(username="notification-delete-owner", password="StrongPass-482!")
    other = User.objects.create_user(username="notification-delete-other", password="StrongPass-482!")
    save_pre_trip_preference(
        owner,
        enabled=True,
        timezone_name="Europe/Helsinki",
        cadence=NotificationPreference.Cadence.ONCE,
        lead_days=3,
    )
    save_pre_trip_preference(
        other,
        enabled=True,
        timezone_name="Europe/London",
        cadence=NotificationPreference.Cadence.ONCE,
        lead_days=7,
    )

    assert delete_pre_trip_preference(owner) is True
    assert delete_pre_trip_preference(owner) is False
    assert pre_trip_preference_for_user(owner) is None
    assert pre_trip_preference_for_user(other) is not None


@pytest.mark.django_db
def test_notification_preference_service_requires_authentication():
    with pytest.raises(NotificationPreferenceError, match="Authentication"):
        save_pre_trip_preference(
            Anonymous(),
            enabled=True,
            timezone_name="UTC",
            cadence=NotificationPreference.Cadence.ONCE,
            lead_days=3,
        )

    with pytest.raises(NotificationPreferenceError, match="Authentication"):
        delete_pre_trip_preference(Anonymous())
