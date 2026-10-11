"""Sign-in view with bounded credential-attempt throttling."""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth.views import LoginView

from apps.accounts.auth_throttle import (
    AuthThrottleUnavailable,
    login_allowed,
    note_login_failure,
    note_login_success,
)
from apps.accounts.forms import QuietAuthenticationForm


class AccountLoginView(LoginView):
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["email_recovery_enabled"] = settings.ACCOUNT_EMAIL_VERIFICATION_ENABLED
        return context

    def _guarded_response(self, *, status: int):
        form = QuietAuthenticationForm(request=self.request)
        context = self.get_context_data(form=form)
        context["auth_guard_error"] = (
            "Too many sign-in attempts. Please try again later."
            if status == 429
            else "Sign-in is temporarily unavailable. Please try again later."
        )
        response = self.render_to_response(context, status=status)
        response["Cache-Control"] = "no-store"
        if status == 429:
            response["Retry-After"] = "900"
        return response

    def post(self, request, *args, **kwargs):
        self._guarded_login_identity = request.POST.get("username", "")
        self._guarded_client_address = request.META.get("REMOTE_ADDR", "")
        try:
            permitted = login_allowed(
                username=self._guarded_login_identity,
                remote_addr=self._guarded_client_address,
            )
        except AuthThrottleUnavailable:
            return self._guarded_response(status=503)
        if not permitted:
            return self._guarded_response(status=429)
        return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        try:
            note_login_failure(
                username=self._guarded_login_identity,
                remote_addr=self._guarded_client_address,
            )
        except AuthThrottleUnavailable:
            return self._guarded_response(status=503)
        return super().form_invalid(form)

    def form_valid(self, form):
        try:
            note_login_success(username=self._guarded_login_identity)
        except AuthThrottleUnavailable:
            # Do not issue an authenticated session if throttle state failed.
            return self._guarded_response(status=503)
        return super().form_valid(form)
