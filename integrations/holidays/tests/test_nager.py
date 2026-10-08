from __future__ import annotations

from datetime import UTC, datetime

import pytest

from integrations.holidays.base import HolidayDataSourceError
from integrations.holidays.nager import parse_nager_holidays


def test_nager_v4_parser_preserves_national_and_subdivision_scope():
    payload = [
        {
            "date": "2026-12-06",
            "name": "Independence Day",
            "countryCode": "FI",
            "nationalHoliday": True,
            "subdivisionCodes": [],
            "holidayTypes": ["Public"],
        },
        {
            "date": "2026-11-07",
            "name": "Example regional holiday",
            "countryCode": "FI",
            "nationalHoliday": False,
            "subdivisionCodes": ["FI-01"],
            "holidayTypes": ["Public"],
        },
    ]

    observations = parse_nager_holidays(
        payload,
        country_code="FI",
        year=2026,
        retrieved_at=datetime(2026, 10, 8, tzinfo=UTC),
        source_url="https://nagerholidays.com/api/v4/Holidays/fi/2026",
    )

    assert len(observations) == 2
    regional = observations[0]
    national = observations[1]
    assert regional.name == "Example regional holiday"
    assert regional.national_holiday is False
    assert regional.subdivision_codes == ("FI-01",)
    assert national.name == "Independence Day"
    assert national.national_holiday is True
    assert national.holiday_types == ("Public",)


def test_nager_parser_fails_closed_on_country_mismatch():
    payload = [
        {
            "date": "2026-12-06",
            "name": "Independence Day",
            "countryCode": "SE",
            "nationalHoliday": True,
            "subdivisionCodes": [],
            "holidayTypes": ["Public"],
        }
    ]

    with pytest.raises(HolidayDataSourceError, match="unexpected country"):
        parse_nager_holidays(
            payload,
            country_code="FI",
            year=2026,
            retrieved_at=datetime(2026, 10, 8, tzinfo=UTC),
            source_url="https://nagerholidays.com/api/v4/Holidays/fi/2026",
        )


def test_nager_parser_rejects_duplicate_identity():
    row = {
        "date": "2026-12-06",
        "name": "Independence Day",
        "countryCode": "FI",
        "nationalHoliday": True,
        "subdivisionCodes": [],
        "holidayTypes": ["Public"],
    }

    with pytest.raises(HolidayDataSourceError, match="duplicate"):
        parse_nager_holidays(
            [row, dict(row)],
            country_code="FI",
            year=2026,
            retrieved_at=datetime(2026, 10, 8, tzinfo=UTC),
            source_url="https://nagerholidays.com/api/v4/Holidays/fi/2026",
        )
