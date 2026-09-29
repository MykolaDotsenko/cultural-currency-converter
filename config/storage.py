from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from config.environment import ConfigurationError, RuntimeEnvironment


class MediaStorageMode(StrEnum):
    FILESYSTEM = "filesystem"
    S3 = "s3"


@dataclass(frozen=True, slots=True)
class MediaStorageConfig:
    """Normalized managed-media storage settings."""

    mode: MediaStorageMode
    backend: str
    media_root: Path
    public_origin: str | None = None
    options: Mapping[str, Any] = field(default_factory=dict, repr=False)

    @property
    def durable(self) -> bool:
        return self.mode is MediaStorageMode.S3

    def as_django_storage(self) -> dict[str, Any]:
        storage: dict[str, Any] = {"BACKEND": self.backend}
        if self.options:
            storage["OPTIONS"] = dict(self.options)
        return storage

    @property
    def media_url(self) -> str:
        if self.public_origin:
            return f"{self.public_origin}/media/"
        return "/media/"


def _optional(environ: Mapping[str, str], name: str) -> str | None:
    value = environ.get(name)
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _required(environ: Mapping[str, str], name: str) -> str:
    value = _optional(environ, name)
    if value is None:
        raise ConfigurationError(f"{name} is required when MEDIA_STORAGE_BACKEND=s3.")
    return value


def _https_origin(value: str, *, field_name: str) -> str:
    parsed = urlparse(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ConfigurationError(f"{field_name} contains an invalid port.") from exc

    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise ConfigurationError(
            f"{field_name} must be an HTTPS origin without credentials, path, query or fragment."
        )

    suffix = f":{port}" if port and port != 443 else ""
    return f"https://{parsed.hostname}{suffix}"


def load_media_storage_config(
    *,
    environ: Mapping[str, str],
    environment: RuntimeEnvironment,
    base_dir: Path,
) -> MediaStorageConfig:
    """Use local files for development/demo and require durable object storage in production."""

    raw_mode = _optional(environ, "MEDIA_STORAGE_BACKEND")
    if raw_mode is None:
        if environment is RuntimeEnvironment.PRODUCTION:
            raise ConfigurationError(
                "MEDIA_STORAGE_BACKEND=s3 is required in production for durable managed media."
            )
        mode = MediaStorageMode.FILESYSTEM
    else:
        try:
            mode = MediaStorageMode(raw_mode.lower())
        except ValueError as exc:
            raise ConfigurationError("MEDIA_STORAGE_BACKEND must be filesystem or s3.") from exc

    media_root = base_dir / "media"

    if mode is MediaStorageMode.FILESYSTEM:
        if environment is RuntimeEnvironment.PRODUCTION:
            raise ConfigurationError(
                "MEDIA_STORAGE_BACKEND=filesystem is not allowed in production."
            )
        return MediaStorageConfig(
            mode=mode,
            backend="django.core.files.storage.FileSystemStorage",
            media_root=media_root,
        )

    bucket = _required(environ, "MEDIA_S3_BUCKET")
    region = _required(environ, "MEDIA_S3_REGION")
    public_origin = _https_origin(
        _required(environ, "MEDIA_S3_PUBLIC_ORIGIN"),
        field_name="MEDIA_S3_PUBLIC_ORIGIN",
    )
    endpoint = _optional(environ, "MEDIA_S3_ENDPOINT_URL")

    options: dict[str, Any] = {
        "bucket_name": bucket,
        "region_name": region,
        "location": "media",
        "custom_domain": public_origin.removeprefix("https://"),
        "url_protocol": "https:",
        "querystring_auth": False,
        "default_acl": None,
        "file_overwrite": True,
        "object_parameters": {
            "CacheControl": "public, max-age=31536000, immutable",
        },
    }
    if endpoint is not None:
        options["endpoint_url"] = _https_origin(
            endpoint,
            field_name="MEDIA_S3_ENDPOINT_URL",
        )

    return MediaStorageConfig(
        mode=mode,
        backend="storages.s3.S3Storage",
        media_root=media_root,
        public_origin=public_origin,
        options=options,
    )
