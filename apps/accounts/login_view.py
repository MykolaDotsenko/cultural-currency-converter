"""Sign-in view with opt-in verified-email recovery affordance."""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth.views import LoginView


class AccountLoginView(LoginView):
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["email_recovery_enabled"] = settings.ACCOUNT_EMAIL_VERIFICATION_ENABLED
        return context
