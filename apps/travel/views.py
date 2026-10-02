from __future__ import annotations

import json
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import OuterRef, Subquery
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from apps.accounts.preferences import recent_history_enabled
from apps.travel.models import (
    FavouritePair,
    RecentConversion,
    SavedScenario,
    SavedScenarioObservation,
)
from apps.travel.services import FavouriteSyncError, serialize_favourite, sync_user_favourites

MAX_SYNC_BODY_BYTES = 16_384


def _pair_url(favourite: FavouritePair, *, swap: bool = False) -> str:
    source_currency = (
        favourite.destination_currency.code if swap else favourite.source_currency.code
    )
    destination_currency = (
        favourite.source_currency.code if swap else favourite.destination_currency.code
    )
    source_country = favourite.destination_country if swap else favourite.source_country
    destination_country = favourite.source_country if swap else favourite.destination_country
    params = {
        "load": "1",
        "source_currency": source_currency,
        "destination_currency": destination_currency,
    }
    if source_country is not None:
        params["source_country"] = source_country.iso2
    if destination_country is not None:
        params["destination_country"] = destination_country.iso2
    return f"{reverse('converter')}?{urlencode(params)}"


def _recent_url(recent: RecentConversion, *, swap: bool = False) -> str:
    source_currency = recent.destination_currency.code if swap else recent.source_currency.code
    destination_currency = recent.source_currency.code if swap else recent.destination_currency.code
    source_country = recent.destination_country if swap else recent.source_country
    destination_country = recent.source_country if swap else recent.destination_country
    params = {
        "convert": "1",
        "amount": recent.input_amount,
        "source_currency": source_currency,
        "destination_currency": destination_currency,
    }
    if source_country is not None:
        params["source_country"] = source_country.iso2
    if destination_country is not None:
        params["destination_country"] = destination_country.iso2
    if recent.rate_mode == RecentConversion.RateMode.HISTORICAL and recent.requested_date:
        params["rate_mode"] = RecentConversion.RateMode.HISTORICAL
        params["requested_date"] = recent.requested_date.isoformat()
    return f"{reverse('converter')}?{urlencode(params)}"


def _comparison_url(destination_country, destination_city=None) -> str:
    if destination_country is None:
        return ""
    token = destination_country.iso2
    if destination_city is not None:
        token = f"{token}:{destination_city.slug}"
    return f"{reverse('destination_comparison')}?{urlencode({'left_destination': token})}"


def _favourite_rows(user) -> list[dict[str, object]]:
    favourites = (
        FavouritePair.objects.filter(user=user)
        .select_related(
            "source_currency",
            "destination_currency",
            "source_country",
            "destination_country",
        )
        .order_by("-updated_at", "-id")
    )
    return [
        {
            "favourite": favourite,
            "use_url": _pair_url(favourite),
            "reverse_url": _pair_url(favourite, swap=True),
            "compare_url": _comparison_url(favourite.destination_country),
        }
        for favourite in favourites
    ]


def _recent_rows(user) -> list[dict[str, object]]:
    recents = (
        RecentConversion.objects.filter(user=user)
        .select_related(
            "source_currency",
            "destination_currency",
            "source_country",
            "destination_country",
        )
        .order_by("-converted_at", "-id")
    )
    return [
        {
            "recent": recent,
            "repeat_url": _recent_url(recent),
            "swap_url": _recent_url(recent, swap=True),
            "compare_url": _comparison_url(recent.destination_country),
        }
        for recent in recents
    ]


def _scenario_rows(user) -> list[dict[str, object]]:
    latest_observation = (
        SavedScenarioObservation.objects.filter(scenario_id=OuterRef("pk"))
        .order_by("-recorded_at", "-id")
        .values("effective_date")[:1]
    )
    scenarios = (
        SavedScenario.objects.filter(user=user)
        .select_related(
            "source_currency",
            "destination_currency",
            "destination_country",
            "destination_city",
        )
        .annotate(latest_effective_date=Subquery(latest_observation))
        .order_by("-updated_at", "-id")
    )
    return [
        {
            "scenario": scenario,
            "latest_effective_date": scenario.latest_effective_date,
            "detail_url": reverse("saved_scenario_detail", args=(scenario.pk,)),
            "compare_url": _comparison_url(
                scenario.destination_country,
                scenario.destination_city,
            ),
        }
        for scenario in scenarios
    ]


