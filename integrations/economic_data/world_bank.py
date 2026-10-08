from __future__ import annotations

import json
import socket
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from http.client import HTTPException
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from integrations.economic_data.base import EconomicDataSourceError, EconomicSourceObservation

BASE_URL = "https://api.worldbank.org/v2"
MAX_RESPONSE_BYTES = 1024 * 1024

WORLD_BANK_INFLATION = "FP.CPI.TOTL.ZG"
WORLD_BANK_PRICE_LEVEL_RATIO = "PA.NUS.PPPC.RF"


def _finite_decimal(value: Any) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise EconomicDataSourceError(
            "World Bank observation has an invalid numeric value."
        ) from exc
    if not parsed.is_finite():
        raise EconomicDataSourceError("World Bank observation must be finite.")
    return parsed


def parse_world_bank_indicator(
    payload: Any,
    *,
    indicator_code: str,
    country_code: str,
    retrieved_at: datetime,
    source_url: str,
) -> EconomicSourceObservation | None:
    if not isinstance(payload, list) or len(payload) != 2:
        raise EconomicDataSourceError(
            "World Bank indicator response must contain metadata and data."
        )

    metadata, rows = payload
    if not isinstance(metadata, dict) or not isinstance(rows, list):
        raise EconomicDataSourceError("World Bank indicator response has an invalid shape.")

    for raw in rows:
        if not isinstance(raw, dict) or raw.get("value") is None:
            continue
        raw_country = str(raw.get("countryiso3code") or "").strip().upper()
        if raw_country and raw_country != country_code.upper():
            continue
        raw_period = str(raw.get("date") or "").strip()
        if len(raw_period) != 4 or not raw_period.isdecimal():
            continue
        year = int(raw_period)
        if year < 1900 or year > retrieved_at.year:
            continue

        if indicator_code == WORLD_BANK_INFLATION:
            indicator = "inflation_yoy"
            unit = "percent"
            benchmark = ""
        elif indicator_code == WORLD_BANK_PRICE_LEVEL_RATIO:
            indicator = "price_level_ratio"
            unit = "ratio"
            benchmark = "United States = 1"
        else:
            raise ValueError("Unsupported World Bank indicator code.")

        observation_status = (
            "estimate" if str(raw.get("obs_status") or "").upper() == "F" else "unknown"
        )
        return EconomicSourceObservation(
            country_code=country_code.upper(),
            indicator=indicator,
            category="all_items",
            value=_finite_decimal(raw["value"]),
            unit=unit,
            benchmark_label=benchmark,
            period_start=date(year, 1, 1),
            frequency="annual",
            observation_status=observation_status,
            source="world_bank",
            source_dataset=indicator_code,
            source_name="World Bank",
            source_url=source_url,
            retrieved_at=retrieved_at,
        )
    return None


class WorldBankEconomicClient:
    def __init__(self, *, timeout_seconds: float = 8.0):
        if not 0 < timeout_seconds <= 30:
            raise ValueError("World Bank timeout must be > 0 and <= 30 seconds.")
        self.timeout_seconds = timeout_seconds

    def fetch_country(
        self,
        country_iso3: str,
        *,
        as_of: date | None = None,
    ) -> tuple[EconomicSourceObservation, ...]:
        code = country_iso3.strip().upper()
        if len(code) != 3 or not code.isascii() or not code.isalpha():
            raise ValueError("World Bank country code must be ISO alpha-3.")

        today = as_of or date.today()
        start_year = max(1900, today.year - 5)
        retrieved_at = datetime.now(UTC)
        observations: list[EconomicSourceObservation] = []
        for indicator_code in (WORLD_BANK_INFLATION, WORLD_BANK_PRICE_LEVEL_RATIO):
            params = urlencode(
                {
                    "format": "json",
                    "date": f"{start_year}:{today.year}",
                    "per_page": "100",
                }
            )
            url = f"{BASE_URL}/country/{code.lower()}/indicator/{indicator_code}?{params}"
            payload = self._fetch_json(url)
            observation = parse_world_bank_indicator(
                payload,
                indicator_code=indicator_code,
                country_code=code,
                retrieved_at=retrieved_at,
                source_url=url,
            )
            if observation is not None:
                observations.append(observation)
        return tuple(observations)

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
                raise EconomicDataSourceError("World Bank rate limit reached.") from exc
            raise EconomicDataSourceError(f"World Bank returned HTTP {exc.code}.") from exc
        except (URLError, HTTPException, TimeoutError, socket.timeout, OSError) as exc:
            raise EconomicDataSourceError("World Bank request failed.") from exc

        if len(raw) > MAX_RESPONSE_BYTES:
            raise EconomicDataSourceError("World Bank response exceeded the size limit.")
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise EconomicDataSourceError("World Bank returned malformed JSON.") from exc
