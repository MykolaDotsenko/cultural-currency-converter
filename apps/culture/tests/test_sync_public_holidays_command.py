from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.countries.models import Country
from apps.culture.models import PublicHolidayObservation
from integrations.holidays.base import HolidayDataSourceError, HolidaySourceObservation


@pytest.fixture
def finland(db):
    return Country.objects.create(iso2="FI", iso3="FIN", name="Finland")


def _holiday(year: int) -> HolidaySourceObservation:
    return HolidaySourceObservation(
        country_code="FI",
        date=date(year, 12, 6),
        name="Independence Day",
        national_holiday=True,
        subdivision_codes=(),
        holiday_types=("Public",),
        source_name="Nager.Date",
        source_url=f"https://nagerholidays.com/api/v4/Holidays/fi/{year}",
        retrieved_at=datetime(2026, 10, 8, tzinfo=UTC),
    )


@pytest.mark.django_db
def test_sync_public_holidays_dry_run_rolls_back(monkeypatch, finland):
    monkeypatch.setattr(
        "apps.culture.management.commands.sync_public_holidays.NagerDateHolidayClient.fetch_year",
        lambda self, country_iso2, year, today=None: (_holiday(year),),
    )

    call_command(
        "sync_public_holidays",
        country=["FI"],
        years_ahead=0,
        dry_run=True,
    )

    assert not PublicHolidayObservation.objects.exists()


@pytest.mark.django_db
def test_sync_public_holidays_persists_current_scope(monkeypatch, finland):
    monkeypatch.setattr(
        "apps.culture.management.commands.sync_public_holidays."
        "NagerDateHolidayClient.fetch_year",
        lambda self, country_iso2, year, today=None: (_holiday(year),),
    )

    call_command(
        "sync_public_holidays",
        country=["FIN"],
        years_ahead=0,
    )

    row = PublicHolidayObservation.objects.get()
    assert row.country == finland
    assert row.name == "Independence Day"
    assert row.national_holiday is True


@pytest.mark.django_db
def test_sync_public_holidays_aborts_before_writes_on_provider_failure(
    monkeypatch,
    finland,
):
    def fail(self, country_iso2, year, today=None):
        raise HolidayDataSourceError("upstream unavailable")

    monkeypatch.setattr(
        "apps.culture.management.commands.sync_public_holidays."
        "NagerDateHolidayClient.fetch_year",
        fail,
    )

    with pytest.raises(CommandError, match="aborted before database writes"):
        call_command(
            "sync_public_holidays",
            country=["FI"],
            years_ahead=0,
        )

    assert not PublicHolidayObservation.objects.exists()
