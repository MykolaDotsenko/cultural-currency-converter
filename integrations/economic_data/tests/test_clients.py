from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from integrations.economic_data.eurostat import parse_eurostat_hicp
from integrations.economic_data.oecd import parse_oecd_price_level_csv
from integrations.economic_data.world_bank import (
    WORLD_BANK_INFLATION,
    WORLD_BANK_PRICE_LEVEL_RATIO,
    parse_world_bank_indicator,
)


def test_world_bank_parser_selects_latest_non_null_observation():
    payload = [
        {"page": 1, "pages": 1, "total": 3},
        [
            {
                "countryiso3code": "FIN",
                "date": "2025",
                "value": 1.8,
                "obs_status": "",
            },
            {
                "countryiso3code": "FIN",
                "date": "2024",
                "value": 1.2,
                "obs_status": "",
            },
            {
                "countryiso3code": "FIN",
                "date": "2023",
                "value": None,
                "obs_status": "",
            },
        ],
    ]

    observation = parse_world_bank_indicator(
        payload,
        indicator_code=WORLD_BANK_INFLATION,
        country_code="FIN",
        retrieved_at=datetime(2026, 10, 8, tzinfo=UTC),
        source_url="https://api.worldbank.org/v2/country/fin/indicator/FP.CPI.TOTL.ZG",
    )

    assert observation is not None
    assert observation.country_code == "FIN"
    assert observation.indicator == "inflation_yoy"
    assert observation.value == Decimal("1.8")
    assert observation.period_start.isoformat() == "2025-01-01"
    assert observation.unit == "percent"


def test_world_bank_price_level_ratio_has_explicit_us_benchmark():
    payload = [
        {"page": 1, "pages": 1, "total": 1},
        [
            {
                "countryiso3code": "JPN",
                "date": "2025",
                "value": 0.82,
                "obs_status": "F",
            }
        ],
    ]

    observation = parse_world_bank_indicator(
        payload,
        indicator_code=WORLD_BANK_PRICE_LEVEL_RATIO,
        country_code="JPN",
        retrieved_at=datetime(2026, 10, 8, tzinfo=UTC),
        source_url="https://api.worldbank.org/v2/country/jpn/indicator/PA.NUS.PPPC.RF",
    )

    assert observation is not None
    assert observation.indicator == "price_level_ratio"
    assert observation.value == Decimal("0.82")
    assert observation.benchmark_label == "United States = 1"
    assert observation.observation_status == "estimate"


def test_eurostat_jsonstat_parser_selects_latest_month():
    payload = {
        "id": ["freq", "unit", "coicop18", "geo", "time"],
        "size": [1, 1, 1, 1, 3],
        "dimension": {
            "freq": {"category": {"index": {"M": 0}}},
            "unit": {"category": {"index": {"RCH_A": 0}}},
            "coicop18": {"category": {"index": {"TOTAL": 0}}},
            "geo": {"category": {"index": {"FI": 0}}},
            "time": {
                "category": {
                    "index": {
                        "2026-07": 0,
                        "2026-08": 1,
                        "2026-09": 2,
                    }
                }
            },
        },
        "value": [0.2, 0.3, 0.5],
    }

    observation = parse_eurostat_hicp(
        payload,
        country_code="FI",
        retrieved_at=datetime(2026, 10, 8, tzinfo=UTC),
        source_url="https://ec.europa.eu/eurostat/api/example",
    )

    assert observation is not None
    assert observation.indicator == "inflation_yoy"
    assert observation.value == Decimal("0.5")
    assert observation.period_start.isoformat() == "2026-09-01"
    assert observation.frequency == "monthly"


def test_oecd_csv_parser_prefers_oecd_benchmark_for_latest_year():
    raw = (
        "REF_AREA,Analytical categories,BASE_REF_AREA,TIME_PERIOD,OBS_VALUE,OBS_STATUS\n"
        "FIN,Gross Domestic Product,EU27_2020,2024,118.4,P\n"
        "FIN,Gross Domestic Product,OECD,2024,111.2,P\n"
        "FIN,Gross Domestic Product,OECD,2023,109.8,\n"
        "JPN,Gross Domestic Product,OECD,2024,92.1,P\n"
        "FIN,Actual individual consumption,OECD,2024,107.0,P\n"
    ).encode()

    observations = parse_oecd_price_level_csv(
        raw,
        requested_country_codes={"FIN", "JPN"},
        retrieved_at=datetime(2026, 10, 8, tzinfo=UTC),
        source_url="https://sdmx.oecd.org/public/rest/data/example",
    )

    assert len(observations) == 2
    fin = next(item for item in observations if item.country_code == "FIN")
    jpn = next(item for item in observations if item.country_code == "JPN")
    assert fin.value == Decimal("111.2")
    assert fin.benchmark_label == "OECD = 100"
    assert fin.period_start.isoformat() == "2024-01-01"
    assert fin.observation_status == "preliminary"
    assert jpn.value == Decimal("92.1")
