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
        "apps.culture.management.commands.sync_public_holidays.NagerDateHolidayClient.fetch_year",
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
        "apps.culture.management.commands.sync_public_holidays.NagerDateHolidayClient.fetch_year",
        fail,
    )

    with pytest.raises(CommandError, match="aborted before database writes"):
        call_command(
            "sync_public_holidays",
            country=["FI"],
            years_ahead=0,
        )

    assert not PublicHolidayObservation.objects.exists()


@pytest.mark.django_db
def test_scheduled_holiday_refresh_rejects_empty_scope_without_unpublishing(monkeypatch, finland):
    monkeypatch.setattr(
        "apps.culture.management.commands.sync_public_holidays.NagerDateHolidayClient.fetch_year",
        lambda self, country_iso2, year, today=None: (_holiday(year),),
    )
    call_command("sync_public_holidays", country=["FI"], years_ahead=0)
    before = tuple(PublicHolidayObservation.objects.values_list("id", "is_published"))
    assert len(before) == 1

    monkeypatch.setattr(
        "apps.culture.management.commands.sync_public_holidays.NagerDateHolidayClient.fetch_year",
        lambda self, country_iso2, year, today=None: (),
    )
    with pytest.raises(CommandError, match="empty country/year scope"):
        call_command(
            "sync_public_holidays",
            country=["FI"],
            years_ahead=0,
            require_nonempty_scopes=True,
        )
    assert tuple(PublicHolidayObservation.objects.values_list("id", "is_published")) == before


@pytest.mark.django_db
def test_scheduled_holiday_refresh_rejects_any_empty_year_atomically(monkeypatch, finland):
    from django.utils import timezone

    current_year = timezone.localdate().year
    monkeypatch.setattr(
        "apps.culture.management.commands.sync_public_holidays.NagerDateHolidayClient.fetch_year",
        lambda self, country_iso2, year, today=None: (
            (_holiday(year),) if year == current_year else ()
        ),
    )
    with pytest.raises(CommandError, match="empty country/year scope"):
        call_command(
            "sync_public_holidays",
            country=["FI"],
            years_ahead=1,
            require_nonempty_scopes=True,
        )

    assert not PublicHolidayObservation.objects.exists()


@pytest.mark.django_db
def test_holiday_dry_run_reports_country_year_aggregates_without_persisting(
    monkeypatch, finland, caplog
):
    monkeypatch.setattr(
        "apps.culture.management.commands.sync_public_holidays.NagerDateHolidayClient.fetch_year",
        lambda self, country_iso2, year, today=None: (_holiday(year),),
    )
    with caplog.at_level("INFO", logger="cultural_currency.jobs"):
        call_command("sync_public_holidays", country=["FI"], years_ahead=0, dry_run=True)

    events = [r for r in caplog.records if r.getMessage() == "background_job_result"]
    assert len(events) == 1
    assert events[0].job == "public_holidays"
    assert events[0].outcome == "success"
    assert events[0].dry_run is True
    assert events[0].records_processed == 1
    assert events[0].records_created == 1
    assert events[0].records_updated == 0
    assert events[0].records_retired == 0
    assert not PublicHolidayObservation.objects.exists()
