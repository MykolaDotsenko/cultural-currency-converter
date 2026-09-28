from __future__ import annotations

import pytest

from config.environment import (
    ConfigurationError,
    HttpsMode,
    RuntimeEnvironment,
    load_runtime_config,
)


def test_local_defaults_require_no_committed_secret() -> None:
    config = load_runtime_config({})

    assert config.environment is RuntimeEnvironment.LOCAL
    assert config.debug is True
    assert config.allowed_hosts == ("localhost", "127.0.0.1", "[::1]")
    assert len(config.secret_key) >= 50
    assert config.https_mode is None
    assert config.hsts_seconds == 0
    assert config.is_deployed is False


def test_test_environment_requires_no_ci_secret() -> None:
    config = load_runtime_config({"APP_ENV": "test"})

    assert config.environment is RuntimeEnvironment.TEST
    assert config.debug is False
    assert "testserver" in config.allowed_hosts
    assert "not-for-production" in config.secret_key
    assert config.https_mode is None
    assert config.hsts_seconds == 0


def test_boolean_values_are_parsed_case_insensitively() -> None:
    config = load_runtime_config(
        {
            "APP_ENV": "test",
            "DJANGO_DEBUG": "YeS",
        }
    )

    assert config.debug is True


@pytest.mark.parametrize("value", ["maybe", "2", "enabled"])
def test_invalid_boolean_values_fail_fast(value: str) -> None:
    with pytest.raises(ConfigurationError, match="DJANGO_DEBUG must be a boolean"):
        load_runtime_config(
            {
                "APP_ENV": "test",
                "DJANGO_DEBUG": value,
            }
        )


def test_unknown_environment_fails_fast() -> None:
    with pytest.raises(ConfigurationError, match="APP_ENV must be one of"):
        load_runtime_config({"APP_ENV": "prod"})


@pytest.mark.parametrize("environment", ["demo", "preview", "production"])
def test_deployed_environments_require_allowed_hosts(environment: str) -> None:
    with pytest.raises(ConfigurationError, match="DJANGO_ALLOWED_HOSTS is required"):
        load_runtime_config(
            {
                "APP_ENV": environment,
                "DJANGO_SECRET_KEY": "x" * 50,
            }
        )


@pytest.mark.parametrize("environment", ["demo", "preview", "production"])
def test_deployed_environments_require_secret(environment: str) -> None:
    with pytest.raises(ConfigurationError, match="DJANGO_SECRET_KEY is required"):
        load_runtime_config(
            {
                "APP_ENV": environment,
                "DJANGO_ALLOWED_HOSTS": "example.com",
            }
        )


@pytest.mark.parametrize("environment", ["demo", "preview", "production"])
def test_deployed_environments_reject_short_secret(environment: str) -> None:
    with pytest.raises(ConfigurationError, match="at least 50 characters"):
        load_runtime_config(
            {
                "APP_ENV": environment,
                "DJANGO_SECRET_KEY": "short",
                "DJANGO_ALLOWED_HOSTS": "example.com",
            }
        )


@pytest.mark.parametrize("environment", ["demo", "preview", "production"])
def test_deployed_environments_reject_debug(environment: str) -> None:
    with pytest.raises(ConfigurationError, match="DJANGO_DEBUG must be false"):
        load_runtime_config(
            {
                "APP_ENV": environment,
                "DJANGO_DEBUG": "true",
                "DJANGO_SECRET_KEY": "x" * 50,
                "DJANGO_ALLOWED_HOSTS": "example.com",
            }
        )


@pytest.mark.parametrize("environment", ["demo", "preview", "production"])
def test_deployed_environments_reject_wildcard_hosts(environment: str) -> None:
    with pytest.raises(ConfigurationError, match="Wildcard"):
        load_runtime_config(
            {
                "APP_ENV": environment,
                "DJANGO_SECRET_KEY": "x" * 50,
                "DJANGO_ALLOWED_HOSTS": "*",
            }
        )


def test_allowed_hosts_reject_urls_and_paths() -> None:
    with pytest.raises(ConfigurationError, match="without schemes or paths"):
        load_runtime_config(
            {
                "APP_ENV": "test",
                "DJANGO_ALLOWED_HOSTS": "https://example.com",
            }
        )


@pytest.mark.parametrize("environment", ["demo", "preview", "production"])
def test_deployed_environments_require_explicit_https_mode(environment: str) -> None:
    with pytest.raises(ConfigurationError, match="DJANGO_HTTPS_MODE is required"):
        load_runtime_config(
            {
                "APP_ENV": environment,
                "DJANGO_SECRET_KEY": "s3cure-" * 10,
                "DJANGO_ALLOWED_HOSTS": "example.com",
                **({"DJANGO_HSTS_SECONDS": "300"} if environment == "production" else {}),
            }
        )


