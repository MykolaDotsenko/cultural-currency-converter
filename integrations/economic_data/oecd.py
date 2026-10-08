from __future__ import annotations

import csv
import io
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from integrations.economic_data.base import EconomicDataSourceError, EconomicSourceObservation

DATA_URL = "https://sdmx.oecd.org/public/rest/data/OECD.SDD.TPS,DSD_PPP@DF_PPP_CPL,1.1/.A...."
MAX_RESPONSE_BYTES = 8 * 1024 * 1024

_AREA_COLUMNS = ("REF_AREA", "Reference area")
_CATEGORY_CODE_COLUMNS = (
    "ANALYTICAL_CATEGORY",
    "ANALYTICAL_CAT",
    "EXPENDITURE",
    "PPP_CATEGORY",
)
_CATEGORY_LABEL_COLUMNS = (
    "Analytical categories",
    "ANALYTICAL_CATEGORY_LABEL",
    "ANALYTICAL_CAT_LABEL",
)
_BASE_COLUMNS = ("BASE_REF_AREA", "Base reference area")
_TIME_COLUMNS = ("TIME_PERIOD", "Time period")
_VALUE_COLUMNS = ("OBS_VALUE", "Observation value")
_STATUS_COLUMNS = ("OBS_STATUS", "Observation status")

_GDP_CODES = frozenset({"GDP", "B1GQ", "A01"})
_OECD_BASE_CODES = frozenset({"OECD", "OECD38", "OECD_TOTAL"})
_EU_BASE_CODES = frozenset({"EU27_2020", "EU27", "EU"})


def _first(row: dict[str, str], names: tuple[str, ...]) -> str:
    for name in names:
        value = row.get(name)
        if value is not None and value.strip():
            return value.strip()
    return ""


def _is_gdp_row(row: dict[str, str]) -> bool:
    code = _first(row, _CATEGORY_CODE_COLUMNS).upper()
    if code in _GDP_CODES:
        return True
    label = _first(row, _CATEGORY_LABEL_COLUMNS).casefold()
    return label == "gross domestic product" or label.startswith("gross domestic product ")


def _benchmark(base_code: str) -> tuple[int, str]:
    normalized = base_code.strip().upper()
    if normalized in _OECD_BASE_CODES or normalized.startswith("OECD"):
        return 0, "OECD = 100"
    if normalized in _EU_BASE_CODES or normalized.startswith("EU27"):
        return 1, "European Union = 100"
    return 2, f"{base_code} = 100" if base_code else "Published benchmark = 100"


def parse_oecd_price_level_csv(
    raw: bytes,
    *,
    requested_country_codes: set[str],
    retrieved_at: datetime,
    source_url: str,
) -> tuple[EconomicSourceObservation, ...]:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise EconomicDataSourceError("OECD returned non-UTF-8 CSV.") from exc

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise EconomicDataSourceError("OECD CSV is missing a header.")

    requested = {code.upper() for code in requested_country_codes}
    candidates: dict[str, list[tuple[date, int, EconomicSourceObservation]]] = {}
    for row in reader:
        area = _first(row, _AREA_COLUMNS).upper()
        if area not in requested or not _is_gdp_row(row):
            continue

        raw_period = _first(row, _TIME_COLUMNS)
        if len(raw_period) != 4 or not raw_period.isdecimal():
            continue
        period = date(int(raw_period), 1, 1)
        if period > retrieved_at.date():
            continue

        raw_value = _first(row, _VALUE_COLUMNS)
        try:
            value = Decimal(raw_value)
        except (InvalidOperation, ValueError):
            continue
        if not value.is_finite() or value <= 0:
            continue

        base_code = _first(row, _BASE_COLUMNS)
        priority, benchmark_label = _benchmark(base_code)
        raw_status = _first(row, _STATUS_COLUMNS).upper()
        status = (
            "preliminary"
            if raw_status in {"P", "PROVISIONAL"}
            else "estimate"
            if raw_status in {"E", "ESTIMATE"}
            else "unknown"
        )
        observation = EconomicSourceObservation(
            country_code=area,
            indicator="price_level_index",
            category="all_items",
            value=value,
            unit="index",
            benchmark_label=benchmark_label,
            period_start=period,
            frequency="annual",
            observation_status=status,
            source="oecd",
            source_dataset="DSD_PPP@DF_PPP_CPL",
            source_name="OECD",
            source_url=source_url,
            retrieved_at=retrieved_at,
        )
        candidates.setdefault(area, []).append((period, priority, observation))

    selected: list[EconomicSourceObservation] = []
    for area in sorted(requested):
        rows = candidates.get(area, [])
        if not rows:
            continue
        latest_period = max(item[0] for item in rows)
        latest = [item for item in rows if item[0] == latest_period]
        selected.append(min(latest, key=lambda item: item[1])[2])
    return tuple(selected)


class OECDEconomicClient:
    def __init__(self, *, timeout_seconds: float = 12.0):
        if not 0 < timeout_seconds <= 30:
            raise ValueError("OECD timeout must be > 0 and <= 30 seconds.")
        self.timeout_seconds = timeout_seconds

    def fetch_countries(
        self,
        country_iso3_codes: set[str],
        *,
        start_year: int | None = None,
    ) -> tuple[EconomicSourceObservation, ...]:
        codes = {code.strip().upper() for code in country_iso3_codes}
        if not codes:
            return ()
        if any(len(code) != 3 or not code.isascii() or not code.isalpha() for code in codes):
            raise ValueError("OECD country codes must use ISO alpha-3 values.")

        first_year = start_year or max(2022, date.today().year - 4)
        params = urlencode(
            {
                "startPeriod": str(first_year),
                "dimensionAtObservation": "AllDimensions",
            }
        )
        url = f"{DATA_URL}?{params}"
        raw = self._fetch_csv(url)
        return parse_oecd_price_level_csv(
            raw,
            requested_country_codes=codes,
            retrieved_at=datetime.now(UTC),
            source_url=url,
        )

    def _fetch_csv(self, url: str) -> bytes:
        request = Request(
            url,
            headers={
                "Accept": "text/csv;version=2.0",
                "User-Agent": "CulturalCurrencyConverter/0.1 economic-context-ingestion",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            if exc.code == 429:
                raise EconomicDataSourceError("OECD rate limit reached.") from exc
            raise EconomicDataSourceError(f"OECD returned HTTP {exc.code}.") from exc
        except (URLError, HTTPException, TimeoutError, OSError) as exc:
            raise EconomicDataSourceError("OECD request failed.") from exc

        if len(raw) > MAX_RESPONSE_BYTES:
            raise EconomicDataSourceError("OECD response exceeded the size limit.")
        return raw
