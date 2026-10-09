from __future__ import annotations

import json
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import OuterRef, Subquery
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from apps.accounts.preferences import recent_history_enabled
from apps.countries.models import CountryCurrency, Currency
from apps.exchange.comparison_snapshot import (
    SavedComparisonTokenError,
    load_saved_comparison_token,
)
from apps.travel.models import (
    FavouritePair,
    RecentConversion,
    SavedComparison,
    SavedCurrency,
    SavedPlace,
    SavedScenario,
    SavedScenarioObservation,
)
from apps.travel.personalization import (
    SavedComparisonPersistenceError,
    SavedCurrencySyncError,
    SavedPlaceSyncError,
    comparison_reopen_params,
    persist_saved_comparison,
    sync_user_saved_currencies,
    sync_user_saved_places,
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
    recents = tuple(
        RecentConversion.objects.filter(user=user)
        .select_related(
            "source_currency",
            "destination_currency",
            "source_country",
            "destination_country",
        )
        .order_by("-converted_at", "-id")
    )
    # One current-currency lookup for all history rows. Do not presume that
    # a historical destination or an archived source currency is still usable.
    current_destinations = set(
        CountryCurrency.objects.current(timezone.localdate())
        .primary()
        .filter(
            country_id__in={
                row.destination_country_id for row in recents if row.destination_country_id
            },
            country__is_active=True,
            currency__is_active=True,
        )
        .values_list("country_id", flat=True)
    )

    def plan_url(row: RecentConversion) -> str:
        if row.destination_country_id not in current_destinations:
            return ""
        params = {"destination": row.destination_country.iso2, "from_history": "1"}
        if row.source_currency.is_active:
            params["source_currency"] = row.source_currency.code
            params["amount"] = row.input_amount
        return f"{reverse('destination_mode')}?{urlencode(params)}"

    return [
        {
            "recent": recent,
            "repeat_url": _recent_url(recent),
            "swap_url": _recent_url(recent, swap=True),
            "compare_url": _comparison_url(recent.destination_country),
            "plan_url": plan_url(recent),
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


def _saved_currency_rows(user) -> list[dict[str, object]]:
    saved = tuple(
        SavedCurrency.objects.filter(user=user)
        .select_related("currency")
        .order_by("-updated_at", "-id")
    )
    rows: list[dict[str, object]] = []
    for item in saved:
        code = item.currency.code
        rows.append(
            {
                "saved": item,
                "available": item.currency.is_active,
                "source_url": (
                    f"{reverse('converter')}?{urlencode({'load': '1', 'source_currency': code})}"
                    if item.currency.is_active
                    else ""
                ),
                "destination_url": (
                    f"{reverse('converter')}?{urlencode({'load': '1', 'destination_currency': code})}"
                    if item.currency.is_active
                    else ""
                ),
            }
        )
    return rows


def _saved_place_rows(user) -> list[dict[str, object]]:
    places = tuple(
        SavedPlace.objects.filter(user=user)
        .select_related("country", "city")
        .order_by("-updated_at", "-id")
    )
    current_links = {
        link.country_id: link
        for link in CountryCurrency.objects.current(timezone.localdate())
        .primary()
        .filter(country_id__in={place.country_id for place in places})
        .select_related("currency")
    }

    rows: list[dict[str, object]] = []
    for place in places:
        link = current_links.get(place.country_id)
        available = (
            place.country.is_active
            and (place.city is None or place.city.is_active)
            and link is not None
            and link.currency.is_active
        )
        token = place.token
        converter_url = ""
        if available and link is not None:
            params = {
                "load": "1",
                "destination_country": place.country.iso2,
                "destination_currency": link.currency.code,
            }
            if place.city is not None:
                params["destination_city_slug"] = place.city.slug
            converter_url = f"{reverse('converter')}?{urlencode(params)}"

        rows.append(
            {
                "place": place,
                "token": token,
                "available": available,
                "currency_code": link.currency.code if link is not None else "",
                "converter_url": converter_url,
                "budget_url": (
                    f"{reverse('destination_mode')}?{urlencode({'destination': token})}"
                    if available
                    else ""
                ),
                "compare_url": (
                    f"{reverse('destination_comparison')}?{urlencode({'left_destination': token})}"
                    if available
                    else ""
                ),
                "profile_url": (
                    reverse(
                        "city_money_profile",
                        kwargs={
                            "country_code": place.country.iso2,
                            "city_slug": place.city.slug,
                        },
                    )
                    if available and place.city is not None
                    else ""
                ),
            }
        )
    return rows


def _saved_comparison_rows(user) -> list[dict[str, object]]:
    comparisons = tuple(
        SavedComparison.objects.filter(user=user)
        .select_related(
            "source_currency",
            "left_country",
            "left_city",
            "right_country",
            "right_city",
        )
        .prefetch_related("budget_items")
        .order_by("-updated_at", "-id")
    )
    current_country_ids = {comparison.left_country_id for comparison in comparisons} | {
        comparison.right_country_id for comparison in comparisons
    }
    current_country_ids.discard(None)
    current_country_ids = set(current_country_ids)
    current_links = {
        country_id
        for country_id in CountryCurrency.objects.current(timezone.localdate())
        .primary()
        .filter(country_id__in=current_country_ids)
        .values_list("country_id", flat=True)
    }

    rows: list[dict[str, object]] = []
    for comparison in comparisons:
        available = (
            comparison.source_currency.is_active
            and comparison.left_country.is_active
            and comparison.right_country.is_active
            and comparison.left_country_id in current_links
            and comparison.right_country_id in current_links
            and (comparison.left_city is None or comparison.left_city.is_active)
            and (comparison.right_city is None or comparison.right_city.is_active)
        )
        params = comparison_reopen_params(comparison)
        rows.append(
            {
                "comparison": comparison,
                "available": available,
                "reopen_url": (
                    f"{reverse('destination_comparison')}?{urlencode(params)}" if available else ""
                ),
                "recheck_fields": params if available else {},
                "left_label": (
                    f"{comparison.left_city.name}, {comparison.left_country.name}"
                    if comparison.left_city is not None
                    else comparison.left_country.name
                ),
                "right_label": (
                    f"{comparison.right_city.name}, {comparison.right_country.name}"
                    if comparison.right_city is not None
                    else comparison.right_country.name
                ),
                "budget_items": tuple(comparison.budget_items.all()),
            }
        )
    return rows


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
            "account_saved_currency_rows": (
                _saved_currency_rows(request.user) if request.user.is_authenticated else []
            ),
            "currency_choices": (
                Currency.objects.filter(is_active=True).order_by("code")
                if request.user.is_authenticated
                else ()
            ),
            "account_saved_place_rows": (
                _saved_place_rows(request.user) if request.user.is_authenticated else []
            ),
            "account_saved_comparison_rows": (
                _saved_comparison_rows(request.user) if request.user.is_authenticated else []
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


@never_cache
@require_GET
def saved_currency_options(request: HttpRequest) -> JsonResponse:
    currencies = list(
        Currency.objects.filter(is_active=True).order_by("code").values("code", "name")[:300]
    )
    return JsonResponse({"currencies": currencies})


def _currency_json_error(message: str, *, status: int) -> JsonResponse:
    return JsonResponse(
        {"error": {"code": "invalid_currencies", "message": message}},
        status=status,
    )


@never_cache
@require_GET
def saved_currencies_status(request: HttpRequest) -> JsonResponse:
    if not request.user.is_authenticated:
        return JsonResponse(
            {
                "error": {
                    "code": "authentication_required",
                    "message": "Sign in to read account-saved currencies.",
                }
            },
            status=401,
        )
    codes = list(
        SavedCurrency.objects.filter(user=request.user, currency__is_active=True)
        .order_by("id")
        .values_list("currency__code", flat=True)
    )
    return JsonResponse({"codes": codes})


@require_POST
def sync_saved_currencies(request: HttpRequest) -> JsonResponse:
    if not request.user.is_authenticated:
        return JsonResponse(
            {
                "error": {
                    "code": "authentication_required",
                    "message": "Sign in to save currencies to your account.",
                }
            },
            status=401,
        )
    if request.content_type != "application/json":
        return _currency_json_error("Content-Type must be application/json.", status=415)

    content_length = request.META.get("CONTENT_LENGTH")
    if content_length:
        try:
            if int(content_length) > MAX_SYNC_BODY_BYTES:
                return _currency_json_error("Saved-currency payload is too large.", status=413)
        except ValueError:
            return _currency_json_error("Invalid Content-Length.", status=400)

    body = request.body
    if len(body) > MAX_SYNC_BODY_BYTES:
        return _currency_json_error("Saved-currency payload is too large.", status=413)
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _currency_json_error("Request body must contain valid JSON.", status=400)
    if not isinstance(payload, dict) or set(payload) != {"currencies"}:
        return _currency_json_error("Request must contain only a currencies list.", status=400)

    try:
        result = sync_user_saved_currencies(request.user, payload["currencies"])
    except SavedCurrencySyncError as exc:
        return _currency_json_error(str(exc), status=400)
    return JsonResponse(
        {
            "createdCount": result.created_count,
            "savedCount": len(result.currencies),
        }
    )


@login_required
@require_POST
def save_currency(request: HttpRequest) -> HttpResponse:
    code = str(request.POST.get("currency_code") or "")
    try:
        result = sync_user_saved_currencies(request.user, [code])
    except SavedCurrencySyncError:
        messages.error(request, "This currency could not be saved safely.")
    else:
        if result.created_count:
            messages.success(request, "Currency saved to your account.")
        else:
            messages.info(request, "This currency is already saved to your account.")
    return redirect("saved_state")


@login_required
@require_POST
def delete_saved_currency(request: HttpRequest, currency_id: int) -> HttpResponse:
    saved = get_object_or_404(SavedCurrency, pk=currency_id, user=request.user)
    code = saved.currency.code
    saved.delete()
    messages.success(request, f"{code} removed from saved currencies.")
    return redirect("saved_state")


@login_required
@require_POST
def clear_saved_currencies(request: HttpRequest) -> HttpResponse:
    SavedCurrency.objects.filter(user=request.user).delete()
    messages.success(request, "Saved currencies cleared.")
    return redirect("saved_state")


def _place_json_error(message: str, *, status: int) -> JsonResponse:
    return JsonResponse(
        {"error": {"code": "invalid_places", "message": message}},
        status=status,
    )


@never_cache
@require_GET
def saved_places_status(request: HttpRequest) -> JsonResponse:
    if not request.user.is_authenticated:
        return JsonResponse(
            {
                "error": {
                    "code": "authentication_required",
                    "message": "Sign in to read account-saved places.",
                }
            },
            status=401,
        )

    tokens = [
        place.token
        for place in SavedPlace.objects.filter(user=request.user)
        .select_related("country", "city")
        .order_by("id")
    ]
    return JsonResponse({"tokens": tokens})


@require_POST
def sync_saved_places(request: HttpRequest) -> JsonResponse:
    if not request.user.is_authenticated:
        return JsonResponse(
            {
                "error": {
                    "code": "authentication_required",
                    "message": "Sign in to save places to your account.",
                }
            },
            status=401,
        )
    if request.content_type != "application/json":
        return _place_json_error("Content-Type must be application/json.", status=415)

    content_length = request.META.get("CONTENT_LENGTH")
    if content_length:
        try:
            if int(content_length) > MAX_SYNC_BODY_BYTES:
                return _place_json_error("Saved-place payload is too large.", status=413)
        except ValueError:
            return _place_json_error("Invalid Content-Length.", status=400)

    body = request.body
    if len(body) > MAX_SYNC_BODY_BYTES:
        return _place_json_error("Saved-place payload is too large.", status=413)

    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _place_json_error("Request body must contain valid JSON.", status=400)

    if not isinstance(payload, dict) or set(payload) != {"places"}:
        return _place_json_error("Request must contain only a places list.", status=400)

    try:
        result = sync_user_saved_places(request.user, payload["places"])
    except SavedPlaceSyncError as exc:
        return _place_json_error(str(exc), status=400)

    return JsonResponse(
        {
            "createdCount": result.created_count,
            "savedCount": len(result.places),
        }
    )


@login_required
@require_POST
def save_place(request: HttpRequest) -> HttpResponse:
    country_code = str(request.POST.get("country_code") or "")
    city_slug = str(request.POST.get("city_slug") or "")
    try:
        result = sync_user_saved_places(
            request.user,
            [{"countryCode": country_code, "citySlug": city_slug}],
        )
    except SavedPlaceSyncError:
        messages.error(
            request,
            "This place could not be saved safely. Refresh Explore and try again.",
        )
    else:
        if result.created_count:
            messages.success(request, "Place saved to your account.")
        else:
            messages.info(request, "This place is already saved to your account.")
    return redirect("explore")


@login_required
@require_POST
def delete_saved_place(request: HttpRequest, place_id: int) -> HttpResponse:
    place = get_object_or_404(SavedPlace, pk=place_id, user=request.user)
    place.delete()
    messages.success(request, "Saved place removed from your account.")
    return redirect("saved_state")


@login_required
@require_POST
def clear_saved_places(request: HttpRequest) -> HttpResponse:
    deleted, _ = SavedPlace.objects.filter(user=request.user).delete()
    if deleted:
        messages.success(request, "All account-saved places were removed.")
    else:
        messages.info(request, "There were no account-saved places to remove.")
    return redirect("saved_state")


@login_required
@require_POST
def save_comparison(request: HttpRequest) -> HttpResponse:
    token = str(request.POST.get("comparison_save_token") or "")
    try:
        value = load_saved_comparison_token(token)
        result = persist_saved_comparison(request.user, value)
    except (SavedComparisonTokenError, SavedComparisonPersistenceError):
        messages.error(
            request,
            "This comparison could not be saved safely. Re-run it before saving.",
        )
        return redirect("destination_comparison")

    if result.created:
        messages.success(request, "Comparison saved to your account.")
    else:
        messages.info(request, "This comparison is already saved to your account.")
    return redirect("saved_state")


@login_required
@require_POST
def delete_saved_comparison(request: HttpRequest, comparison_id: int) -> HttpResponse:
    comparison = get_object_or_404(
        SavedComparison,
        pk=comparison_id,
        user=request.user,
    )
    comparison.delete()
    messages.success(request, "Saved comparison removed from your account.")
    return redirect("saved_state")


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
