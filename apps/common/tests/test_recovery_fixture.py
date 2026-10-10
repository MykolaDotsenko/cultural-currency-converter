"""Guarded recovery probe must be read-only on verification and never usable in production."""

from __future__ import annotations

from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from apps.travel.models import SavedScenario, SavedScenarioSpendEntry


@pytest.mark.django_db
def test_disposable_recovery_fixture_round_trip() -> None:
    call_command("seed_reference_data", stdout=StringIO())
    call_command("verify_recovery_fixture", phase="prepare", confirm_ci_only=True)
    output = StringIO()
    call_command("verify_recovery_fixture", phase="verify", confirm_ci_only=True, stdout=output)
    assert "owner, saved budget, FX observation, spend" in output.getvalue()
    assert SavedScenario.objects.count() == 1


@pytest.mark.django_db
def test_recovery_fixture_requires_explicit_approval() -> None:
    with pytest.raises(CommandError, match="approved isolated test"):
        call_command("verify_recovery_fixture", phase="prepare")
    assert not get_user_model().objects.exists()


@pytest.mark.django_db
@override_settings(APP_ENV="production")
def test_recovery_fixture_never_writes_in_production() -> None:
    with pytest.raises(CommandError, match="approved isolated test"):
        call_command("verify_recovery_fixture", phase="prepare", confirm_ci_only=True)
    assert not get_user_model().objects.exists()


@pytest.mark.django_db
def test_recovery_fixture_refuses_overwrite() -> None:
    call_command("seed_reference_data", stdout=StringIO())
    call_command("verify_recovery_fixture", phase="prepare", confirm_ci_only=True)
    with pytest.raises(CommandError, match="already exists"):
        call_command("verify_recovery_fixture", phase="prepare", confirm_ci_only=True)
    assert SavedScenario.objects.count() == 1


@pytest.mark.django_db
def test_recovery_fixture_detects_missing_confirmed_spend_without_writing() -> None:
    call_command("seed_reference_data", stdout=StringIO())
    call_command("verify_recovery_fixture", phase="prepare", confirm_ci_only=True)
    SavedScenarioSpendEntry.objects.all().delete()
    with pytest.raises(CommandError, match="integrity check failed"):
        call_command("verify_recovery_fixture", phase="verify", confirm_ci_only=True)


@pytest.mark.django_db
def test_recovery_fixture_fails_read_only_when_missing() -> None:
    with pytest.raises(CommandError, match="integrity check failed"):
        call_command("verify_recovery_fixture", phase="verify", confirm_ci_only=True)
    assert not get_user_model().objects.exists()
