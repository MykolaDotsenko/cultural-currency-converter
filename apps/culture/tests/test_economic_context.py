from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.countries.models import Country, Currency
from apps.culture.economic import build_economic_context, persist_economic_observation
from apps.culture.models import EconomicObservation
from apps.culture.presentation import build_destination_context_component
from apps.culture.services import build_destination_context
from integrations.economic_data.base import EconomicSourceObservation


@pytest.fixture
def finland(db):
    return Country.objects.create(
        iso2="FI",
        iso3="FIN",
        name="Finland",
        region="Europe",
        subregion="Northern Europe",
    )


@pytest.fixture
def euro(db):
    return Currency.objects.create(code="EUR", name="Euro", symbol="€", minor_units=2)


def _observation(
    *,
    country,
    source,
    indicator,
    value,
    period_start,
    unit,
    benchmark_label="",
):
    return EconomicObservation.objects.create(
        country=country,
        source=source,
        indicator=indicator,
        category="all_items",
        value=Decimal(value),
        unit=unit,
        benchmark_label=benchmark_label,
        period_start=period_start,
        frequency="monthly" if source == "eurostat" else "annual",
        observation_status="unknown",
        source_dataset=f"{source}-dataset",
        source_name={
            "eurostat": "Eurostat",
            "world_bank": "World Bank",
            "oecd": "OECD",
        }[source],
        source_url=f"https://example.test/{source}",
        source_retrieved_at=datetime(2026, 10, 8, tzinfo=UTC),
        is_published=True,
    )


@pytest.mark.django_db
def test_economic_context_prefers_provider_semantics_before_raw_recency(finland):
    _observation(
        country=finland,
        source="eurostat",
        indicator="inflation_yoy",
        value="0.8",
        period_start=date(2026, 9, 1),
        unit="percent",
    )
    _observation(
        country=finland,
        source="world_bank",
        indicator="inflation_yoy",
        value="1.4",
        period_start=date(2026, 1, 1),
        unit="percent",
    )
    _observation(
        country=finland,
        source="oecd",
        indicator="price_level_index",
        value="111.2",
        period_start=date(2024, 1, 1),
        unit="index",
        benchmark_label="OECD = 100",
    )
    _observation(
        country=finland,
        source="world_bank",
        indicator="price_level_ratio",
        value="1.09",
        period_start=date(2025, 1, 1),
        unit="ratio",
        benchmark_label="United States = 1",
    )

    context = build_economic_context(country=finland, as_of=date(2026, 10, 8))

    assert context is not None
    assert context.inflation is not None
    assert context.inflation.source == "eurostat"
    assert context.inflation.value == Decimal("0.8")
    assert context.price_level is not None
    assert context.price_level.source == "oecd"
    assert context.price_level.value == Decimal("111.2")
    assert context.price_level.benchmark_label == "OECD = 100"


@pytest.mark.django_db
def test_economic_context_ignores_stale_observations(finland):
    old = timezone.localdate() - timedelta(days=1500)
    _observation(
        country=finland,
        source="world_bank",
        indicator="inflation_yoy",
        value="9.9",
        period_start=old,
        unit="percent",
    )
    _observation(
        country=finland,
        source="world_bank",
        indicator="price_level_ratio",
        value="1.2",
        period_start=old,
        unit="ratio",
        benchmark_label="United States = 1",
    )

    assert build_economic_context(country=finland) is None


@pytest.mark.django_db
def test_persist_economic_observation_maps_iso_codes_and_is_idempotent(finland):
    source = EconomicSourceObservation(
        country_code="FIN",
        indicator="inflation_yoy",
        category="all_items",
        value=Decimal("1.25"),
        unit="percent",
        benchmark_label="",
        period_start=date(2025, 1, 1),
        frequency="annual",
        observation_status="unknown",
        source="world_bank",
        source_dataset="FP.CPI.TOTL.ZG",
        source_name="World Bank",
        source_url="https://api.worldbank.org/v2/example",
        retrieved_at=datetime(2026, 10, 8, tzinfo=UTC),
    )

    first, created = persist_economic_observation(source)
    updated_source = EconomicSourceObservation(
        **{**source.__dict__, "value": Decimal("1.30")}
    )
    second, created_again = persist_economic_observation(updated_source)

    assert created is True
    assert created_again is False
    assert first.pk == second.pk
    assert EconomicObservation.objects.get(pk=first.pk).value == Decimal("1.30")


@pytest.mark.django_db
def test_destination_context_and_presentation_include_macro_evidence(finland, euro):
    _observation(
        country=finland,
        source="eurostat",
        indicator="inflation_yoy",
        value="0.8",
        period_start=date(2026, 9, 1),
        unit="percent",
    )
    _observation(
        country=finland,
        source="oecd",
        indicator="price_level_index",
        value="111.2",
        period_start=date(2024, 1, 1),
        unit="index",
        benchmark_label="OECD = 100",
    )

    context = build_destination_context(
        country_code="FI",
        converted_amount=Decimal("100"),
        quote_currency=euro.code,
        as_of=date(2026, 10, 8),
    )

    assert context is not None
    assert context.economic is not None
    assert context.has_content is True

    component = build_destination_context_component(context, historical=False)
    economic = component["economic"]
    assert economic is not None
    assert economic["inflation"]["value_text"] == "0.8%"
    assert economic["price_level"]["value_text"] == "111.2"
    assert economic["price_level"]["interpretation"] == "OECD = 100"
