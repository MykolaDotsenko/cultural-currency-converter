from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction

from apps.accounts.models import PaymentFeeProfile
from apps.countries.models import Currency
from apps.exchange.payment_estimate import (
    MAX_FX_MARKUP_PERCENT,
    PaymentEstimateAssumptions,
)

MAX_PAYMENT_FEE_PROFILES = 12
MAX_PROFILE_FIXED_FEE = Decimal("1000000000")


class PaymentFeeProfileError(ValueError):
    """Raised when reusable payment assumptions violate the profile contract."""


def payment_fee_profiles_for_user(user) -> tuple[PaymentFeeProfile, ...]:
    if not user.is_authenticated:
        return ()

    return tuple(
        PaymentFeeProfile.objects.filter(user=user)
        .select_related("source_currency", "destination_currency")
        .order_by("name", "id")
    )


def fee_profiles_for_pair(
    user,
    *,
    source_currency_code: str,
    destination_currency_code: str,
) -> tuple[PaymentFeeProfile, ...]:
    if not user.is_authenticated:
        return ()

    return tuple(
        PaymentFeeProfile.objects.filter(
            user=user,
            source_currency__code=source_currency_code.upper(),
            source_currency__is_active=True,
            destination_currency__code=destination_currency_code.upper(),
            destination_currency__is_active=True,
        )
        .select_related("source_currency", "destination_currency")
        .order_by("name", "id")
    )


def fee_profile_for_pair(
    user,
    *,
    profile_id: int,
    source_currency_code: str,
    destination_currency_code: str,
) -> PaymentFeeProfile:
    if not user.is_authenticated:
        raise PaymentFeeProfileError("Authentication is required to use a saved fee profile.")

    try:
        return PaymentFeeProfile.objects.select_related(
            "source_currency",
            "destination_currency",
        ).get(
            pk=profile_id,
            user=user,
            source_currency__code=source_currency_code.upper(),
            source_currency__is_active=True,
            destination_currency__code=destination_currency_code.upper(),
            destination_currency__is_active=True,
        )
    except PaymentFeeProfile.DoesNotExist as exc:
        raise PaymentFeeProfileError(
            "This saved fee profile is unavailable for the current currency pair."
        ) from exc


def upsert_payment_fee_profile(
    user,
    *,
    name: str,
    source_currency: Currency,
    destination_currency: Currency,
    assumptions: PaymentEstimateAssumptions,
) -> PaymentFeeProfile:
    if not user.is_authenticated:
        raise PaymentFeeProfileError("Authentication is required to save a fee profile.")

    normalized_name = " ".join(name.split())
    if not normalized_name:
        raise PaymentFeeProfileError("Enter a name for this fee profile.")
    if len(normalized_name) > 80:
        raise PaymentFeeProfileError("Fee profile name must be 80 characters or fewer.")
    if not source_currency.is_active or not destination_currency.is_active:
        raise PaymentFeeProfileError("Fee profiles require active currencies.")
    if source_currency.pk == destination_currency.pk:
        raise PaymentFeeProfileError("Fee profiles require two different currencies.")
    _validate_assumptions(assumptions)
    _validate_fee_precision(
        assumptions.source_fixed_fee,
        minor_units=source_currency.minor_units,
        label=f"Source fixed fee in {source_currency.code}",
    )
    _validate_fee_precision(
        assumptions.destination_fixed_fee,
        minor_units=destination_currency.minor_units,
        label=f"Destination fixed fee in {destination_currency.code}",
    )

    user_model = get_user_model()
    with transaction.atomic():
        user_model.objects.select_for_update().get(pk=user.pk)
        existing = PaymentFeeProfile.objects.filter(
            user=user,
            name=normalized_name,
        ).first()
        if existing is None:
            if PaymentFeeProfile.objects.filter(user=user).count() >= MAX_PAYMENT_FEE_PROFILES:
                raise PaymentFeeProfileError(
                    f"You can save at most {MAX_PAYMENT_FEE_PROFILES} payment fee profiles."
                )
            profile = PaymentFeeProfile(user=user, name=normalized_name)
        else:
            profile = existing

        profile.source_currency = source_currency
        profile.destination_currency = destination_currency
        profile.fx_markup_percent = assumptions.fx_markup_percent
        profile.source_fixed_fee = assumptions.source_fixed_fee
        profile.destination_fixed_fee = assumptions.destination_fixed_fee
        try:
            profile.full_clean()
        except ValidationError as exc:
            raise PaymentFeeProfileError(_validation_message(exc)) from exc
        profile.save()
        return profile


def delete_payment_fee_profile(user, *, profile_id: int) -> bool:
    if not user.is_authenticated:
        raise PaymentFeeProfileError("Authentication is required to delete a fee profile.")

    deleted, _ = PaymentFeeProfile.objects.filter(pk=profile_id, user=user).delete()
    return bool(deleted)


def _validate_assumptions(assumptions: PaymentEstimateAssumptions) -> None:
    values = (
        ("FX markup", assumptions.fx_markup_percent, MAX_FX_MARKUP_PERCENT),
        ("Source fixed fee", assumptions.source_fixed_fee, MAX_PROFILE_FIXED_FEE),
        (
            "Destination fixed fee",
            assumptions.destination_fixed_fee,
            MAX_PROFILE_FIXED_FEE,
        ),
    )
    for label, value, upper_bound in values:
        if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
            raise PaymentFeeProfileError(f"{label} must be a finite non-negative Decimal.")
        if value > upper_bound:
            raise PaymentFeeProfileError(f"{label} exceeds the supported profile limit.")


def _validate_fee_precision(value: Decimal, *, minor_units: int, label: str) -> None:
    quantum = Decimal(1).scaleb(-minor_units)
    if value != value.quantize(quantum):
        unit_label = "decimal place" if minor_units == 1 else "decimal places"
        raise PaymentFeeProfileError(f"{label} supports at most {minor_units} {unit_label}.")


def _validation_message(exc: ValidationError) -> str:
    if hasattr(exc, "message_dict"):
        for messages in exc.message_dict.values():
            if messages:
                return str(messages[0])
    if exc.messages:
        return str(exc.messages[0])
    return "Fee profile validation failed."
