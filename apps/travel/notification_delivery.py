from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation, localcontext
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db import transaction
from django.utils import timezone

from apps.exchange.config import FxConfigurationError
from apps.exchange.domain import FxDomainError
from apps.exchange.providers.base import FxProviderError
from apps.exchange.services import quote_conversion
from apps.exchange.web.gateways import build_latest_quote_gateway
from apps.travel.models import (
    SavedScenario,
    SavedScenarioObservation,
    SavedScenarioObservationKind,
    ScenarioNotificationCadence,
    ScenarioNotificationDelivery,
    ScenarioNotificationDeliveryChannel,
    ScenarioNotificationPreference,
    ScenarioNotificationType,
)

logger = logging.getLogger("cultural_currency.travel")


@dataclass(frozen=True, slots=True)
class RateAlertProbe:
    rate: Decimal
    output_amount: Decimal
    effective_date: date
    stale: bool


@dataclass(frozen=True, slots=True)
class NotificationCandidate:
    preference_id: int
    dedupe_key: str
    title: str
    body: str
    due_at: datetime


RateProbe = Callable[[SavedScenario, datetime], RateAlertProbe]


def probe_current_scenario_rate(scenario: SavedScenario, now: datetime) -> RateAlertProbe:
    result = quote_conversion(
        amount=scenario.source_amount,
        base_currency=scenario.source_currency.code,
        quote_currency=scenario.destination_currency.code,
        quote_minor_units=scenario.destination_currency.minor_units,
        gateway=build_latest_quote_gateway(),
        now=now,
    )
    return RateAlertProbe(
        rate=result.quote.rate,
        output_amount=result.output_amount,
        effective_date=result.quote.effective_date,
        stale=result.stale,
    )


def _local_date(preference: ScenarioNotificationPreference, value: datetime) -> date | None:
    try:
        zone = ZoneInfo(preference.timezone)
    except ZoneInfoNotFoundError:
        logger.warning(
            "scenario_notification_timezone_invalid",
            extra={"preference_id": preference.pk},
        )
        return None
    return timezone.localtime(value, zone).date()


def _cadence_allows(
    preference: ScenarioNotificationPreference,
    *,
    local_today: date,
) -> bool:
    last = preference.last_delivered_at
    if last is None:
        return True
    if preference.cadence == ScenarioNotificationCadence.ONCE:
        return False

    last_local = _local_date(preference, last)
    if last_local is None:
        return False
    if preference.cadence == ScenarioNotificationCadence.DAILY:
        return last_local < local_today
    if preference.cadence == ScenarioNotificationCadence.WEEKLY:
        return (local_today - last_local).days >= 7
    return False


def _period_token(
    preference: ScenarioNotificationPreference,
    *,
    local_today: date,
) -> str:
    if preference.cadence == ScenarioNotificationCadence.ONCE:
        return "once"
    if preference.cadence == ScenarioNotificationCadence.DAILY:
        return local_today.isoformat()
    iso = local_today.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _format_amount(value: Decimal, minor_units: int) -> str:
    quantum = Decimal(1).scaleb(-minor_units)
    with localcontext() as context:
        context.prec = max(64, len(value.as_tuple().digits) + minor_units + 8)
        rounded = value.quantize(quantum, rounding=ROUND_HALF_EVEN)
    return format(rounded, f".{minor_units}f") if minor_units else format(rounded, "f")


def _initial_observation(
    scenario: SavedScenario,
) -> SavedScenarioObservation | None:
    return next(
        (
            observation
            for observation in scenario.observations.all()
            if observation.kind == SavedScenarioObservationKind.INITIAL
        ),
        None,
    )


def _latest_observation(
    scenario: SavedScenario,
) -> SavedScenarioObservation | None:
    observations = tuple(scenario.observations.all())
    if not observations:
        return None
    return max(observations, key=lambda item: (item.recorded_at, item.pk))