@pytest.mark.parametrize("https_mode", ["auto", "forwarded", "https"])
def test_invalid_https_mode_fails_fast(https_mode: str) -> None:
    with pytest.raises(ConfigurationError, match="must be direct or proxy"):
        load_runtime_config(
            {
                "APP_ENV": "preview",
                "DJANGO_SECRET_KEY": "s3cure-" * 10,
                "DJANGO_ALLOWED_HOSTS": "preview.example.com",
                "DJANGO_HTTPS_MODE": https_mode,
            }
        )


def test_production_requires_positive_explicit_hsts() -> None:
    base = {
        "APP_ENV": "production",
        "DJANGO_SECRET_KEY": "s3cure-" * 10,
        "DJANGO_ALLOWED_HOSTS": "example.com",
        "DJANGO_HTTPS_MODE": "direct",
    }

    with pytest.raises(ConfigurationError, match="DJANGO_HSTS_SECONDS is required"):
        load_runtime_config(base)

    with pytest.raises(ConfigurationError, match="must be positive"):
        load_runtime_config({**base, "DJANGO_HSTS_SECONDS": "0"})


@pytest.mark.parametrize("hsts_seconds", ["abc", "-1", "63072001"])
def test_invalid_hsts_seconds_fail_fast(hsts_seconds: str) -> None:
    with pytest.raises(ConfigurationError, match="DJANGO_HSTS_SECONDS"):
        load_runtime_config(
            {
                "APP_ENV": "preview",
                "DJANGO_SECRET_KEY": "s3cure-" * 10,
                "DJANGO_ALLOWED_HOSTS": "preview.example.com",
                "DJANGO_HTTPS_MODE": "proxy",
                "DJANGO_HSTS_SECONDS": hsts_seconds,
            }
        )


def test_hsts_flags_require_nonzero_hsts_window() -> None:
    with pytest.raises(ConfigurationError, match="cannot be enabled"):
        load_runtime_config(
            {
                "APP_ENV": "preview",
                "DJANGO_SECRET_KEY": "s3cure-" * 10,
                "DJANGO_ALLOWED_HOSTS": "preview.example.com",
                "DJANGO_HTTPS_MODE": "proxy",
                "DJANGO_HSTS_SECONDS": "0",
                "DJANGO_HSTS_INCLUDE_SUBDOMAINS": "true",
            }
        )


def test_preview_proxy_mode_is_explicit_without_forcing_hsts() -> None:
    config = load_runtime_config(
        {
            "APP_ENV": "preview",
            "DJANGO_SECRET_KEY": "s3cure-" * 10,
            "DJANGO_ALLOWED_HOSTS": "preview.example.com",
            "DJANGO_HTTPS_MODE": "proxy",
        }
    )

    assert config.https_mode is HttpsMode.PROXY
    assert config.hsts_seconds == 0
    assert config.is_deployed is True



def test_demo_accepts_secure_ephemeral_configuration() -> None:
    config = load_runtime_config(
        {
            "APP_ENV": "demo",
            "DJANGO_DEBUG": "false",
            "DJANGO_SECRET_KEY": "d" * 64,
            "DJANGO_ALLOWED_HOSTS": "demo.example.com",
            "DJANGO_HTTPS_MODE": "proxy",
        }
    )

    assert config.environment is RuntimeEnvironment.DEMO
    assert config.debug is False
    assert config.allowed_hosts == ("demo.example.com",)
    assert config.https_mode is HttpsMode.PROXY
    assert config.hsts_seconds == 0
    assert config.is_production is False
    assert config.is_deployed is True


def test_production_accepts_explicit_safe_configuration() -> None:
    config = load_runtime_config(
        {
            "APP_ENV": "production",
            "DJANGO_DEBUG": "false",
            "DJANGO_SECRET_KEY": "s" * 64,
            "DJANGO_ALLOWED_HOSTS": "example.com,www.example.com",
            "DJANGO_HTTPS_MODE": "proxy",
            "DJANGO_HSTS_SECONDS": "300",
            "DJANGO_HSTS_INCLUDE_SUBDOMAINS": "true",
            "DJANGO_HSTS_PRELOAD": "true",
        }
    )

    assert config.environment is RuntimeEnvironment.PRODUCTION
    assert config.debug is False
    assert config.allowed_hosts == ("example.com", "www.example.com")
    assert config.https_mode is HttpsMode.PROXY
    assert config.hsts_seconds == 300
    assert config.hsts_include_subdomains is True
    assert config.hsts_preload is True
    assert config.is_production is True
    assert config.is_deployed is True
