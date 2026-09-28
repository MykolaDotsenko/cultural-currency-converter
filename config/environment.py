from __future__ import annotations

import os
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum


class ConfigurationError(RuntimeError):
    """Raised when runtime configuration is missing or unsafe."""


class RuntimeEnvironment(StrEnum):
    LOCAL = "local"
    TEST = "test"
    DEMO = "demo"
    PREVIEW = "preview"
    PRODUCTION = "production"


class HttpsMode(StrEnum):
    DIRECT = "direct"
    PROXY = "proxy"


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    environment: RuntimeEnvironment
    secret_key: str
    debug: bool
    allowed_hosts: tuple[str, ...]
    https_mode: HttpsMode | None
    hsts_seconds: int
    hsts_include_subdomains: bool
    hsts_preload: bool

    @property
    def is_production(self) -> bool:
        return self.environment is RuntimeEnvironment.PRODUCTION

    @property
    def is_deployed(self) -> bool:
        return self.environment in {
            RuntimeEnvironment.DEMO,
            RuntimeEnvironment.PREVIEW,
            RuntimeEnvironment.PRODUCTION,
        }


_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off"})

_LOCAL_HOSTS = ("localhost", "127.0.0.1", "[::1]")
_TEST_HOSTS = ("testserver", "localhost", "127.0.0.1")
_TEST_SECRET_KEY = "test-only-secret-key-not-for-production-use-0123456789abcdef"


def _optional(environ: Mapping[str, str], name: str) -> str | None:
    value = environ.get(name)
    if value is None:
        return None

    value = value.strip()
    return value or None


def _parse_environment(environ: Mapping[str, str]) -> RuntimeEnvironment:
    raw = _optional(environ, "APP_ENV") or RuntimeEnvironment.LOCAL.value

    try:
        return RuntimeEnvironment(raw.lower())
    except ValueError as exc:
        allowed = ", ".join(environment.value for environment in RuntimeEnvironment)
        raise ConfigurationError(f"APP_ENV must be one of: {allowed}.") from exc


def _parse_bool(
    environ: Mapping[str, str],
    name: str,
    *,
    default: bool,
) -> bool:
    raw = _optional(environ, name)
    if raw is None:
        return default

    normalized = raw.lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False

    raise ConfigurationError(f"{name} must be a boolean value (true/false, yes/no, on/off, 1/0).")


def _parse_allowed_hosts(
    environ: Mapping[str, str],
    environment: RuntimeEnvironment,
) -> tuple[str, ...]:
    raw = _optional(environ, "DJANGO_ALLOWED_HOSTS")

    if raw is None:
        if environment is RuntimeEnvironment.LOCAL:
            return _LOCAL_HOSTS
        if environment is RuntimeEnvironment.TEST:
            return _TEST_HOSTS
        raise ConfigurationError(
            "DJANGO_ALLOWED_HOSTS is required for demo, preview and production."
        )

    hosts = tuple(host.strip() for host in raw.split(",") if host.strip())
    if not hosts:
        raise ConfigurationError("DJANGO_ALLOWED_HOSTS must contain at least one host.")

    for host in hosts:
        if "://" in host or "/" in host:
            raise ConfigurationError(
                "DJANGO_ALLOWED_HOSTS entries must be host names without schemes or paths."
            )

    if (
        environment
        in {
            RuntimeEnvironment.DEMO,
            RuntimeEnvironment.PREVIEW,
            RuntimeEnvironment.PRODUCTION,
        }
        and "*" in hosts
    ):
        raise ConfigurationError(
            "Wildcard DJANGO_ALLOWED_HOSTS is not allowed in demo, preview or production."
        )

    return hosts


def _parse_https_mode(
    environ: Mapping[str, str],
    environment: RuntimeEnvironment,
) -> HttpsMode | None:
    raw = _optional(environ, "DJANGO_HTTPS_MODE")
    if raw is None:
        if environment in {
            RuntimeEnvironment.DEMO,
            RuntimeEnvironment.PREVIEW,
            RuntimeEnvironment.PRODUCTION,
        }:
            raise ConfigurationError(
                "DJANGO_HTTPS_MODE is required for demo, preview and production (direct/proxy)."
            )
        return None

    try:
        return HttpsMode(raw.lower())
    except ValueError as exc:
        raise ConfigurationError("DJANGO_HTTPS_MODE must be direct or proxy.") from exc