def _pre_trip_candidate(
    preference: ScenarioNotificationPreference,
    *,
    now: datetime,
    local_today: date,
) -> NotificationCandidate | None:
    scenario = preference.scenario
    start = scenario.travel_start_date
    if start is None:
        return None

    days = (start - local_today).days
    if days < 0 or days > 7:
        return None

    if days == 0:
        timing = "today"
    elif days == 1:
        timing = "tomorrow"
    else:
        timing = f"in {days} days"

    return NotificationCandidate(
        preference_id=preference.pk,
        dedupe_key=f"pre-trip:{start.isoformat()}:{_period_token(preference, local_today=local_today)}",
        title=f"{scenario.title or 'Saved trip'} starts {timing}",
        body=(
            "Reopen the saved scenario when useful, re-check the reference rate explicitly, "
            "and review current destination money context before departure."
        ),
        due_at=now,
    )


def _freshness_candidate(
    preference: ScenarioNotificationPreference,
    *,
    now: datetime,
    local_today: date,
) -> NotificationCandidate | None:
    scenario = preference.scenario
    start = scenario.travel_start_date
    if start is None:
        return None

    days_until = (start - local_today).days
    if days_until < 0 or days_until > 14:
        return None

    observation = _latest_observation(scenario)
    if observation is None:
        return None

    age_days = max(0, (now - observation.fetched_at).days)
    if not observation.stale and age_days < 7:
        return None

    freshness = "marked stale" if observation.stale else f"{age_days} days old"
    return NotificationCandidate(
        preference_id=preference.pk,
        dedupe_key=(
            f"context-freshness:{observation.pk}:"
            f"{_period_token(preference, local_today=local_today)}"
        ),
        title=f"Refresh {scenario.title or 'saved trip'} before travel",
        body=(
            f"The newest stored FX reference is {freshness}. Re-check it explicitly, refresh the "
            "local money guide, and replace any offline pack you plan to rely on. Stored values "
            "remain references, not live rates."
        ),
        due_at=now,
    )


def _rate_alert_candidate(
    preference: ScenarioNotificationPreference,
    *,
    now: datetime,
    local_today: date,
    rate_probe: RateProbe,
) -> NotificationCandidate | None:
    scenario = preference.scenario
    threshold = preference.rate_change_threshold_percent
    initial = _initial_observation(scenario)
    if threshold is None or initial is None or initial.rate <= 0:
        return None

    try:
        probe = rate_probe(scenario, now)
    except (FxConfigurationError, FxDomainError, FxProviderError, ValueError) as exc:
        logger.warning(
            "scenario_notification_rate_probe_unavailable",
            extra={
                "preference_id": preference.pk,
                "scenario_id": scenario.pk,
                "error_code": exc.__class__.__name__,
            },
        )
        return None

    if probe.stale or probe.rate <= 0:
        return None

    try:
        percent = ((probe.rate - initial.rate) / initial.rate * Decimal("100")).quantize(
            Decimal("0.1"),
            rounding=ROUND_HALF_EVEN,
        )
    except InvalidOperation:
        return None
    if abs(percent) < threshold:
        return None

    difference = probe.output_amount - initial.output_amount
    direction = "more" if difference > 0 else "less" if difference < 0 else "the same amount"
    amount_text = _format_amount(
        abs(difference),
        scenario.destination_currency.minor_units,
    )
    if difference == 0:
        comparison_text = (
            f"the same rounded {scenario.destination_currency.code} amount as the saved baseline"
        )
    else:
        comparison_text = f"{amount_text} {scenario.destination_currency.code} {direction} than the saved baseline"

    return NotificationCandidate(
        preference_id=preference.pk,
        dedupe_key=(
            f"rate-alert:{probe.effective_date.isoformat()}:{probe.rate}:"
            f"{_period_token(preference, local_today=local_today)}"
        ),
        title=f"Saved trip reference rate moved {abs(percent)}%",
        body=(
            f"At the latest reference rate, the saved source amount would convert to "
            f"{_format_amount(probe.output_amount, scenario.destination_currency.minor_units)} "
            f"{scenario.destination_currency.code}, {comparison_text}. "
            "This is informational, not a recommendation to exchange money."
        ),
        due_at=now,
    )


