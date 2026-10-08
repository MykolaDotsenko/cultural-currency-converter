from __future__ import annotations

import json
from datetime import UTC, date, datetime
from http.client import HTTPException
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from integrations.holidays.base import HolidayDataSourceError, HolidaySourceObservation

BASE_URL = "https://nagerholidays.com/api/v4/Holidays"
MAX_RESPONSE_BYTES = 512 * 1024


def _normalized_strings(value: Any, *, field_name: str, max_length: int) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise HolidayDataSourceError(f"Nager.Date {field_name} must be a list.")
    result: list[str] = []
    for raw in value:
        if not isinstance(raw, str):
            raise HolidayDataSourceError(f"Nager.Date {field_name} must contain strings.")
        text = " ".join(raw.split())
        if not text or len(text) > max_length:
            raise HolidayDataSourceError(f"Nager.Date {field_name} contains an invalid value.")
        result.append(text)
    return tuple(dict.fromkeys(result))


def parse_nager_holidays(
    payload: Any,
    *,
    country_code: str,
    year: int,
    retrieved_at: datetime,
    source_url: str,
) -> tuple[HolidaySourceObservation, ...]:
    if not isinstance(payload, list):
        raise HolidayDataSourceError("Nager.Date holiday response must be an array.")

    expected_country = country_code.upper()
    observations: list[HolidaySourceObservation] = []
    seen: set[tuple[date, str]] = set()
    for raw in payload:
        if not isinstance(raw, dict):
            raise HolidayDataSourceError("Nager.Date holiday row must be an object.")

        raw_country = str(raw.get("countryCode") or "").strip().upper()
        if raw_country != expected_country:
            raise HolidayDataSourceError("Nager.Date holiday row has unexpected country scope.")

        try:
            holiday_date = date.fromisoformat(str(raw.get("date") or ""))
        except ValueError as exc:
            raise HolidayDataSourceError("Nager.Date holiday row has an invalid date.") from exc
        if holiday_date.year != year:
            raise HolidayDataSourceError("Nager.Date holiday row is outside the requested year.")

        name = " ".join(str(raw.get("name") or "").split())
        if not name or len(name) > 200:
            raise HolidayDataSourceError("Nager.Date holiday row has an invalid name.")

        national_holiday = raw.get("nationalHoliday")
        if not isinstance(national_holiday, bool):
            raise HolidayDataSourceError("Nager.Date holiday row is missing nationalHoliday scope.")

        subdivision_codes = tuple(
            value.upper()
            for value in _normalized_strings(
                raw.get("subdivisionCodes"),
                field_name="subdivisionCodes",
                max_length=16,
            )
        )
        holiday_types = _normalized_strings(
            raw.get("holidayTypes"),
            field_name="holidayTypes",
            max_length=40,
        )

        identity = (holiday_date, name.casefold())
        if identity in seen:
            raise HolidayDataSourceError("Nager.Date response contains duplicate holiday identity.")
        seen.add(identity)

        observations.append(
            HolidaySourceObservation(
                country_code=expected_country,
                date=holiday_date,
                name=name,
                national_holiday=national_holiday,
                subdivision_codes=subdivision_codes,
                holiday_types=holiday_types,
                source_name="Nager.Date",
                source_url=source_url,
                retrieved_at=retrieved_at,
            )
        )
    return tuple(sorted(observations, key=lambda item: (item.date, item.name)))


class NagerDateHolidayClient:
    def __init__(self, *, timeout_seconds: float = 8.0):
        if not 0 < timeout_seconds <= 30:
            raise ValueError("Nager.Date timeout must be > 0 and <= 30 seconds.")
        self.timeout_seconds = timeout_seconds

    def fetch_year(
        self,
        country_iso2: str,
        year: int,
        *,
        today: date | None = None,
    ) -> tuple[HolidaySourceObservation, ...]:
        code = country_iso2.strip().upper()
        if len(code) != 2 or not code.isascii() or not code.isalpha():
            raise ValueError("Nager.Date country code must be ISO alpha-2.")

        current_year = (today or date.today()).year
        if year < current_year or year > current_year + 5:
            raise ValueError("Nager.Date Community v4 supports current year through +5 years.")

        url = f"{BASE_URL}/{code.lower()}/{year}"
        payload = self._fetch_json(url)
        return parse_nager_holidays(
            payload,
            country_code=code,
            year=year,
            retrieved_at=datetime.now(UTC),
            source_url=url,
        )

    def _fetch_json(self, url: str) -> Any:
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "CulturalCurrencyConverter/0.1 holiday-context-ingestion",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            if exc.code == 404:
                raise HolidayDataSourceError(
                    "Nager.Date has no holiday dataset for this scope."
                ) from exc
            if exc.code == 429:
                raise HolidayDataSourceError("Nager.Date rate limit reached.") from exc
            raise HolidayDataSourceError(f"Nager.Date returned HTTP {exc.code}.") from exc
        except (URLError, HTTPException, TimeoutError, OSError) as exc:
            raise HolidayDataSourceError("Nager.Date request failed.") from exc

        if len(raw) > MAX_RESPONSE_BYTES:
            raise HolidayDataSourceError("Nager.Date response exceeded the size limit.")
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise HolidayDataSourceError("Nager.Date returned malformed JSON.") from exc
