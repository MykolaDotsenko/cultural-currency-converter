import pytest

from apps.exchange.config import FxConfigurationError, load_fx_runtime_config
from apps.exchange.providers.deterministic_test import DeterministicTestFxProvider
from apps.exchange.providers.frankfurter import FrankfurterProvider


def test_fx_runtime_config_defaults_to_https_v2_endpoint():
    config = load_fx_runtime_config({})
    assert config.base_url == "https://api.frankfurter.dev/v2"
    assert config.timeout_seconds == 3.0


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"FRANKFURTER_BASE_URL": "http://example.test/v2"}, "absolute HTTPS"),
        ({"FRANKFURTER_BASE_URL": "https://"}, "absolute HTTPS"),
        (
            {"FRANKFURTER_BASE_URL": "https://user:pass@example.test/v2"},
            "must not contain credentials",
        ),
        (
            {"FRANKFURTER_BASE_URL": "https://example.test/v2?mode=test"},
            "must not contain credentials",
        ),
        ({"FRANKFURTER_TIMEOUT_SECONDS": "slow"}, "must be numeric"),
        ({"FRANKFURTER_TIMEOUT_SECONDS": "30"}, "must be > 0 and <= 10"),
    ],
)
def test_fx_runtime_config_rejects_unsafe_or_invalid_values(values, message):
    with pytest.raises(FxConfigurationError, match=message):
        load_fx_runtime_config(values)


def test_fx_runtime_config_uses_deterministic_fixture_only_in_test_environment():
    config = load_fx_runtime_config(
        {
            "APP_ENV": "test",
            "FX_TEST_FIXTURE_ENABLED": "true",
        }
    )

    assert config.test_fixture_enabled is True
    assert isinstance(config.build_provider(), DeterministicTestFxProvider)


def test_fx_runtime_config_uses_frankfurter_by_default():
    config = load_fx_runtime_config({"APP_ENV": "test"})

    assert config.test_fixture_enabled is False
    assert isinstance(config.build_provider(), FrankfurterProvider)


@pytest.mark.parametrize("environment", ["", "local", "demo", "preview", "production"])
def test_fx_runtime_config_rejects_test_fixture_outside_test(environment):
    values = {"FX_TEST_FIXTURE_ENABLED": "true"}
    if environment:
        values["APP_ENV"] = environment

    with pytest.raises(FxConfigurationError, match="allowed only when APP_ENV=test"):
        load_fx_runtime_config(values)


def test_fx_runtime_config_rejects_invalid_test_fixture_boolean():
    with pytest.raises(FxConfigurationError, match="must be a boolean value"):
        load_fx_runtime_config(
            {
                "APP_ENV": "test",
                "FX_TEST_FIXTURE_ENABLED": "sometimes",
            }
        )