def collect_due_notification_candidates(
    *,
    now: datetime | None = None,
    scenario_ids: Iterable[int] | None = None,
    rate_probe: RateProbe | None = None,
) -> tuple[NotificationCandidate, ...]:
    selected_now = now or timezone.now()
    probe = rate_probe or probe_current_scenario_rate

    preferences = (
        ScenarioNotificationPreference.objects.filter(
            enabled=True,
            delivery_channel=ScenarioNotificationDeliveryChannel.IN_APP,
        )
        .select_related(
            "scenario",
            "scenario__user",
            "scenario__source_currency",
            "scenario__destination_currency",
        )
        .prefetch_related("scenario__observations")
        .order_by("id")
    )
    if scenario_ids is not None:
        ids = tuple({int(value) for value in scenario_ids})
        if not ids:
            return ()
        preferences = preferences.filter(scenario_id__in=ids)

    candidates: list[NotificationCandidate] = []
    for preference in preferences:
        local_today = _local_date(preference, selected_now)
        if local_today is None or not _cadence_allows(preference, local_today=local_today):
            continue

        if preference.notification_type == ScenarioNotificationType.PRE_TRIP:
            candidate = _pre_trip_candidate(
                preference,
                now=selected_now,
                local_today=local_today,
            )
        elif preference.notification_type == ScenarioNotificationType.CONTEXT_FRESHNESS:
            candidate = _freshness_candidate(
                preference,
                now=selected_now,
                local_today=local_today,
            )
        elif preference.notification_type == ScenarioNotificationType.RATE_ALERT:
            candidate = _rate_alert_candidate(
                preference,
                now=selected_now,
                local_today=local_today,
                rate_probe=probe,
            )
        else:
            candidate = None

        if candidate is not None:
            candidates.append(candidate)

    return tuple(candidates)


def generate_due_notifications(
    *,
    now: datetime | None = None,
    scenario_ids: Iterable[int] | None = None,
    rate_probe: RateProbe | None = None,
) -> tuple[ScenarioNotificationDelivery, ...]:
    selected_now = now or timezone.now()
    candidates = collect_due_notification_candidates(
        now=selected_now,
        scenario_ids=scenario_ids,
        rate_probe=rate_probe,
    )
    created: list[ScenarioNotificationDelivery] = []

    for candidate in candidates:
        with transaction.atomic():
            preference = (
                ScenarioNotificationPreference.objects.select_for_update()
                .select_related("scenario")
                .get(pk=candidate.preference_id)
            )
            if not preference.enabled:
                continue
            local_today = _local_date(preference, selected_now)
            if local_today is None or not _cadence_allows(preference, local_today=local_today):
                continue

            delivery, was_created = ScenarioNotificationDelivery.objects.get_or_create(
                preference=preference,
                dedupe_key=candidate.dedupe_key,
                defaults={
                    "title": candidate.title,
                    "body": candidate.body,
                },
            )
            if not was_created:
                continue

            ScenarioNotificationPreference.objects.filter(pk=preference.pk).update(
                last_delivered_at=selected_now,
            )
            created.append(delivery)

    return tuple(created)


def notifications_for_user(user, *, limit: int = 50):
    if not user.is_authenticated:
        return ScenarioNotificationDelivery.objects.none()
    return (
        ScenarioNotificationDelivery.objects.filter(
            preference__scenario__user=user,
        )
        .select_related(
            "preference",
            "preference__scenario",
        )
        .order_by("-created_at", "-id")[:limit]
    )


def mark_notification_read(user, *, delivery_id: int) -> bool:
    if not user.is_authenticated:
        return False
    updated = ScenarioNotificationDelivery.objects.filter(
        pk=delivery_id,
        preference__scenario__user=user,
        read_at__isnull=True,
    ).update(read_at=timezone.now())
    return bool(updated)


def mark_all_notifications_read(user) -> int:
    if not user.is_authenticated:
        return 0
    return ScenarioNotificationDelivery.objects.filter(
        preference__scenario__user=user,
        read_at__isnull=True,
    ).update(read_at=timezone.now())
