from __future__ import annotations

from pathlib import Path

import pytest

from config.environment import ConfigurationError, RuntimeEnvironment
from config.storage import MediaStorageMode, load_media_storage_config

BASE_DIR = Path("/tmp/cultural-currency-test")


def test_local_defaults_to_filesystem_storage() -> None:
    config = load_media_storage_config(
        environ={},
        environment=RuntimeEnvironment.LOCAL,
        base_dir=BASE_DIR,
    )

    assert config.mode is MediaStorageMode.FILESYSTEM
    assert config.durable is False
    assert config.public_origin is None
    assert config.media_root == BASE_DIR / "media"
    assert config.media_url == "/media/"
    assert config.as_django_storage() == {
        "BACKEND": "django.core.files.storage.FileSystemStorage"
    }


@pytest.mark.parametrize(
    "environment",
    [RuntimeEnvironment.TEST, RuntimeEnvironment.DEMO, RuntimeEnvironment.PREVIEW],
)
def test_nonproduction_environments_may_use_ephemeral_filesystem(
    environment: RuntimeEnvironment,
) -> None:
    config = load_media_storage_config(
        environ={},
        environment=environment,
        base_dir=BASE_DIR,
    )

    assert config.mode is MediaStorageMode.FILESYSTEM


def test_production_requires_explicit_durable_media_storage() -> None:
    with pytest.raises(ConfigurationError, match="MEDIA_STORAGE_BACKEND=s3 is required"):
        load_media_storage_config(
            environ={},
            environment=RuntimeEnvironment.PRODUCTION,
            base_dir=BASE_DIR,
        )

    with pytest.raises(ConfigurationError, match="filesystem is not allowed"):
        load_media_storage_config(
            environ={"MEDIA_STORAGE_BACKEND": "filesystem"},
            environment=RuntimeEnvironment.PRODUCTION,
            base_dir=BASE_DIR,
        )


@pytest.mark.parametrize("value", ["disk", "bucket", "object-store"])
def test_unknown_media_storage_backend_fails_fast(value: str) -> None:
    with pytest.raises(ConfigurationError, match="must be filesystem or s3"):
        load_media_storage_config(
            environ={"MEDIA_STORAGE_BACKEND": value},
            environment=RuntimeEnvironment.TEST,
            base_dir=BASE_DIR,
        )


@pytest.mark.parametrize(
    "missing",
    ["MEDIA_S3_BUCKET", "MEDIA_S3_REGION", "MEDIA_S3_PUBLIC_ORIGIN"],
)
def test_s3_storage_requires_explicit_public_configuration(missing: str) -> None:
    environ = {
        "MEDIA_STORAGE_BACKEND": "s3",
        "MEDIA_S3_BUCKET": "currency-media",
        "MEDIA_S3_REGION": "eu-central-1",
        "MEDIA_S3_PUBLIC_ORIGIN": "https://media.example.test",
    }
    environ.pop(missing)

    with pytest.raises(ConfigurationError, match=missing):
        load_media_storage_config(
            environ=environ,
            environment=RuntimeEnvironment.TEST,
            base_dir=BASE_DIR,
        )


@pytest.mark.parametrize(
    "origin",
    [
        "http://media.example.test",
        "https://user:pass@media.example.test",
        "https://media.example.test/assets",
        "https://media.example.test?token=secret",
        "https://media.example.test#fragment",
        "not-a-url",
    ],
)
def test_s3_public_origin_requires_clean_https_origin(origin: str) -> None:
    with pytest.raises(ConfigurationError, match="must be an HTTPS origin"):
        load_media_storage_config(
            environ={
                "MEDIA_STORAGE_BACKEND": "s3",
                "MEDIA_S3_BUCKET": "currency-media",
                "MEDIA_S3_REGION": "eu-central-1",
                "MEDIA_S3_PUBLIC_ORIGIN": origin,
            },
            environment=RuntimeEnvironment.TEST,
            base_dir=BASE_DIR,
        )


def test_s3_storage_builds_public_immutable_media_backend() -> None:
    config = load_media_storage_config(
        environ={
            "MEDIA_STORAGE_BACKEND": "s3",
            "MEDIA_S3_BUCKET": "currency-media",
            "MEDIA_S3_REGION": "eu-central-1",
            "MEDIA_S3_PUBLIC_ORIGIN": "https://media.example.test/",
            "MEDIA_S3_ENDPOINT_URL": "https://objects.example.test",
        },
        environment=RuntimeEnvironment.PRODUCTION,
        base_dir=BASE_DIR,
    )

    assert config.mode is MediaStorageMode.S3
    assert config.durable is True
    assert config.public_origin == "https://media.example.test"
    assert config.media_url == "https://media.example.test/media/"
    assert config.as_django_storage() == {
        "BACKEND": "storages.s3.S3Storage",
        "OPTIONS": {
            "bucket_name": "currency-media",
            "region_name": "eu-central-1",
            "location": "media",
            "custom_domain": "media.example.test",
            "url_protocol": "https:",
            "querystring_auth": False,
            "default_acl": None,
            "file_overwrite": True,
            "object_parameters": {
                "CacheControl": "public, max-age=31536000, immutable",
            },
            "endpoint_url": "https://objects.example.test",
        },
    }


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://objects.example.test",
        "https://objects.example.test/path",
        "https://objects.example.test?key=value",
    ],
)
def test_s3_endpoint_requires_clean_https_origin(endpoint: str) -> None:
    with pytest.raises(ConfigurationError, match="MEDIA_S3_ENDPOINT_URL"):
        load_media_storage_config(
            environ={
                "MEDIA_STORAGE_BACKEND": "s3",
                "MEDIA_S3_BUCKET": "currency-media",
                "MEDIA_S3_REGION": "eu-central-1",
                "MEDIA_S3_PUBLIC_ORIGIN": "https://media.example.test",
                "MEDIA_S3_ENDPOINT_URL": endpoint,
            },
            environment=RuntimeEnvironment.TEST,
            base_dir=BASE_DIR,
        )
