"""Authenticated, opt-in recovery-email ownership verification (not password reset)."""

from __future__ import annotations

import hashlib
import secrets
from uuid import uuid4

from django.conf import settings
from django.core import signing
from django.core.cache import cache
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import VerifiedRecoveryEmail

_SALT = "ccc.recovery-email.verify.v1"
_MAX_AGE_SECONDS = 1800
_COOLDOWN_SECONDS = 180


class RecoveryEmailError(Exception):
    """Expected safe failure that cannot reveal SMTP/database exception text."""


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _make_token(user_id: int, nonce: object, email: str) -> str:
    return signing.dumps(
        {"user_id": user_id, "nonce": str(nonce), "digest": _digest(email)},
        salt=_SALT,
    )


def _load_token(token: str) -> dict:
    try:
        value = signing.loads(token, salt=_SALT, max_age=_MAX_AGE_SECONDS)
    except signing.BadSignature:
        raise RecoveryEmailError("Verification link invalid or expired.") from None
    if (
        not isinstance(value, dict)
        or set(value) != {"user_id", "nonce", "digest"}
        or not isinstance(value["user_id"], int)
        or not isinstance(value["nonce"], str)
        or not isinstance(value["digest"], str)
    ):
        raise RecoveryEmailError("Verification link invalid or expired.")
    return value


def propose_recovery_email(*, user, email: str) -> None:
    """Never trust a proposed address until a signed, owner-confirmed POST."""

    if not settings.ACCOUNT_EMAIL_VERIFICATION_ENABLED:
        raise RecoveryEmailError("Email verification is unavailable.")
    normalized = email.strip().lower()
    key = f"ccc:email-verification:user:{user.pk}"
    try:
        accepted = cache.add(key, "1", timeout=_COOLDOWN_SECONDS)
    except Exception:
        raise RecoveryEmailError("Email verification is unavailable.") from None
    if not accepted:
        raise RecoveryEmailError("Please try again in a few minutes.")

    try:
        with transaction.atomic():
            if (
                VerifiedRecoveryEmail.objects.filter(
                    email__iexact=normalized, verified_at__isnull=False
                )
                .exclude(user=user)
                .exists()
            ):
                raise RecoveryEmailError("This address cannot be used.")
            identity = (
                VerifiedRecoveryEmail.objects.select_for_update()
                .filter(user=user)
                .first()
            )
            if identity is not None and identity.is_verified and identity.email == normalized:
                raise RecoveryEmailError("This address is already verified.")
            if identity is None:
                identity = VerifiedRecoveryEmail(user=user)
            identity.email = normalized
            identity.verified_at = None
            identity.verification_nonce = uuid4()
            identity.full_clean()
            identity.save()
            code = _make_token(user.pk, identity.verification_nonce, identity.email)
            verify_url = settings.ACCOUNT_EMAIL_PUBLIC_ORIGIN + reverse(
                "recovery_email_confirm", kwargs={"token": code}
            )
            delivered = send_mail(
                "Verify your Cultural Currency Converter recovery email",
                (
                    "Confirm the recovery email for your signed-in account.\n"
                    "This link expires in 30 minutes and requires signing in.\n\n"
                    f"{verify_url}\n\n"
                    "If you did not request this, ignore this email.\n"
                ),
                settings.DEFAULT_FROM_EMAIL,
                [normalized],
                fail_silently=False,
            )
            if delivered != 1:
                raise RecoveryEmailError("Email verification is unavailable.")
    except RecoveryEmailError:
        raise
    except Exception:
        raise RecoveryEmailError("Email verification is unavailable.") from None


def _validate(*, user, token: str, identity: VerifiedRecoveryEmail) -> None:
    payload = _load_token(token)
    if (
        not settings.ACCOUNT_EMAIL_VERIFICATION_ENABLED
        or identity.user_id != user.pk
        or payload["user_id"] != user.pk
        or identity.verified_at is not None
        or str(identity.verification_nonce) != payload["nonce"]
        or not secrets.compare_digest(_digest(identity.email), payload["digest"])
    ):
        raise RecoveryEmailError("Verification link invalid or expired.")


def preview_recovery_token(*, user, token: str) -> None:
    if not user.is_authenticated:
        raise RecoveryEmailError("Verification link invalid or expired.")
    identity = VerifiedRecoveryEmail.objects.filter(user=user).first()
    if identity is None:
        raise RecoveryEmailError("Verification link invalid or expired.")
    _validate(user=user, token=token, identity=identity)


def confirm_recovery_token(*, user, token: str) -> None:
    """One-time atomic transition, with conditional DB uniqueness as backstop."""

    if not user.is_authenticated:
        raise RecoveryEmailError("Verification link invalid or expired.")
    try:
        with transaction.atomic():
            identity = VerifiedRecoveryEmail.objects.select_for_update().get(user=user)
            _validate(user=user, token=token, identity=identity)
            identity.verified_at = timezone.now()
            identity.verification_nonce = uuid4()
            identity.save(update_fields=["verified_at", "verification_nonce", "updated_at"])
    except (VerifiedRecoveryEmail.DoesNotExist, IntegrityError):
        raise RecoveryEmailError("Verification link invalid or expired.") from None