def _parse_hsts_seconds(
    environ: Mapping[str, str],
    environment: RuntimeEnvironment,
) -> int:
    raw = _optional(environ, "DJANGO_HSTS_SECONDS")
    if raw is None:
        if environment is RuntimeEnvironment.PRODUCTION:
            raise ConfigurationError("DJANGO_HSTS_SECONDS is required in production.")
        return 0

    try:
        seconds = int(raw)
    except ValueError as exc:
        raise ConfigurationError("DJANGO_HSTS_SECONDS must be an integer.") from exc

    if seconds < 0 or seconds > 63_072_000:
        raise ConfigurationError("DJANGO_HSTS_SECONDS must be between 0 and 63072000.")
    if environment is RuntimeEnvironment.PRODUCTION and seconds == 0:
        raise ConfigurationError("DJANGO_HSTS_SECONDS must be positive in production.")
    return seconds


def _parse_hsts_flags(
    environ: Mapping[str, str],
    *,
    hsts_seconds: int,
) -> tuple[bool, bool]:
    include_subdomains = _parse_bool(
        environ,
        "DJANGO_HSTS_INCLUDE_SUBDOMAINS",
        default=False,
    )
    preload = _parse_bool(
        environ,
        "DJANGO_HSTS_PRELOAD",
        default=False,
    )
    if hsts_seconds == 0 and (include_subdomains or preload):
        raise ConfigurationError(
            "HSTS include-subdomains/preload cannot be enabled when DJANGO_HSTS_SECONDS is 0."
        )
    return include_subdomains, preload


def _load_secret_key(
    environ: Mapping[str, str],
    environment: RuntimeEnvironment,
) -> str:
    configured = _optional(environ, "DJANGO_SECRET_KEY")
    if configured is not None:
        if (
            environment
            in {
                RuntimeEnvironment.DEMO,
                RuntimeEnvironment.PREVIEW,
                RuntimeEnvironment.PRODUCTION,
            }
            and len(configured) < 50
        ):
            raise ConfigurationError(
                "DJANGO_SECRET_KEY must be at least 50 characters in demo, preview or production."
            )
        return configured

    if environment is RuntimeEnvironment.TEST:
        return _TEST_SECRET_KEY

    if environment is RuntimeEnvironment.LOCAL:
        # Local development requires no committed secret. Set DJANGO_SECRET_KEY
        # explicitly when stable sessions across process restarts are useful.
        return secrets.token_urlsafe(48)

    raise ConfigurationError("DJANGO_SECRET_KEY is required for demo, preview and production.")


def load_runtime_config(
    environ: Mapping[str, str] | None = None,
) -> RuntimeConfig:
    """Load and validate security-sensitive Django runtime configuration."""

    values = os.environ if environ is None else environ
    environment = _parse_environment(values)
    debug = _parse_bool(
        values,
        "DJANGO_DEBUG",
        default=environment is RuntimeEnvironment.LOCAL,
    )

    if (
        environment
        in {
            RuntimeEnvironment.DEMO,
            RuntimeEnvironment.PREVIEW,
            RuntimeEnvironment.PRODUCTION,
        }
        and debug
    ):
        raise ConfigurationError("DJANGO_DEBUG must be false in demo, preview and production.")

    secret_key = _load_secret_key(values, environment)
    allowed_hosts = _parse_allowed_hosts(values, environment)
    https_mode = _parse_https_mode(values, environment)
    hsts_seconds = _parse_hsts_seconds(values, environment)
    hsts_include_subdomains, hsts_preload = _parse_hsts_flags(
        values,
        hsts_seconds=hsts_seconds,
    )

    return RuntimeConfig(
        environment=environment,
        secret_key=secret_key,
        debug=debug,
        allowed_hosts=allowed_hosts,
        https_mode=https_mode,
        hsts_seconds=hsts_seconds,
        hsts_include_subdomains=hsts_include_subdomains,
        hsts_preload=hsts_preload,
    )
