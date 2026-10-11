"""Account verification mail can never become enabled by accidental defaults."""

from __future__ import annotations

import pytest

from config.account_mail import load_account_mail_config
from config.environment import ConfigurationError, RuntimeEnvironment


def test_email_verification_is_disabled_by_default():
    config = load_account_mail_config({}, RuntimeEnvironment.PRODUCTION)
    assert config.enabled is False
    assert config.host == ""
    assert config.sender == ""


@pytest.mark.parametrize("value", ["yes", "1", "on", "sometimes"])
def test_ambiguous_enable_flag_fails_closed(value):
    with pytest.raises(ConfigurationError, match="must be true or false"):
        load_account_mail_config(
            {"ACCOUNT_EMAIL_VERIFICATION_ENABLED": value},
            RuntimeEnvironment.PRODUCTION,
        )


def _enabled():
    return {
        "ACCOUNT_EMAIL_VERIFICATION_ENABLED": "true",
        "ACCOUNT_EMAIL_PUBLIC_ORIGIN": "https://money.example.test",
        "ACCOUNT_EMAIL_FROM": "accounts@example.test",
        "ACCOUNT_SMTP_HOST": "smtp.example.test",
        "ACCOUNT_SMTP_PORT": "587",
        "ACCOUNT_SMTP_USER": "mailer",
        "ACCOUNT_SMTP_PASSWORD": "test-placeholder",
        "ACCOUNT_SMTP_USE_TLS": "true",
    }


def test_deployed_verification_requires_explicit_authenticated_tls():
    conf = load_account_mail_config(_enabled(), RuntimeEnvironment.PRODUCTION)
    assert conf.enabled
    assert conf.origin == "https://money.example.test"
    assert conf.tls
    assert conf.port == 587


@pytest.mark.parametrize(
    "key,value",
    [
        ("ACCOUNT_EMAIL_PUBLIC_ORIGIN", "http://money.example.test"),
        ("ACCOUNT_EMAIL_PUBLIC_ORIGIN", "https://money.example.test/path"),
        ("ACCOUNT_EMAIL_PUBLIC_ORIGIN", "https://u:p@money.example.test"),
        ("ACCOUNT_EMAIL_FROM", "not-an-email"),
        ("ACCOUNT_SMTP_HOST", "https://evil.example.test"),
        ("ACCOUNT_SMTP_PORT", "99999"),
        ("ACCOUNT_SMTP_USER", ""),
        ("ACCOUNT_SMTP_PASSWORD", ""),
        ("ACCOUNT_SMTP_USE_TLS", "false"),
    ],
)
def test_invalid_deployment_settings_fail_without_printing_secrets(key, value):
    env = _enabled()
    env[key] = value
    with pytest.raises(ConfigurationError) as error:
        load_account_mail_config(env, RuntimeEnvironment.PRODUCTION)
    assert "test-placeholder" not in str(error.value)


def test_local_can_use_test_mail_transport_without_smtp_credentials():
    env = _enabled()
    env.update(ACCOUNT_SMTP_USER="", ACCOUNT_SMTP_PASSWORD="", ACCOUNT_SMTP_USE_TLS="false")
    config = load_account_mail_config(env, RuntimeEnvironment.TEST)
    assert config.enabled
    assert config.tls is False