@never_cache
@require_GET
def saved_state(request: HttpRequest) -> HttpResponse:
    return render(
        request,
        "travel/saved_state.html",
        {
            "account_scenario_rows": (
                _scenario_rows(request.user) if request.user.is_authenticated else []
            ),
            "account_favourite_rows": (
                _favourite_rows(request.user) if request.user.is_authenticated else []
            ),
            "account_recent_rows": (
                _recent_rows(request.user) if request.user.is_authenticated else []
            ),
            "account_recent_history_enabled": (
                recent_history_enabled(request.user) if request.user.is_authenticated else False
            ),
        },
    )


def _json_error(message: str, *, status: int) -> JsonResponse:
    return JsonResponse(
        {"error": {"code": "invalid_favourites", "message": message}},
        status=status,
    )


@require_POST
def sync_favourites(request: HttpRequest) -> JsonResponse:
    if not request.user.is_authenticated:
        return JsonResponse(
            {
                "error": {
                    "code": "authentication_required",
                    "message": "Sign in to sync saved pairs.",
                }
            },
            status=401,
        )
    if request.content_type != "application/json":
        return _json_error("Content-Type must be application/json.", status=415)

    content_length = request.META.get("CONTENT_LENGTH")
    if content_length:
        try:
            if int(content_length) > MAX_SYNC_BODY_BYTES:
                return _json_error("Saved-pair payload is too large.", status=413)
        except ValueError:
            return _json_error("Invalid Content-Length.", status=400)

    body = request.body
    if len(body) > MAX_SYNC_BODY_BYTES:
        return _json_error("Saved-pair payload is too large.", status=413)

    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _json_error("Request body must contain valid JSON.", status=400)

    if not isinstance(payload, dict) or set(payload) != {"favourites"}:
        return _json_error("Request must contain only a favourites list.", status=400)

    try:
        result = sync_user_favourites(request.user, payload["favourites"])
    except FavouriteSyncError as exc:
        return _json_error(str(exc), status=400)

    return JsonResponse(
        {
            "favourites": [serialize_favourite(item) for item in result.favourites],
            "createdCount": result.created_count,
        }
    )


@login_required
@require_POST
def delete_favourite(request: HttpRequest, favourite_id: int) -> HttpResponse:
    favourite = get_object_or_404(
        FavouritePair,
        pk=favourite_id,
        user=request.user,
    )
    favourite.delete()
    messages.success(request, "Saved pair removed from your account.")
    return redirect("saved_state")


@login_required
@require_POST
def clear_favourites(request: HttpRequest) -> HttpResponse:
    deleted, _ = FavouritePair.objects.filter(user=request.user).delete()
    if deleted:
        messages.success(request, "All account-saved pairs were removed.")
    else:
        messages.info(request, "There were no account-saved pairs to remove.")
    return redirect("saved_state")


@login_required
@require_POST
def delete_recent_conversion(request: HttpRequest, recent_id: int) -> HttpResponse:
    recent = get_object_or_404(
        RecentConversion,
        pk=recent_id,
        user=request.user,
    )
    recent.delete()
    messages.success(request, "Recent conversion removed from your account.")
    return redirect("saved_state")


@login_required
@require_POST
def clear_recent_conversions(request: HttpRequest) -> HttpResponse:
    deleted, _ = RecentConversion.objects.filter(user=request.user).delete()
    if deleted:
        messages.success(request, "All account recent history was removed.")
    else:
        messages.info(request, "There was no account recent history to remove.")
    return redirect("saved_state")
