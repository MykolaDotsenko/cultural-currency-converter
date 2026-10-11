"""Account recovery web endpoints with generic responses and token redaction."""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import SetPasswordForm
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from apps.accounts.forms import ForgottenPasswordRequestForm
from apps.accounts.models import VerifiedRecoveryEmail
from apps.accounts.password_reset import (
    request_verified_password_reset,
    verified_password_token_generator,
)


def _private_response(response: HttpResponse) -> HttpResponse:
    response["Cache-Control"] = "no-store"
    response["Referrer-Policy"] = "no-referrer"
    return response


def _recoverable_user(uidb64: str, token: str):
    if (
        not settings.ACCOUNT_EMAIL_VERIFICATION_ENABLED
        or len(uidb64) > 64
        or len(token) > 160
    ):
        return None
    try:
        pk = int(force_str(urlsafe_base64_decode(uidb64)))
        if pk <= 0:
            return None
    except (ValueError, TypeError, UnicodeDecodeError, OverflowError):
        return None
    user = get_user_model().objects.filter(pk=pk, is_active=True).first()
    if user is None or not user.has_usable_password():
        return None
    if not VerifiedRecoveryEmail.objects.filter(
        user=user, verified_at__isnull=False
    ).exists():
        return None
    if not verified_password_token_generator.check_token(user, token):
        return None
    return user


@require_http_methods(["GET", "POST"])
@sensitive_post_parameters("email")
def password_reset_request(request: HttpRequest) -> HttpResponse:
    enabled = settings.ACCOUNT_EMAIL_VERIFICATION_ENABLED
    form = ForgottenPasswordRequestForm(request.POST or None)
    if request.method == "POST":
        if enabled and form.is_valid():
            request_verified_password_reset(
                email=form.cleaned_data["email"],
                remote_address=request.META.get("REMOTE_ADDR", ""),
            )
            return redirect("password_reset_sent")
        if not enabled:
            return redirect("password_reset_sent")
    return _private_response(
        render(
            request,
            "accounts/password_reset_request.html",
            {"form": form, "available": enabled},
        )
    )


@require_http_methods(["GET"])
def password_reset_sent(request: HttpRequest) -> HttpResponse:
    return _private_response(render(request, "accounts/password_reset_sent.html"))


@require_http_methods(["GET", "POST"])
@sensitive_post_parameters("new_password1", "new_password2")
def password_reset_confirm(
    request: HttpRequest, uidb64: str, token: str
) -> HttpResponse:
    user = _recoverable_user(uidb64, token)
    if request.method == "POST" and user is not None:
        # Two concurrent reset submissions must never both succeed.
        with transaction.atomic():
            user = get_user_model().objects.select_for_update().get(pk=user.pk)
            valid = _recoverable_user(uidb64, token)
            if valid is not None:
                form = SetPasswordForm(user, request.POST)
                if form.is_valid():
                    form.save()
                    return redirect("password_reset_complete")
    elif user is not None:
        form = SetPasswordForm(user)
    if user is None or (request.method == "POST" and _recoverable_user(uidb64, token) is None):
        form = None
    if form is not None:
        for field in form.fields.values():
            field.widget.attrs["class"] = "qa-text-input"
    return _private_response(
        render(
            request,
            "accounts/password_reset_confirm.html",
            {"form": form, "valid_link": form is not None},
        )
    )


@require_http_methods(["GET"])
def password_reset_complete(request: HttpRequest) -> HttpResponse:
    return _private_response(render(request, "accounts/password_reset_complete.html"))
