from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from apps.countries.models import Country, Currency
from apps.culture.calendar import build_calendar_context, reconcile_public_holiday_year
from apps.culture.models import PublicHolidayObservation
from apps.culture.presentation import build_destination_context_component
from apps.culture.services import build_destination_context
from integrations.holidays.base import HolidaySourceObservation


@pytest.fixture
def finland(db):
    return Country.objects.create(iso2="FI", iso3="FIN", name="Finland")


def _source_holiday(
    *,
    name: str,
    holiday_date: date,
    national: bool = True,
    subdivisions: tuple[str, ...] = (),
) -> HolidaySourceObservation:
    return HolidaySourceObservation(
        country_code="FI",
        date=holiday_date,
        name=name,
        national_holiday=national,
        subdivision_codes=subdivisions,
        holiday_types=("Public",),
        source_name="Nager.Date",
        source_url=f"https://nagerholidays.com/api/v4/Holidays/fi/{holiday_date.year}",
        retrieved_at=datetime(2026, 10, 8, tzinfo=UTC),
    )


@pytest.mark.django_db
def test_calendar_context_exposes_only_national_holidays(finland):
    for observation in (
        _source_holiday(name="Today Holiday", holiday_date=date(2026, 10, 8)),
        _source_holiday(
            name="Regional Holiday",
            holiday_date=date(2026, 10, 9),
            national=False,
            subdivisions=("FI-01",),
        ),
        _source_holiday(name="Next Holiday", holiday_date=date(2026, 10, 20)),
        _source_holiday(name="Too Far", holiday_date=date(2026, 12, 6)),
    ):
        reconcile_public_holiday_year(
            country=finland,
            year=2026,
            observations=(
                *tuple(
                    _source_holiday(
                        name=row.name,
                        holiday_date=row.date,
                        national=row.national_holiday,
                        subdivisions=tuple(row.subdivision_codes),
                    )
                    for row in PublicHolidayObservation.objects.filter(country=finland)
                ),
                observation,
            ),
        )

    context = build_calendar_context(
        country=finland,
        as_of=date(2026, 10, 8),
        window_days=30,
    )

    assert context is not None
    assert [item.name for item in context.today] == ["Today Holiday"]
    assert [item.name for item in context.upcoming] == ["Next Holiday"]
    assert "Regional Holiday" not in {
        item.name for item in (*context.today, *context.upcoming)
    }


@pytest.mark.django_db
def test_reconcile_holiday_year_retires_removed_upstream_rows(finland):
    first = (
        _source_holiday(name="Holiday A", holiday_date=date(2026, 12, 6)),
        _source_holiday(name="Holiday B", holiday_date=date(2026, 12, 25)),
    )
    created, updated, retired = reconcile_public_holiday_year(
        country=finland,
        year=2026,
        observations=first,
    )

    assert (created, updated, retired) == (2, 0, 0)

    second = (
        _source_holiday(name="Holiday A", holiday_date=date(2026, 12, 6)),
    )
    created, updated, retired = reconcile_public_holiday_year(
        country=finland,
        year=2026,
        observations=second,
    )

    assert (created, updated, retired) == (0, 1, 1)
    assert PublicHolidayObservation.objects.get(name="Holiday A").is_published is True
    assert PublicHolidayObservation.objects.get(name="Holiday B").is_published is False


@pytest.mark.django_db
def test_destination_context_presents_neutral_holiday_guidance(finland):
    euro = Currency.objects.create(code="EUR", name="Euro")
    reconcile_public_holiday_year(
        country=finland,
        year=2026,
        observations=(
            _source_holiday(name="Independence Day", holiday_date=date(2026, 12, 6)),
        ),
    )

    context = build_destination_context(
        country_code="FI",
        converted_amount=Decimal("100"),
        quote_currency=euro.code,
        as_of=date(2026, 12, 1),
    )

    assert context is not None
    assert context.calendar is not None
    component = build_destination_context_component(context, historical=False)
    assert component["calendar"] is not None
    assert component["calendar"]["today"] == []
    assert component["calendar"]["upcoming"][0]["name"] == "Independence Day"
    assert component["calendar"]["upcoming"][0]["date"] == "6 Dec 2026"
