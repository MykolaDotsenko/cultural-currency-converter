from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.countries.models import Country
from apps.culture.models import (
    EconomicIndicator,
    EconomicObservation,
    EconomicObservationSource,
)
from integrations.economic_data import EconomicSourceObservation

INFLATION_MAX_AGE = timedelta(days=550)
ANNUAL_CONTEXT_MAX_AGE = timedelta(days=1095)

_INFLATION_SOURCE_PRIORITY = {
    EconomicObservationSource.EUROSTAT.value: 0,
    EconomicObservationSource.WORLD_BANK.value: 1,
}
_PRICE_LEVEL_SOURCE_PRIORITY = {
    EconomicObservationSource.OECD.value: 0,
    EconomicObservationSource.WORLD_BANK: 1,
}


@dataclass(frozen=True, slots=True)
class EconomicMetricContext:
    indicator: str
    value: Decimal
    unit: str
    benchmark_label: str
    period_start: date
    frequency: str
    observation_status: str
    source: str
    source_name: str
    source_url: str
    source_dataset: str


@dataclass(frozen=True, slots=True)
class EconomicContext:
    inflation: EconomicMetricContext | None
    price_level: EconomicMetricContext | None

    @property
    def has_content(self) -> bool:
        return self.inflation is not None or self.price_level is not None


def _metric(row: EconomicObservation) -> EconomicMetricContext:
    return EconomicMetricContext(
        indicator=row.indicator,
        value=row.value,
        unit=row.unit,
        benchmark_label=row.benchmark_label,
        period_start=row.period_start,
        frequency=row.frequency,
        observation_status=row.observation_status,
        source=row.source,
        source_name=row.source_name,
        source_url=row.source_url,
        source_dataset=row.source_dataset,
    )


def _select_latest(
    rows: list[EconomicObservation],
    *,
    priority: dict[str, int],
) -> EconomicObservation | None:
    if not rows:
        return None

    best_priority = min(priority.get(row.source, 99) for row in rows)
    preferred = [row for row in rows if priority.get(row.source, 99) == best_priority]
    latest_period = max(row.period_start for row in preferred)
    latest = [row for row in preferred if row.period_start == latest_period]
    return min(latest, key=lambda row: row.pk)


def build_economic_context(
    *,
    country: Country,
    as_of: date | None = None,
) -> EconomicContext | None:
    selected_date = as_of or timezone.localdate()

    inflation_cutoff = selected_date - INFLATION_MAX_AGE
    inflation_rows = list(
        EconomicObservation.objects.filter(
            country=country,
            is_published=True,
            indicator=EconomicIndicator.INFLATION_YOY,
            period_start__gte=inflation_cutoff,
            period_start__lte=selected_date,
        ).order_by("-period_start", "source", "pk")
    )
    inflation_row = _select_latest(
        inflation_rows,
        priority=_INFLATION_SOURCE_PRIORITY,
    )

    annual_cutoff = selected_date - ANNUAL_CONTEXT_MAX_AGE
    price_level_rows = list(
        EconomicObservation.objects.filter(
            country=country,
            is_published=True,
            indicator__in=(
                EconomicIndicator.PRICE_LEVEL_INDEX,
                EconomicIndicator.PRICE_LEVEL_RATIO,
            ),
            period_start__gte=annual_cutoff,
            period_start__lte=selected_date,
        ).order_by("-period_start", "source", "pk")
    )
    price_level_row = _select_latest(
        price_level_rows,
        priority=_PRICE_LEVEL_SOURCE_PRIORITY,
    )

    context = EconomicContext(
        inflation=_metric(inflation_row) if inflation_row is not None else None,
        price_level=_metric(price_level_row) if price_level_row is not None else None,
    )
    return context if context.has_content else None


def persist_economic_observation(
    observation: EconomicSourceObservation,
) -> tuple[EconomicObservation, bool]:
    country_code = observation.country_code.strip().upper()
    country = (
        Country.objects.filter(iso2=country_code, is_active=True).first()
        if len(country_code) == 2
        else Country.objects.filter(iso3=country_code, is_active=True).first()
    )
    if country is None:
        raise ValueError(f"No active canonical country matches {country_code}.")

    with transaction.atomic():
        row, created = EconomicObservation.objects.update_or_create(
            country=country,
            source=observation.source,
            indicator=observation.indicator,
            category=observation.category,
            period_start=observation.period_start,
            defaults={
                "value": observation.value,
                "unit": observation.unit,
                "benchmark_label": observation.benchmark_label,
                "frequency": observation.frequency,
                "observation_status": observation.observation_status,
                "source_dataset": observation.source_dataset,
                "source_name": observation.source_name,
                "source_url": observation.source_url,
                "source_retrieved_at": observation.retrieved_at,
                "is_published": True,
            },
        )
        row.full_clean()
        row.save()
    return row, created
