from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods

from apps.accounts.forms import (
    DeleteAccountForm,
    HomeCurrencyPreferenceForm,
    PreTripNotificationPreferenceForm,
    SignUpForm,
)
from apps.accounts.notification_preferences import (
    NotificationPreferenceError,
    delete_pre_trip_preference,
    pre_trip_preference_for_user,
    save_pre_trip_preference,
)
from apps.accounts.preferences import (
    home_currency_code,
    recent_history_enabled,
    set_home_currency,
    set_recent_history_enabled,
)
from apps.exchange.budget_presets import (
    budget_presets_for_user,
    delete_budget_preset,
)
from apps.exchange.fee_profiles import (
    delete_payment_fee_profile,
    payment_fee_profiles_for_user,
)


def _safe_next(request: HttpRequest) -> str:
    candidate = request.POST.get("next") or request.GET.get("next") or ""
    if not candidate:
        return ""
    allowed = {request.get_host()}
    return (
        candidate
        if url_has_allowed_host_and_scheme(
            candidate,
            allowed_hosts=allowed,
            require_https=request.is_secure(),
        )
        else ""
    )


@require_http_methods(["GET", "POST"])
def signup(request: HttpRequest) -> HttpResponse:
    next_url = _safe_next(request)
    if request.user.is_authenticated:
        return redirect(next_url or reverse("profile"))

    form = SignUpForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(
            request,
            "Account created. Saved pairs can now sync across signed-in devices.",
        )
        return redirect(next_url or reverse("saved_state"))

    return render(
        request,
        "accounts/signup.html",
        {"form": form, "next": next_url},
    )


def _profile_context(
    user,
    *,
    home_currency_form: HomeCurrencyPreferenceForm | None = None,
    home_currency: str | None = None,
    pre_trip_notification_form: PreTripNotificationPreferenceForm | None = None,
) -> dict[str, object]:
    current_home_currency = home_currency if home_currency is not None else home_currency_code(user)
    pre_trip_preference = pre_trip_preference_for_user(user)
    return {
        "recent_history_enabled": recent_history_enabled(user),
        "home_currency_form": home_currency_form
        or HomeCurrencyPreferenceForm(current_code=current_home_currency),
        "home_currency_code": current_home_currency,
        "payment_fee_profiles": payment_fee_profiles_for_user(user),
        "budget_presets": budget_presets_for_user(user),
        "pre_trip_notification_preference": pre_trip_preference,
        "pre_trip_notification_form": pre_trip_notification_form
        or PreTripNotificationPreferenceForm(preference=pre_trip_preference),
    }


@login_required
@require_http_methods(["GET"])
def profile(request: HttpRequest) -> HttpResponse:
    return render(
        request,
        "accounts/profile.html",
        _profile_context(request.user),
    )


@login_required
@require_http_methods(["POST"])
def update_home_currency_preference(request: HttpRequest) -> HttpResponse:
    current_code = home_currency_code(request.user)
    form = HomeCurrencyPreferenceForm(
        request.POST,
        current_code=current_code,
    )
    if not form.is_valid():
        messages.error(request, "Home currency preference was not changed.")
        return render(
            request,
            "accounts/profile.html",
            _profile_context(
                request.user,
                home_currency_form=form,
                home_currency=current_code,
            ),
            status=422,
        )

    code = form.cleaned_data["home_currency"]
    set_home_currency(request.user, currency_code=code)
    if code:
        messages.success(request, f"{code} is now your default home currency.")
    else:
        messages.success(request, "Saved home currency default was cleared.")
    return redirect("profile")


@login_required
@require_http_methods(["POST"])
def update_recent_history_preference(request: HttpRequest) -> HttpResponse:
    action = request.POST.get("action", "")
    if action not in {"enable", "disable"}:
        messages.error(request, "Recent-history preference was not changed.")
        return redirect("profile")

    enabled = action == "enable"
    set_recent_history_enabled(request.user, enabled=enabled)
    if enabled:
        messages.success(
            request,
            "Cross-device recent history is on. Only future successful conversions are stored.",
        )
    else:
        messages.success(
            request,
            "Cross-device recent history is off. Existing account history was kept.",
        )
    return redirect("profile")


@login_required
@require_http_methods(["POST"])
def update_pre_trip_notification_preference(request: HttpRequest) -> HttpResponse:
    current_preference = pre_trip_preference_for_user(request.user)
    form = PreTripNotificationPreferenceForm(
        request.POST,
        preference=current_preference,
    )
    if not form.is_valid():
        messages.error(request, "Pre-trip reminder preference was not changed.")
        return render(
            request,
            "accounts/profile.html",
            _profile_context(
                request.user,
                pre_trip_notification_form=form,
            ),
            status=422,
        )

    try:
        preference = save_pre_trip_preference(
            request.user,
            enabled=form.cleaned_data["enabled"],
            timezone_name=form.cleaned_data["timezone_name"],
            cadence=form.cleaned_data["cadence"],
            lead_days=form.cleaned_data["lead_days"],
            delivery_channel=form.cleaned_data["delivery_channel"],
        )
    except NotificationPreferenceError as exc:
        form.add_error(None, str(exc))
        messages.error(request, "Pre-trip reminder preference was not changed.")
        return render(
            request,
            "accounts/profile.html",
            _profile_context(
                request.user,
                pre_trip_notification_form=form,
            ),
            status=422,
        )

    if preference is not None and preference.enabled:
        messages.success(
            request,
            "Pre-trip reminders are on. Delivery is in-app only and never re-checks FX automatically.",
        )
    else:
        messages.success(request, "Pre-trip reminders are off.")
    return redirect("profile")


@login_required
@require_http_methods(["POST"])
def delete_pre_trip_notification_preference(request: HttpRequest) -> HttpResponse:
    if delete_pre_trip_preference(request.user):
        messages.success(request, "Pre-trip reminder configuration deleted.")
    else:
        messages.info(request, "No pre-trip reminder configuration was stored.")
    return redirect("profile")


@login_required
@require_http_methods(["POST"])
def delete_budget_preset_view(request: HttpRequest, preset_id: int) -> HttpResponse:
    if delete_budget_preset(request.user, preset_id=preset_id):
        messages.success(request, "Budget preset deleted.")
    else:
        messages.info(request, "That budget preset is no longer available.")
    return redirect("profile")


@login_required
@require_http_methods(["POST"])
def delete_fee_profile(request: HttpRequest, profile_id: int) -> HttpResponse:
    if delete_payment_fee_profile(request.user, profile_id=profile_id):
        messages.success(request, "Payment fee profile deleted.")
    else:
        messages.info(request, "That payment fee profile is no longer available.")
    return redirect("profile")


@login_required
@require_http_methods(["GET", "POST"])
def delete_account(request: HttpRequest) -> HttpResponse:
    form = DeleteAccountForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        user = request.user
        logout(request)
        user.delete()
        messages.success(request, "Your account and account-owned saved data were deleted.")
        return redirect("converter")

    return render(request, "accounts/delete_account.html", {"form": form})
