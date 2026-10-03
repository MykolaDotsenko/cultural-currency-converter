from __future__ import annotations

import pytest

from config.ai import load_ai_config
from config.environment import ConfigurationError


def test_ai_config_defaults_to_disabled_without_secret():
    config = load_ai_config({})

    assert config.provider == "google"
    assert config.text_model == "gemini-3.1-flash-lite"
    assert config.runtime_explanation_enabled is False
    assert config.runtime_test_fixture_enabled is False
    assert config.camera_extraction_enabled is False
    assert config.camera_test_fixture_enabled is False
    assert config.gemini_api_key == ""
    assert config.fallback_mode == "deterministic"
    assert config.timeout_seconds == 5
    assert config.max_attempts == 2


def test_ai_runtime_feature_requires_key_only_when_enabled():
    with pytest.raises(ConfigurationError, match="GEMINI_API_KEY"):
        load_ai_config({"AI_RUNTIME_EXPLANATION_ENABLED": "true"})

    config = load_ai_config(
        {
            "AI_RUNTIME_EXPLANATION_ENABLED": "true",
            "GEMINI_API_KEY": "server-secret",
        }
    )
    assert config.has_live_runtime_explanation is True


def test_runtime_test_fixture_is_test_only_and_does_not_require_gemini_key():
    config = load_ai_config(
        {
            "APP_ENV": "test",
            "AI_RUNTIME_EXPLANATION_ENABLED": "true",
            "AI_RUNTIME_TEST_FIXTURE_ENABLED": "true",
        }
    )

    assert config.runtime_explanation_enabled is True
    assert config.runtime_test_fixture_enabled is True
    assert config.gemini_api_key == ""
    assert config.has_live_runtime_explanation is False


def test_runtime_test_fixture_is_rejected_outside_test_environment():
    with pytest.raises(ConfigurationError, match="allowed only when APP_ENV=test"):
        load_ai_config(
            {
                "APP_ENV": "production",
                "AI_RUNTIME_EXPLANATION_ENABLED": "true",
                "AI_RUNTIME_TEST_FIXTURE_ENABLED": "true",
            }
        )


def test_runtime_test_fixture_requires_runtime_feature_flag():
    with pytest.raises(ConfigurationError, match="requires AI_RUNTIME_EXPLANATION_ENABLED"):
        load_ai_config(
            {
                "APP_ENV": "test",
                "AI_RUNTIME_TEST_FIXTURE_ENABLED": "true",
            }
        )


def test_camera_extraction_has_separate_opt_in_and_requires_server_key():
    with pytest.raises(ConfigurationError, match="GEMINI_API_KEY"):
        load_ai_config({"AI_CAMERA_EXTRACTION_ENABLED": "true"})

    config = load_ai_config(
        {
            "AI_CAMERA_EXTRACTION_ENABLED": "true",
            "GEMINI_API_KEY": "server-secret",
        }
    )

    assert config.camera_extraction_enabled is True
    assert config.has_live_camera_extraction is True
    assert config.runtime_explanation_enabled is False


def test_camera_test_fixture_is_test_only_and_does_not_require_gemini_key():
    config = load_ai_config(
        {
            "APP_ENV": "test",
            "AI_CAMERA_EXTRACTION_ENABLED": "true",
            "AI_CAMERA_TEST_FIXTURE_ENABLED": "true",
        }
    )

    assert config.camera_extraction_enabled is True
    assert config.camera_test_fixture_enabled is True
    assert config.gemini_api_key == ""
    assert config.has_live_camera_extraction is False


def test_camera_test_fixture_is_rejected_outside_test_environment():
    with pytest.raises(ConfigurationError, match="allowed only when APP_ENV=test"):
        load_ai_config(
            {
                "APP_ENV": "production",
                "AI_CAMERA_EXTRACTION_ENABLED": "true",
                "AI_CAMERA_TEST_FIXTURE_ENABLED": "true",
            }
        )


def test_camera_test_fixture_requires_camera_feature_flag():
    with pytest.raises(ConfigurationError, match="requires AI_CAMERA_EXTRACTION_ENABLED"):
        load_ai_config(
            {
                "APP_ENV": "test",
                "AI_CAMERA_TEST_FIXTURE_ENABLED": "true",
            }
        )


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("AI_PROVIDER", "openai", "AI_PROVIDER"),
        ("AI_TEXT_MODEL", "gemini-3.8-flash", "AI_TEXT_MODEL"),
        ("AI_FALLBACK_MODE", "paid", "AI_FALLBACK_MODE"),
        ("AI_EDITORIAL_GENERATION_ENABLED", "true", "EDITORIAL"),
        ("AI_IMAGE_GENERATION_ENABLED", "true", "IMAGE"),
        ("AI_RUNTIME_EXPLANATION_ENABLED", "maybe", "boolean"),
        ("AI_CAMERA_EXTRACTION_ENABLED", "maybe", "boolean"),
        ("AI_CAMERA_TEST_FIXTURE_ENABLED", "maybe", "boolean"),
    ],
)
def test_ai_config_rejects_unpromoted_or_unsafe_runtime_configuration(name, value, message):
    with pytest.raises(ConfigurationError, match=message):
        load_ai_config({name: value})


@pytest.mark.parametrize("value", ["0.4", "16", "not-a-number"])
def test_ai_config_rejects_invalid_timeout(value):
    with pytest.raises(ConfigurationError, match="AI_TIMEOUT_SECONDS"):
        load_ai_config({"AI_TIMEOUT_SECONDS": value})


@pytest.mark.parametrize("value", ["0", "3", "1.5"])
def test_ai_config_rejects_invalid_attempt_count(value):
    with pytest.raises(ConfigurationError, match="AI_MAX_ATTEMPTS"):
        load_ai_config({"AI_MAX_ATTEMPTS": value})


def test_ai_config_accepts_single_attempt_and_bounded_timeout():
    config = load_ai_config(
        {
            "AI_TIMEOUT_SECONDS": "3.5",
            "AI_MAX_ATTEMPTS": "1",
        }
    )

    assert config.timeout_seconds == 3.5
    assert config.max_attempts == 1
