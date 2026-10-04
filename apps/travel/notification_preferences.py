from __future__ import annotations

from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.travel.models import (
    SavedScenario,
    ScenarioNotificationCadence,
    ScenarioNotificationDeliveryChannel,
    ScenarioNotificationPreference,
    ScenarioNotificationType,
)


class ScenarioNotificationPreferenceError(ValueError):
    """Raised when scenario notification intent/configuration is invalid."""


def notification_preferences_for_scenario(
    user,
    *,
    scenario_id: int,
) -> tuple[ScenarioNotificationPreference, ...]:
    if not user.is_authenticated:
        return ()

    return tuple(
        ScenarioNotificationPreference.objects.filter(
            scenario_id=scenario_id,
            scenario__user=user,
        )
        .select_related("scenario")
        .order_by("notification_type", "id")
    )


def upsert_scenario_notification_preference(
    user,
    *,
    scenario_id: int,
    notification_type: str,
    enabled: bool,
    timezone_name: str,
    cadence: str,
    delivery_channel: str = ScenarioNotificationDeliveryChannel.IN_APP,
    rate_change_threshold_percent: Decimal | str | None = None,
) -> ScenarioNotificationPreference:
    if not user.is_authenticated:
        raise ScenarioNotificationPreferenceError(
            "Authentication is required to configure scenario notifications."
        )
    if not isinstance(enabled, bool):
        raise ScenarioNotificationPreferenceError("Notification enabled state must be boolean.")

    notification_type_value = _choice_value(
        ScenarioNotificationType,
        notification_type,
        label="notification type",
    )
    cadence_value = _choice_value(
        ScenarioNotificationCadence,
        cadence,
        label="notification cadence",
    )
    channel_value = _choice_value(
        ScenarioNotificationDeliveryChannel,
        delivery_channel,
        label="delivery channel",
    )
    timezone_value = _normalize_timezone(timezone_name)

    with transaction.atomic():
        try:
            scenario = SavedScenario.objects.select_for_update().get(
                pk=scenario_id,
                user=user,
            )
        except SavedScenario.DoesNotExist as exc:
            raise ScenarioNotificationPreferenceError(
                "That saved scenario is no longer available."
            ) from exc

        if (
            enabled
            and notification_type_value == ScenarioNotificationType.PRE_TRIP
            and scenario.travel_start_date is None
        ):
            raise ScenarioNotificationPreferenceError(
                "A pre-trip reminder requires a saved travel start date."
            )

        threshold_value: Decimal | None = None
        if notification_type_value == ScenarioNotificationType.RATE_ALERT:
            if rate_change_threshold_percent in (None, ""):
                existing = ScenarioNotificationPreference.objects.filter(
                    scenario=scenario,
                    notification_type=notification_type_value,
                ).only("rate_change_threshold_percent").first()
                threshold_value = (
                    existing.rate_change_threshold_percent if existing is not None else None
                )
                if enabled and threshold_value is None:
                    raise ScenarioNotificationPreferenceError(
                        "Choose a rate-change threshold before enabling this alert."
                    )
            else:
                threshold_value = _normalize_rate_threshold(rate_change_threshold_percent)

        preference, _created = ScenarioNotificationPreference.objects.update_or_create(
            scenario=scenario,
            notification_type=notification_type_value,
            defaults={
                "enabled": enabled,
                "timezone": timezone_value,
                "cadence": cadence_value,
                "delivery_channel": channel_value,
                "rate_change_threshold_percent": threshold_value,
            },
        )
        try:
            preference.full_clean()
        except ValidationError as exc:
            raise ScenarioNotificationPreferenceError(_validation_message(exc)) from exc
        preference.save()
        return preference


def delete_scenario_notification_preference(
    user,
    *,
    scenario_id: int,
    notification_type: str,
) -> bool:
    if not user.is_authenticated:
        raise ScenarioNotificationPreferenceError(
            "Authentication is required to delete scenario notifications."
        )

    notification_type_value = _choice_value(
        ScenarioNotificationType,
        notification_type,
        label="notification type",
    )
    deleted, _ = ScenarioNotificationPreference.objects.filter(
        scenario_id=scenario_id,
        scenario__user=user,
        notification_type=notification_type_value,
    ).delete()
    return bool(deleted)


def _choice_value(choice_type, raw_value: str, *, label: str) -> str:
    value = str(raw_value or "").strip()
    try:
        return choice_type(value)
    except ValueError as exc:
        raise ScenarioNotificationPreferenceError(f"Unsupported {label}.") from exc


def _normalize_timezone(raw_value: str) -> str:
    value = str(raw_value or "").strip()
    if not value or len(value) > 64:
        raise ScenarioNotificationPreferenceError("Choose a valid IANA timezone.")
    try:
        return ZoneInfo(value).key
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ScenarioNotificationPreferenceError("Choose a valid IANA timezone.") from exc


def _validation_message(exc: ValidationError) -> str:
    if hasattr(exc, "message_dict"):
        for messages in exc.message_dict.values():
            if messages:
                return str(messages[0])
    if exc.messages:
        return str(exc.messages[0])
    return "Scenario notification preference validation failed."


def _normalize_rate_threshold(raw_value: Decimal | str) -> Decimal:
    try:
        value = Decimal(str(raw_value))
    except (InvalidOperation, ValueError) as exc:
        raise ScenarioNotificationPreferenceError(
            "Rate-change threshold must be a valid percentage."
        ) from exc

    if not value.is_finite() or value < Decimal("0.1") or value > Decimal("25"):
        raise ScenarioNotificationPreferenceError(
            "Rate-change threshold must be between 0.1% and 25%."
        )
    return value.quantize(Decimal("0.1"))
