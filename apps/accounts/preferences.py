from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db import transaction

from apps.accounts.models import AccountPreferences, AnswerDetail, PreferredLanguage, TravelStyle
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


def set_explanation_preferences(
    user,
    *,
    preferred_language: str,
    answer_detail: str,
    travel_style: str,
) -> AccountPreferences:
    if not user.is_authenticated:
        raise ValueError("Authentication is required.")
    if preferred_language not in PreferredLanguage.values:
        raise ValueError("Preferred language is invalid.")
    if answer_detail not in AnswerDetail.values:
        raise ValueError("Answer detail is invalid.")
    if travel_style not in TravelStyle.values:
        raise ValueError("Travel style is invalid.")

    user_model = get_user_model()
    with transaction.atomic():
        user_model.objects.select_for_update().get(pk=user.pk)
        preferences, _ = AccountPreferences.objects.update_or_create(
            user=user,
            defaults={
                "preferred_language": preferred_language,
                "answer_detail": answer_detail,
                "travel_style": travel_style,
            },
        )
    return preferences
