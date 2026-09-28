from __future__ import annotations

import pytest

from config.cache import CacheConfig, load_cache_config
from config.environment import ConfigurationError, RuntimeEnvironment


def test_local_defaults_to_process_local_cache() -> None:
    config = load_cache_config(environ={}, environment=RuntimeEnvironment.LOCAL)

    assert config.shared is False
    assert config.backend == "django.core.cache.backends.locmem.LocMemCache"
    assert config.as_django_settings() == {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "cultural-currency-local",
        "KEY_PREFIX": "cultural-currency:local",
    }


def test_test_environment_defaults_to_process_local_cache() -> None:
    config = load_cache_config(environ={}, environment=RuntimeEnvironment.TEST)

    assert config.shared is False
    assert config.as_django_settings()["KEY_PREFIX"] == "cultural-currency:test"



def test_demo_defaults_to_process_local_cache() -> None:
    config = load_cache_config(environ={}, environment=RuntimeEnvironment.DEMO)

    assert config.shared is False
    assert config.as_django_settings()["KEY_PREFIX"] == "cultural-currency:demo"


@pytest.mark.parametrize("environment", [RuntimeEnvironment.PREVIEW, RuntimeEnvironment.PRODUCTION])
def test_deployed_environments_require_cache_url(environment: RuntimeEnvironment) -> None:
    with pytest.raises(ConfigurationError, match="CACHE_URL is required"):
        load_cache_config(environ={}, environment=environment)


@pytest.mark.parametrize("scheme", ["redis", "rediss"])
def test_redis_cache_url_enables_shared_cache(scheme: str) -> None:
    config = load_cache_config(
        environ={"CACHE_URL": f"{scheme}://:secret@cache.example.test:6380/2"},
        environment=RuntimeEnvironment.PRODUCTION,
    )

    assert config == CacheConfig(
        backend="django.core.cache.backends.redis.RedisCache",
        environment=RuntimeEnvironment.PRODUCTION,
        location=f"{scheme}://:secret@cache.example.test:6380/2",
        shared=True,
    )
    assert config.as_django_settings() == {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": f"{scheme}://:secret@cache.example.test:6380/2",
        "KEY_PREFIX": "cultural-currency:production",
        "OPTIONS": {
            "socket_connect_timeout": 1.0,
            "socket_timeout": 1.0,
        },
    }


@pytest.mark.parametrize(
    ("url", "message"),
    [
        ("http://cache.example.test/0", "redis:// or rediss://"),
        ("redis:///0", "Redis host"),
        ("redis://cache.example.test:bad/0", "invalid Redis host or port"),
        ("redis://cache.example.test:0/0", "invalid Redis port"),
        ("redis://cache.example.test//0", "at most one Redis database"),
        ("redis://cache.example.test/0/1", "at most one Redis database"),
        ("redis://cache.example.test/not-a-db", "non-negative integer"),
        ("redis://cache.example.test/0#fragment", "URL fragment"),
        ("redis://cache.example.test/0?broken", "invalid query options"),
        (
            "redis://cache.example.test/0?socket_timeout=30",
            "must not override cache timeout, retry, or TLS verification policy",
        ),
        (
            "redis://cache.example.test/0?retry_on_timeout=true",
            "must not override cache timeout, retry, or TLS verification policy",
        ),
        (
            "rediss://cache.example.test/0?ssl_cert_reqs=none",
            "must not override cache timeout, retry, or TLS verification policy",
        ),
        (
            "rediss://cache.example.test/0?ssl_check_hostname=false",
            "must not override cache timeout, retry, or TLS verification policy",
        ),
    ],
)
def test_invalid_cache_urls_fail_fast(url: str, message: str) -> None:
    with pytest.raises(ConfigurationError, match=message):
        load_cache_config(
            environ={"CACHE_URL": url},
            environment=RuntimeEnvironment.TEST,
        )


def test_cache_credentials_are_redacted_from_repr() -> None:
    config = load_cache_config(
        environ={"CACHE_URL": "redis://:super-secret@cache.example.test/0"},
        environment=RuntimeEnvironment.TEST,
    )

    assert "super-secret" not in repr(config)
