from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from http.client import HTTPException
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request

from integrations.economic_data.base import EconomicDataSourceError, EconomicSourceObservation
from integrations.http_transport import make_pinned_https_urlopen

BASE_URL = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"
urlopen = make_pinned_https_urlopen("ec.europa.eu")
HICP_DATASET = "prc_hicp_minr"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


def _category_positions(payload: dict[str, Any], dimension_id: str) -> dict[str, int]:
    dimension = payload.get("dimension")
    if not isinstance(dimension, dict):
        raise EconomicDataSourceError("Eurostat response is missing dimensions.")
    raw_dimension = dimension.get(dimension_id)
    if not isinstance(raw_dimension, dict):
        raise EconomicDataSourceError(f"Eurostat response is missing {dimension_id} dimension.")
    category = raw_dimension.get("category")
    if not isinstance(category, dict):
        raise EconomicDataSourceError("Eurostat dimension is missing categories.")
    index = category.get("index")
    if isinstance(index, dict):
        result: dict[str, int] = {}
        for key, value in index.items():
            if isinstance(value, int) and value >= 0:
                result[str(key)] = value
        return result
    if isinstance(index, list):
        return {str(key): position for position, key in enumerate(index)}
    raise EconomicDataSourceError("Eurostat category index has an unsupported shape.")


def _value_at(payload: dict[str, Any], flat_index: int) -> Any:
    values = payload.get("value")
    if isinstance(values, list):
        return values[flat_index] if flat_index < len(values) else None
    if isinstance(values, dict):
        return values.get(str(flat_index))
    raise EconomicDataSourceError("Eurostat response is missing observation values.")


def _parse_month(value: str) -> date | None:
    try:
        year_text, month_text = value.split("-", 1)
        year = int(year_text)
        month = int(month_text)
        return date(year, month, 1)
    except (TypeError, ValueError):
        return None


def parse_eurostat_hicp(
    payload: Any,
    *,
    country_code: str,
    retrieved_at: datetime,
    source_url: str,
) -> EconomicSourceObservation | None:
    if not isinstance(payload, dict):
        raise EconomicDataSourceError("Eurostat response must be a JSON-stat object.")

    dimension_ids = payload.get("id")
    sizes = payload.get("size")
    if not isinstance(dimension_ids, list) or not isinstance(sizes, list):
        raise EconomicDataSourceError("Eurostat response is missing JSON-stat dimension metadata.")
    if len(dimension_ids) != len(sizes) or not dimension_ids:
        raise EconomicDataSourceError("Eurostat JSON-stat dimensions are inconsistent.")
    if "time" not in dimension_ids:
        raise EconomicDataSourceError("Eurostat HICP response is missing time.")

    try:
        normalized_sizes = [int(size) for size in sizes]
    except (TypeError, ValueError) as exc:
        raise EconomicDataSourceError("Eurostat JSON-stat dimension sizes are invalid.") from exc

    time_axis = dimension_ids.index("time")
    for position, size in enumerate(normalized_sizes):
        if position != time_axis and size != 1:
            raise EconomicDataSourceError(
                "Eurostat HICP query returned ambiguous non-time dimensions."
            )

    time_positions = _category_positions(payload, "time")
    stride = 1
    for size in normalized_sizes[time_axis + 1 :]:
        stride *= size

    candidates: list[tuple[date, Decimal]] = []
    for raw_period, coordinate in time_positions.items():
        period = _parse_month(raw_period)
        if period is None or period > retrieved_at.date():
            continue
        raw_value = _value_at(payload, coordinate * stride)
        if raw_value is None:
            continue
        try:
            value = Decimal(str(raw_value))
        except (InvalidOperation, TypeError, ValueError):
            continue
        if not value.is_finite():
            continue
        candidates.append((period, value))

    if not candidates:
        return None

    period, value = max(candidates, key=lambda item: item[0])
    return EconomicSourceObservation(
        country_code=country_code.upper(),
        indicator="inflation_yoy",
        category="all_items",
        value=value,
        unit="percent",
        benchmark_label="",
        period_start=period,
        frequency="monthly",
        observation_status="unknown",
        source="eurostat",
        source_dataset=HICP_DATASET,
        source_name="Eurostat",
        source_url=source_url,
        retrieved_at=retrieved_at,
    )


class EurostatEconomicClient:
    def __init__(self, *, timeout_seconds: float = 8.0):
        if not 0 < timeout_seconds <= 30:
            raise ValueError("Eurostat timeout must be > 0 and <= 30 seconds.")
        self.timeout_seconds = timeout_seconds

    def fetch_country(self, country_iso2: str) -> tuple[EconomicSourceObservation, ...]:
        code = country_iso2.strip().upper()
        if len(code) != 2 or not code.isascii() or not code.isalpha():
            raise ValueError("Eurostat country code must be ISO alpha-2.")

        params = urlencode(
            {
                "lang": "en",
                "freq": "M",
                "unit": "RCH_A",
                "coicop18": "TOTAL",
                "geo": code,
            }
        )
        url = f"{BASE_URL}/{HICP_DATASET}?{params}"
        payload = self._fetch_json(url)
        observation = parse_eurostat_hicp(
            payload,
            country_code=code,
            retrieved_at=datetime.now(UTC),
            source_url=url,
        )
        return (observation,) if observation is not None else ()

    def _fetch_json(self, url: str) -> Any:
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "CulturalCurrencyConverter/0.1 economic-context-ingestion",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            if exc.code == 429:
                raise EconomicDataSourceError("Eurostat rate limit reached.") from exc
            raise EconomicDataSourceError(f"Eurostat returned HTTP {exc.code}.") from exc
        except (URLError, HTTPException, TimeoutError, OSError) as exc:
            raise EconomicDataSourceError("Eurostat request failed.") from exc

        if len(raw) > MAX_RESPONSE_BYTES:
            raise EconomicDataSourceError("Eurostat response exceeded the size limit.")
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise EconomicDataSourceError("Eurostat returned malformed JSON.") from exc
