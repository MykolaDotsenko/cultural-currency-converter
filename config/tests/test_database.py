from __future__ import annotations

from pathlib import Path

import pytest

from config.database import DatabaseConfig, load_database_config
from config.environment import ConfigurationError, RuntimeEnvironment

BASE_DIR = Path("/tmp/cultural-currency-test")


def test_local_defaults_to_sqlite() -> None:
    config = load_database_config(
        environ={},
        environment=RuntimeEnvironment.LOCAL,
        base_dir=BASE_DIR,
    )

    assert config.engine == "django.db.backends.sqlite3"
    assert config.name == str(BASE_DIR / "db.sqlite3")
    assert config.is_postgresql is False
    assert config.as_django_settings() == {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": str(BASE_DIR / "db.sqlite3"),
        "ATOMIC_REQUESTS": False,
    }


def test_test_environment_defaults_to_sqlite() -> None:
    config = load_database_config(
        environ={},
        environment=RuntimeEnvironment.TEST,
        base_dir=BASE_DIR,
    )

    assert config.engine == "django.db.backends.sqlite3"


def test_demo_defaults_to_ephemeral_sqlite() -> None:
    config = load_database_config(
        environ={},
        environment=RuntimeEnvironment.DEMO,
        base_dir=BASE_DIR,
    )

    assert config.engine == "django.db.backends.sqlite3"


@pytest.mark.parametrize("environment", [RuntimeEnvironment.PREVIEW, RuntimeEnvironment.PRODUCTION])
def test_deployed_environments_require_database_url(environment: RuntimeEnvironment) -> None:
    with pytest.raises(ConfigurationError, match="DATABASE_URL is required"):
        load_database_config(
            environ={},
            environment=environment,
            base_dir=BASE_DIR,
        )


@pytest.mark.parametrize("scheme", ["postgresql", "postgres"])
def test_postgresql_url_is_normalized(scheme: str) -> None:
    config = load_database_config(
        environ={
            "DATABASE_URL": (
                f"{scheme}://currency_user:p%40ssword@db.example.test:5433/"
                "quiet%5Fatlas?sslmode=require&application_name=currency-app"
            )
        },
        environment=RuntimeEnvironment.PRODUCTION,
        base_dir=BASE_DIR,
    )

    assert config == DatabaseConfig(
        engine="django.db.backends.postgresql",
        name="quiet_atlas",
        user="currency_user",
        password="p@ssword",
        host="db.example.test",
        port="5433",
        options=(("sslmode", "require"), ("application_name", "currency-app")),
    )

    settings = config.as_django_settings()
    assert settings["ENGINE"] == "django.db.backends.postgresql"
    assert settings["NAME"] == "quiet_atlas"
    assert settings["USER"] == "currency_user"
    assert settings["PASSWORD"] == "p@ssword"
    assert settings["HOST"] == "db.example.test"
    assert settings["PORT"] == "5433"
    assert settings["CONN_MAX_AGE"] == 0
    assert settings["ATOMIC_REQUESTS"] is False
    assert settings["OPTIONS"] == {
        "sslmode": "require",
        "application_name": "currency-app",
    }


def test_postgresql_default_port_is_5432() -> None:
    config = load_database_config(
        environ={"DATABASE_URL": "postgresql://user:pass@localhost/currency"},
        environment=RuntimeEnvironment.TEST,
        base_dir=BASE_DIR,
    )

    assert config.port == "5432"


@pytest.mark.parametrize(
    ("url", "message"),
    [
        ("mysql://user:pass@localhost/db", "postgresql:// scheme"),
        ("postgresql://user:pass@/db", "PostgreSQL host"),
        ("postgresql://localhost/db", "PostgreSQL user"),
        ("postgresql://user:pass@localhost/", "database name"),
        ("postgresql://user:pass@localhost/a/b", "exactly one database name"),
        ("postgresql://user:pass@localhost:bad/db", "invalid PostgreSQL port"),
        ("postgresql://user:pass@localhost/db#fragment", "URL fragment"),
    ],
)
def test_invalid_database_urls_fail_fast(url: str, message: str) -> None:
    with pytest.raises(ConfigurationError, match=message):
        load_database_config(
            environ={"DATABASE_URL": url},
            environment=RuntimeEnvironment.TEST,
            base_dir=BASE_DIR,
        )


def test_database_password_is_redacted_from_repr() -> None:
    config = load_database_config(
        environ={"DATABASE_URL": "postgresql://user:super-secret@localhost/db"},
        environment=RuntimeEnvironment.TEST,
        base_dir=BASE_DIR,
    )

    assert "super-secret" not in repr(config)


def test_malformed_database_query_options_fail_fast() -> None:
    with pytest.raises(ConfigurationError, match="invalid query options"):
        load_database_config(
            environ={"DATABASE_URL": "postgresql://user:pass@localhost/db?broken"},
            environment=RuntimeEnvironment.TEST,
            base_dir=BASE_DIR,
        )


def test_duplicate_database_query_options_fail_fast() -> None:
    with pytest.raises(ConfigurationError, match="duplicated"):
        load_database_config(
            environ={
                "DATABASE_URL": (
                    "postgresql://user:pass@localhost/db?sslmode=require&sslmode=prefer"
                )
            },
            environment=RuntimeEnvironment.TEST,
            base_dir=BASE_DIR,
        )


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://user:pass@localhost/db?sslmode",
        "postgresql://user:pass@localhost/db?=require",
    ],
)
def test_invalid_query_options_fail_fast(url: str) -> None:
    with pytest.raises(ConfigurationError, match=r"invalid query options|empty query option"):
        load_database_config(
            environ={"DATABASE_URL": url},
            environment=RuntimeEnvironment.TEST,
            base_dir=BASE_DIR,
        )


@pytest.mark.parametrize("option", ["user", "password", "host", "port", "dbname"])
def test_query_options_cannot_override_core_connection_fields(option: str) -> None:
    with pytest.raises(ConfigurationError, match="duplicates a core connection field"):
        load_database_config(
            environ={"DATABASE_URL": f"postgresql://user:pass@localhost/db?{option}=override"},
            environment=RuntimeEnvironment.TEST,
            base_dir=BASE_DIR,
        )


def test_empty_postgresql_user_fails_fast() -> None:
    with pytest.raises(ConfigurationError, match="PostgreSQL user"):
        load_database_config(
            environ={"DATABASE_URL": "postgresql://:pass@localhost/db"},
            environment=RuntimeEnvironment.TEST,
            base_dir=BASE_DIR,
        )
