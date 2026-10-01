from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from config.environment import ConfigurationError

_DEFAULT_PROVIDER = "google"
_DEFAULT_TEXT_MODEL = "gemini-3.1-flash-lite"
_DEFAULT_FALLBACK_MODE = "deterministic"
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off"})


@dataclass(frozen=True, slots=True)
class AIConfig:
    provider: str
    text_model: str
    runtime_explanation_enabled: bool
    runtime_test_fixture_enabled: bool
    camera_extraction_enabled: bool
    editorial_generation_enabled: bool
    image_generation_enabled: bool
    fallback_mode: str
    timeout_seconds: float
    max_attempts: int
    gemini_api_key: str

    @property
    def has_live_runtime_explanation(self) -> bool:
        return self.runtime_explanation_enabled and bool(self.gemini_api_key)

    @property
    def has_live_camera_extraction(self) -> bool:
        return self.camera_extraction_enabled and bool(self.gemini_api_key)


def _optional(environ: Mapping[str, str], name: str) -> str | None:
    value = environ.get(name)
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _parse_bool(
    environ: Mapping[str, str],
    name: str,
    *,
    default: bool,
) -> bool:
    raw = _optional(environ, name)
    if raw is None:
        return default
    normalized = raw.casefold()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    raise ConfigurationError(f"{name} must be a boolean value.")


def _parse_runtime_test_fixture_enabled(values: Mapping[str, str]) -> bool:
    raw = _optional(values, "AI_RUNTIME_TEST_FIXTURE_ENABLED")
    if raw is None:
        return False
    normalized = raw.casefold()
    if normalized in _FALSE_VALUES:
        return False
    if normalized not in _TRUE_VALUES:
        raise ConfigurationError("AI_RUNTIME_TEST_FIXTURE_ENABLED must be a boolean value.")
    if (_optional(values, "APP_ENV") or "").casefold() != "test":
        raise ConfigurationError(
            "AI_RUNTIME_TEST_FIXTURE_ENABLED is allowed only when APP_ENV=test."
        )
    return True


def _parse_timeout(environ: Mapping[str, str]) -> float:
    raw = _optional(environ, "AI_TIMEOUT_SECONDS") or "5"
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigurationError("AI_TIMEOUT_SECONDS must be numeric.") from exc
    if not 0.5 <= value <= 15:
        raise ConfigurationError("AI_TIMEOUT_SECONDS must be between 0.5 and 15 seconds.")
    return value


def _parse_attempts(environ: Mapping[str, str]) -> int:
    raw = _optional(environ, "AI_MAX_ATTEMPTS") or "2"
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigurationError("AI_MAX_ATTEMPTS must be an integer.") from exc
    if value not in {1, 2}:
        raise ConfigurationError("AI_MAX_ATTEMPTS must be 1 or 2.")
    return value


def load_ai_config(environ: Mapping[str, str] | None = None) -> AIConfig:
    values = os.environ if environ is None else environ
    provider = (_optional(values, "AI_PROVIDER") or _DEFAULT_PROVIDER).casefold()
    model = _optional(values, "AI_TEXT_MODEL") or _DEFAULT_TEXT_MODEL
    fallback_mode = (_optional(values, "AI_FALLBACK_MODE") or _DEFAULT_FALLBACK_MODE).casefold()
    runtime_enabled = _parse_bool(
        values,
        "AI_RUNTIME_EXPLANATION_ENABLED",
        default=False,
    )
    runtime_test_fixture_enabled = _parse_runtime_test_fixture_enabled(values)
    camera_enabled = _parse_bool(
        values,
        "AI_CAMERA_EXTRACTION_ENABLED",
        default=False,
    )
    editorial_enabled = _parse_bool(
        values,
        "AI_EDITORIAL_GENERATION_ENABLED",
        default=False,
    )
    image_enabled = _parse_bool(
        values,
        "AI_IMAGE_GENERATION_ENABLED",
        default=False,
    )
    api_key = _optional(values, "GEMINI_API_KEY") or ""

    if provider != _DEFAULT_PROVIDER:
        raise ConfigurationError("AI_PROVIDER must be 'google' for the PR7B runtime capability.")
    if model != _DEFAULT_TEXT_MODEL:
        raise ConfigurationError(
            "AI_TEXT_MODEL must remain gemini-3.1-flash-lite until a documented eval promotion."
        )
    if fallback_mode != _DEFAULT_FALLBACK_MODE:
        raise ConfigurationError("AI_FALLBACK_MODE must be 'deterministic'.")
    if editorial_enabled:
        raise ConfigurationError(
            "AI_EDITORIAL_GENERATION_ENABLED is not available until its review workflow ships."
        )
    if image_enabled:
        raise ConfigurationError(
            "AI_IMAGE_GENERATION_ENABLED is disabled in the public runtime architecture."
        )
    if runtime_test_fixture_enabled and not runtime_enabled:
        raise ConfigurationError(
            "AI_RUNTIME_TEST_FIXTURE_ENABLED requires AI_RUNTIME_EXPLANATION_ENABLED=true."
        )
    live_runtime_requires_key = runtime_enabled and not runtime_test_fixture_enabled
    if (live_runtime_requires_key or camera_enabled) and not api_key:
        raise ConfigurationError(
            "GEMINI_API_KEY is required when live runtime AI or camera extraction is enabled."
        )

    return AIConfig(
        provider=provider,
        text_model=model,
        runtime_explanation_enabled=runtime_enabled,
        runtime_test_fixture_enabled=runtime_test_fixture_enabled,
        camera_extraction_enabled=camera_enabled,
        editorial_generation_enabled=editorial_enabled,
        image_generation_enabled=image_enabled,
        fallback_mode=fallback_mode,
        timeout_seconds=_parse_timeout(values),
        max_attempts=_parse_attempts(values),
        gemini_api_key=api_key,
    )
