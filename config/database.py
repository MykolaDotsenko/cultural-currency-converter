from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, unquote, urlparse

from config.environment import ConfigurationError, RuntimeEnvironment

_RESERVED_QUERY_OPTIONS = frozenset({"user", "password", "host", "port", "dbname"})


@dataclass(frozen=True, slots=True)
class DatabaseConfig:
    """Normalized database settings independent from Django's global settings."""

    engine: str
    name: str
    user: str = ""
    password: str = field(default="", repr=False)
    host: str = ""
    port: str = ""
    options: tuple[tuple[str, str], ...] = ()

    @property
    def is_postgresql(self) -> bool:
        return self.engine == "django.db.backends.postgresql"

    def as_django_settings(self) -> dict[str, Any]:
        settings: dict[str, Any] = {
            "ENGINE": self.engine,
            "NAME": self.name,
            "ATOMIC_REQUESTS": False,
        }

        if self.is_postgresql:
            settings.update(
                {
                    "USER": self.user,
                    "PASSWORD": self.password,
                    "HOST": self.host,
                    "PORT": self.port,
                    "CONN_MAX_AGE": 0,
                }
            )
            if self.options:
                settings["OPTIONS"] = dict(self.options)

        return settings


def _optional(environ: Mapping[str, str], name: str) -> str | None:
    value = environ.get(name)
    if value is None:
        return None

    value = value.strip()
    return value or None


def _parse_query_options(query: str) -> tuple[tuple[str, str], ...]:
    if not query:
        return ()

    try:
        pairs = parse_qsl(query, keep_blank_values=False, strict_parsing=True)
    except ValueError as exc:
        raise ConfigurationError("DATABASE_URL contains invalid query options.") from exc

    seen: set[str] = set()
    normalized: list[tuple[str, str]] = []

    for key, value in pairs:
        key = key.strip()
        if not key:
            raise ConfigurationError("DATABASE_URL contains an empty query option.")

        if key in _RESERVED_QUERY_OPTIONS:
            raise ConfigurationError(
                f"DATABASE_URL query option {key!r} duplicates a core connection field."
            )

        if key in seen:
            raise ConfigurationError(f"DATABASE_URL query option {key!r} is duplicated.")

        seen.add(key)
        normalized.append((key, value))

    return tuple(normalized)


def _parse_postgresql_url(database_url: str) -> DatabaseConfig:
    parsed = urlparse(database_url)

    if parsed.scheme not in {"postgres", "postgresql"}:
        raise ConfigurationError("DATABASE_URL must use the postgresql:// scheme when configured.")

    if parsed.fragment:
        raise ConfigurationError("DATABASE_URL must not contain a URL fragment.")

    if not parsed.hostname:
        raise ConfigurationError("DATABASE_URL must include a PostgreSQL host.")

    if parsed.username is None or not unquote(parsed.username).strip():
        raise ConfigurationError("DATABASE_URL must include a PostgreSQL user.")

    database_name = unquote(parsed.path.lstrip("/")).strip()
    if not database_name or "/" in database_name:
        raise ConfigurationError("DATABASE_URL must include exactly one database name.")

    try:
        port = parsed.port or 5432
    except ValueError as exc:
        raise ConfigurationError("DATABASE_URL contains an invalid PostgreSQL port.") from exc

    return DatabaseConfig(
        engine="django.db.backends.postgresql",
        name=database_name,
        user=unquote(parsed.username),
        password=unquote(parsed.password or ""),
        host=parsed.hostname,
        port=str(port),
        options=_parse_query_options(parsed.query),
    )


def load_database_config(
    *,
    environ: Mapping[str, str],
    environment: RuntimeEnvironment,
    base_dir: Path,
) -> DatabaseConfig:
    """Require PostgreSQL for every deployed, user-writable environment."""

    database_url = _optional(environ, "DATABASE_URL")

    if database_url is not None:
        return _parse_postgresql_url(database_url)

    if environment in {
        RuntimeEnvironment.DEMO,
        RuntimeEnvironment.PREVIEW,
        RuntimeEnvironment.PRODUCTION,
    }:
        raise ConfigurationError("DATABASE_URL is required for demo, preview and production.")

    return DatabaseConfig(
        engine="django.db.backends.sqlite3",
        name=str(base_dir / "db.sqlite3"),
    )
