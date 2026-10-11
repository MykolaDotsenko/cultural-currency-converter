"""One-time installation is atomic, only in explicitly approved nonproduction environments."""

from __future__ import annotations

from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from apps.countries.models import Country, Currency
from apps.culture.models import StoryMoment, TypicalPrice


@pytest.mark.django_db
def test_atomic_bootstrap_seeds_every_core_source_in_one_transaction() -> None:
    output = StringIO()
    call_command("bootstrap_empty_deployment", confirm_empty=True, stdout=output)
    assert "Atomic empty-database bootstrap completed" in output.getvalue()
    assert Country.objects.filter(iso2="FI").exists()
    assert Currency.objects.filter(code="EUR").exists()
    assert StoryMoment.objects.exists()
    assert TypicalPrice.objects.exists()


@pytest.mark.django_db
def test_atomic_bootstrap_rejects_existing_data_without_mutating() -> None:
    call_command("seed_reference_data", stdout=StringIO())
    before = Country.objects.count()
    with pytest.raises(CommandError, match="existing product records"):
        call_command("bootstrap_empty_deployment", confirm_empty=True)
    assert Country.objects.count() == before


@pytest.mark.django_db
def test_atomic_bootstrap_rolls_back_every_seed_on_error() -> None:
    from django.core.management import call_command as django_call_command

    def failing_seed(name, *args, **kwargs):
        if name == "seed_story_data":
            raise RuntimeError("Simulated seed failure")
        return django_call_command(name, *args, **kwargs)

    with (
        patch(
            "apps.countries.management.commands.bootstrap_empty_deployment.call_command",
            side_effect=failing_seed,
        ),
        pytest.raises(RuntimeError, match="Simulated seed failure"),
    ):
        call_command("bootstrap_empty_deployment", confirm_empty=True)

    assert not Country.objects.exists()
    assert not Currency.objects.exists()
    assert not StoryMoment.objects.exists()
    assert not TypicalPrice.objects.exists()


@pytest.mark.django_db
def test_atomic_bootstrap_is_unavailable_without_approval() -> None:
    with pytest.raises(CommandError, match="explicit non-production approval"):
        call_command("bootstrap_empty_deployment")
    assert not Country.objects.exists()


@pytest.mark.django_db
@override_settings(APP_ENV="production")
def test_atomic_bootstrap_cannot_seed_production_even_with_approval() -> None:
    with pytest.raises(CommandError, match="explicit non-production approval"):
        call_command("bootstrap_empty_deployment", confirm_empty=True)
    assert not Country.objects.exists()


@pytest.mark.django_db
@override_settings(APP_ENV="demo")
def test_deployed_sqlite_bootstrap_is_rejected() -> None:
    with pytest.raises(CommandError, match="requires PostgreSQL"):
        call_command("bootstrap_empty_deployment", confirm_empty=True)
    assert not Country.objects.exists()
