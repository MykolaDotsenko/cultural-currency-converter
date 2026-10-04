from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from apps.travel.models import SavedScenario
from apps.travel import notification_delivery
from apps.travel.notification_preferences import (
    ScenarioNotificationPreferenceError,
    delete_scenario_notification_preference,
    upsert_scenario_notification_preference,
)


@login_required
@never_cache
@require_GET
def notification_inbox(request: HttpRequest) -> HttpResponse:
    deliveries = tuple(notification_delivery.notifications_for_user(request.user))
    return render(
        request,
        "travel/notifications.html",
        {
            "deliveries": deliveries,
            "unread_count": sum(1 for item in deliveries if item.read_at is None),
        },
    )


@login_required
@require_POST
def configure_saved_scenario_notification(
    request: HttpRequest,
    scenario_id: int,
) -> HttpResponse:
    scenario = get_object_or_404(SavedScenario, pk=scenario_id, user=request.user)
    try:
        upsert_scenario_notification_preference(
            request.user,
            scenario_id=scenario.pk,
            notification_type=str(request.POST.get("notification_type") or ""),
            enabled=request.POST.get("enabled") == "1",
            timezone_name=str(request.POST.get("timezone") or ""),
            cadence=str(request.POST.get("cadence") or ""),
            rate_change_threshold_percent=request.POST.get("rate_change_threshold_percent"),
        )
    except ScenarioNotificationPreferenceError as exc:
        messages.error(request, f"Could not save notification: {exc}")
    else:
        messages.success(request, "Notification preference saved.")
    return redirect("saved_scenario_detail", scenario_id=scenario.pk)


@login_required
@require_POST
def delete_saved_scenario_notification(
    request: HttpRequest,
    scenario_id: int,
    notification_type: str,
) -> HttpResponse:
    scenario = get_object_or_404(SavedScenario, pk=scenario_id, user=request.user)
    try:
        deleted = delete_scenario_notification_preference(
            request.user,
            scenario_id=scenario.pk,
            notification_type=notification_type,
        )
    except ScenarioNotificationPreferenceError as exc:
        messages.error(request, f"Could not remove notification: {exc}")
    else:
        if deleted:
            messages.success(request, "Notification preference removed.")
    return redirect("saved_scenario_detail", scenario_id=scenario.pk)


@login_required
@require_POST
def mark_notification_read(request: HttpRequest, delivery_id: int) -> HttpResponse:
    notification_delivery.mark_notification_read(request.user, delivery_id=delivery_id)
    return redirect("notification_inbox")


@login_required
@require_POST
def mark_all_notifications_read(request: HttpRequest) -> HttpResponse:
    notification_delivery.mark_all_notifications_read(request.user)
    return redirect("notification_inbox")
