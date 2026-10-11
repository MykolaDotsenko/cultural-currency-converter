"""Fail-closed opt-in configuration for recovery-email verification SMTP."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from config.environment import ConfigurationError, RuntimeEnvironment


@dataclass(frozen=True, slots=True)
class AccountMailConfig:
    enabled: bool
    origin: str = ""
    sender: str = ""
    host: str = ""
    port: int = 587
    username: str = ""
    password: str = ""
    tls: bool = False


def load_account_mail_config(
    environ: Mapping[str, str], environment: RuntimeEnvironment
) -> AccountMailConfig:
    flag = environ.get("ACCOUNT_EMAIL_VERIFICATION_ENABLED", "false").strip().lower()
    if flag not in {"true", "false"}:
        raise ConfigurationError("ACCOUNT_EMAIL_VERIFICATION_ENABLED must be true or false.")
    if flag == "false":
        return AccountMailConfig(enabled=False)
    origin = environ.get("ACCOUNT_EMAIL_PUBLIC_ORIGIN", "").strip().rstrip("/")
    sender = environ.get("ACCOUNT_EMAIL_FROM", "").strip()
    host = environ.get("ACCOUNT_SMTP_HOST", "").strip()
    username = environ.get("ACCOUNT_SMTP_USER", "").strip()
    password = environ.get("ACCOUNT_SMTP_PASSWORD", "")
    tls_flag = environ.get("ACCOUNT_SMTP_USE_TLS", "true").strip().lower()
    try:
        url = urlsplit(origin)
        valid = (
            url.scheme == "https"
            and bool(url.hostname)
            and url.username is None
            and url.password is None
            and not url.path
            and not url.query
            and not url.fragment
        )
    except ValueError:
        valid = False
    if not valid:
        raise ConfigurationError("ACCOUNT_EMAIL_PUBLIC_ORIGIN must be an HTTPS origin.")
    try:
        validate_email(sender)
    except ValidationError:
        raise ConfigurationError("ACCOUNT_EMAIL_FROM must be a valid address.") from None
    if not host or "://" in host or "/" in host or " " in host:
        raise ConfigurationError("ACCOUNT_SMTP_HOST must be a hostname.")
    if tls_flag not in {"true", "false"}:
        raise ConfigurationError("ACCOUNT_SMTP_USE_TLS must be true or false.")
    if environment not in {RuntimeEnvironment.LOCAL, RuntimeEnvironment.TEST} and (
        not username or not password or tls_flag != "true"
    ):
        raise ConfigurationError("Deployed account email requires authenticated SMTP/TLS.")
    try:
        port = int(environ.get("ACCOUNT_SMTP_PORT", "587"))
    except ValueError:
        raise ConfigurationError("ACCOUNT_SMTP_PORT must be a valid port.") from None
    if not 1 <= port <= 65535:
        raise ConfigurationError("ACCOUNT_SMTP_PORT must be a valid port.")
    return AccountMailConfig(
        enabled=True,
        origin=origin,
        sender=sender,
        host=host,
        port=port,
        username=username,
        password=password,
        tls=tls_flag == "true",
    )
