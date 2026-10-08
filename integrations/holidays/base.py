from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


class HolidayDataSourceError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class HolidaySourceObservation:
    country_code: str
    date: date
    name: str
    national_holiday: bool
    subdivision_codes: tuple[str, ...]
    holiday_types: tuple[str, ...]
    source_name: str
    source_url: str
    retrieved_at: datetime
