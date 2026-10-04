from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db import transaction

from apps.accounts.models import AccountPreferences
from apps.countries.models import Currency


def recent_history_enabled(user) -> bool:
    return bool(
        user.is_authenticated
        and AccountPreferences.objects.filter(
            user=user,
            sync_recent_history=True,
        ).exists()
    )


def set_recent_history_enabled(user, *, enabled: bool) -> AccountPreferences:
    if not user.is_authenticated:
        raise ValueError("Authentication is required.")

    user_model = get_user_model()
    with transaction.atomic():
        user_model.objects.select_for_update().get(pk=user.pk)
        preferences, _ = AccountPreferences.objects.update_or_create(
            user=user,
            defaults={"sync_recent_history": enabled},
        )
    return preferences


def home_currency_code(user) -> str:
    if not user.is_authenticated:
        return ""
    return (
        AccountPreferences.objects.filter(user=user, home_currency__is_active=True)
        .values_list("home_currency__code", flat=True)
        .first()
        or ""
    )


def set_home_currency(user, *, currency_code: str) -> AccountPreferences:
    if not user.is_authenticated:
        raise ValueError("Authentication is required.")

    code = currency_code.upper().strip()
    currency = None
    if code:
        try:
            currency = Currency.objects.get(code=code, is_active=True)
        except Currency.DoesNotExist as exc:
            raise ValueError("Home currency must be active.") from exc

    user_model = get_user_model()
    with transaction.atomic():
        user_model.objects.select_for_update().get(pk=user.pk)
        preferences, _ = AccountPreferences.objects.update_or_create(
            user=user,
            defaults={"home_currency": currency},
        )
    return preferences
