"""Recovery-email enrollment views; never provide forgotten-password reset."""

from __future__ import annotations

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from apps.accounts.forms import RecoveryEmailEnrollmentForm
from apps.accounts.recovery_email import (
    RecoveryEmailError,
    confirm_recovery_token,
    preview_recovery_token,
    propose_recovery_email,
)
from apps.accounts.views import _profile_context


@login_required
@require_http_methods(["POST"])
def request_recovery_email(request: HttpRequest) -> HttpResponse:
    if not settings.ACCOUNT_EMAIL_VERIFICATION_ENABLED:
        messages.error(request, "Email verification is unavailable.")
        return redirect("profile")
    form = RecoveryEmailEnrollmentForm(request.POST, user=request.user)
    if not form.is_valid():
        return render(
            request,
            "accounts/profile.html",
            _profile_context(request.user, recovery_email_form=form),
            status=422,
        )
    try:
        propose_recovery_email(user=request.user, email=form.cleaned_data["email"])
    except RecoveryEmailError as exc:
        messages.error(request, str(exc))
        return redirect("profile")
    messages.success(request, "Verification link sent. It expires in 30 minutes.")
    return redirect("profile")


@login_required
@require_http_methods(["GET", "POST"])
def confirm_recovery_email(request: HttpRequest, token: str) -> HttpResponse:
    try:
        preview_recovery_token(user=request.user, token=token)
    except RecoveryEmailError:
        messages.error(request, "Verification link invalid or expired.")
        return redirect("profile")

    if request.method == "POST":
        try:
            confirm_recovery_token(user=request.user, token=token)
        except RecoveryEmailError:
            messages.error(request, "Verification link invalid or expired.")
            return redirect("profile")
        messages.success(request, "Recovery email verified.")
        return redirect("profile")
    response = render(request, "accounts/recovery_email_confirm.html")
    response["Referrer-Policy"] = "no-referrer"
    response["Cache-Control"] = "no-store"
    return response
