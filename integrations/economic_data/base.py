from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal


class EconomicDataSourceError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class EconomicSourceObservation:
    country_code: str
    indicator: str
    category: str
    value: Decimal
    unit: str
    benchmark_label: str
    period_start: date
    frequency: str
    observation_status: str
    source: str
    source_dataset: str
    source_name: str
    source_url: str
    retrieved_at: datetime
