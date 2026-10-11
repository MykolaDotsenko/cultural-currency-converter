"""Forgotten-password reset, exclusively through independently verified recovery email.

Legacy auth.User.email and pending identities never authorize a reset.
"""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.core.cache import cache
from django.core.mail import send_mail
from django.urls import reverse
from django.utils.crypto import salted_hmac
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from apps.accounts.models import VerifiedRecoveryEmail

_COOLDOWN_SECONDS = 300
_IP_COOLDOWN_SECONDS = 10


class VerifiedEmailPasswordTokenGenerator(PasswordResetTokenGenerator):
    """Tie standard password/session rotation tokens to verified email ownership."""

    key_salt = "ccc.accounts.verified-password-reset.v1"

    def _make_hash_value(self, user, timestamp):
        identity = VerifiedRecoveryEmail.objects.filter(
            user=user, verified_at__isnull=False
        ).first()
        if identity is None:
            return super()._make_hash_value(user, timestamp) + "|no-verified-email"
        return (
            super()._make_hash_value(user, timestamp)
            + f"|{identity.email}|{identity.verified_at}|{identity.verification_nonce}"
        )


verified_password_token_generator = VerifiedEmailPasswordTokenGenerator()


def _throttle_key(namespace: str, value: str) -> str:
    return "ccc:password-reset:" + namespace + ":" + salted_hmac(
        "ccc.password-reset.throttle.v1", value
    ).hexdigest()


def request_verified_password_reset(*, email: str, remote_address: str = "") -> None:
    """Try safe delivery; always return identically for known/unknown recipients.

    Cache failure and mail-provider failure fail closed without leaking
    account state, storage topology or transport exception details.
    """

    if not settings.ACCOUNT_EMAIL_VERIFICATION_ENABLED:
        return
    normalized = email.strip().lower()
    if not normalized:
        return
    try:
        if not cache.add(
            _throttle_key("address", normalized), "1", timeout=_COOLDOWN_SECONDS
        ):
            return
        if remote_address and not cache.add(
            _throttle_key("client", remote_address), "1", timeout=_IP_COOLDOWN_SECONDS
        ):
            return
    except Exception:
        return

    identity = VerifiedRecoveryEmail.objects.select_related("user").filter(
        email__iexact=normalized,
        verified_at__isnull=False,
        user__is_active=True,
    ).first()
    if identity is None or not identity.user.has_usable_password():
        return

    user = identity.user
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = verified_password_token_generator.make_token(user)
    relative_url = reverse(
        "password_reset_confirm",
        kwargs={"uidb64": uid, "token": token},
    )
    url = settings.ACCOUNT_EMAIL_PUBLIC_ORIGIN + relative_url
    try:
        send_mail(
            "Reset your Cultural Currency Converter password",
            (
                "A password reset was requested for your account.\n"
                "This link expires in 30 minutes and can only be used once.\n\n"
                f"{url}\n\n"
                "If you did not request this, ignore the message.\n"
            ),
            settings.DEFAULT_FROM_EMAIL,
            [identity.email],
            fail_silently=False,
        )
    except Exception:
        # Never expose transport configuration or whether an account exists.
        return
