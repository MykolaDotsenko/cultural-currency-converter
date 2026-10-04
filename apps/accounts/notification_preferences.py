from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction

from apps.accounts.models import NotificationPreference


class NotificationPreferenceError(ValueError):
    """Raised when explicit notification configuration violates the account contract."""


def notification_preference_for_user(
    user,
    *,
    notification_type: str,
) -> NotificationPreference | None:
    if not user.is_authenticated:
        return None

    return NotificationPreference.objects.filter(
        user=user,
        notification_type=notification_type,
    ).first()


def pre_trip_preference_for_user(user) -> NotificationPreference | None:
    return notification_preference_for_user(
        user,
        notification_type=NotificationPreference.NotificationType.PRE_TRIP,
    )


def save_pre_trip_preference(
    user,
    *,
    enabled: bool,
    timezone_name: str,
    cadence: str,
    lead_days: int,
    delivery_channel: str = NotificationPreference.DeliveryChannel.IN_APP,
) -> NotificationPreference | None:
    if not user.is_authenticated:
        raise NotificationPreferenceError(
            "Authentication is required to change notification preferences."
        )
    if not isinstance(enabled, bool):
        raise NotificationPreferenceError("Notification enabled state must be explicit.")
    if not isinstance(lead_days, int) or isinstance(lead_days, bool):
        raise NotificationPreferenceError("Reminder lead time must be an integer number of days.")

    normalized_timezone = timezone_name.strip()
    if not normalized_timezone:
        raise NotificationPreferenceError("Enter an IANA timezone.")
    if cadence not in NotificationPreference.Cadence.values:
        raise NotificationPreferenceError("Choose a supported reminder cadence.")
    if delivery_channel not in NotificationPreference.DeliveryChannel.values:
        raise NotificationPreferenceError("Choose a supported notification delivery channel.")

    user_model = get_user_model()
    with transaction.atomic():
        user_model.objects.select_for_update().get(pk=user.pk)
        preference = NotificationPreference.objects.filter(
            user=user,
            notification_type=NotificationPreference.NotificationType.PRE_TRIP,
        ).first()

        if preference is None and not enabled:
            return None

        if preference is None:
            preference = NotificationPreference(
                user=user,
                notification_type=NotificationPreference.NotificationType.PRE_TRIP,
            )

        preference.enabled = enabled
        preference.timezone_name = normalized_timezone
        preference.cadence = cadence
        preference.lead_days = lead_days
        preference.delivery_channel = delivery_channel
        try:
            preference.full_clean()
        except ValidationError as exc:
            raise NotificationPreferenceError(_validation_message(exc)) from exc
        preference.save()
        return preference


def delete_pre_trip_preference(user) -> bool:
    if not user.is_authenticated:
        raise NotificationPreferenceError(
            "Authentication is required to delete notification preferences."
        )

    deleted, _ = NotificationPreference.objects.filter(
        user=user,
        notification_type=NotificationPreference.NotificationType.PRE_TRIP,
    ).delete()
    return bool(deleted)


def _validation_message(exc: ValidationError) -> str:
    if hasattr(exc, "message_dict"):
        for messages in exc.message_dict.values():
            if messages:
                return str(messages[0])
    if exc.messages:
        return str(exc.messages[0])
    return "Notification preference validation failed."
