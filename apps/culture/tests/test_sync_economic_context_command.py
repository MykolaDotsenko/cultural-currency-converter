from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.countries.models import Country
from apps.culture.models import EconomicObservation
from integrations.economic_data.base import EconomicDataSourceError, EconomicSourceObservation


def _world_bank_observation(code: str) -> EconomicSourceObservation:
    return EconomicSourceObservation(
        country_code=code,
        indicator="inflation_yoy",
        category="all_items",
        value=Decimal("1.2"),
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


@pytest.fixture
def finland(db):
    return Country.objects.create(iso2="FI", iso3="FIN", name="Finland")


@pytest.mark.django_db
def test_sync_economic_context_dry_run_rolls_back(monkeypatch, finland):
    monkeypatch.setattr(
        "apps.culture.management.commands.sync_economic_context."
        "WorldBankEconomicClient.fetch_country",
        lambda self, country_iso3: (_world_bank_observation(country_iso3),),
    )

    call_command(
        "sync_economic_context",
        source="world_bank",
        country=["FI"],
        dry_run=True,
    )

    assert not EconomicObservation.objects.exists()


@pytest.mark.django_db
def test_sync_economic_context_persists_validated_observation(monkeypatch, finland):
    monkeypatch.setattr(
        "apps.culture.management.commands.sync_economic_context."
        "WorldBankEconomicClient.fetch_country",
        lambda self, country_iso3: (_world_bank_observation(country_iso3),),
    )

    call_command(
        "sync_economic_context",
        source="world_bank",
        country=["FIN"],
    )

    row = EconomicObservation.objects.get()
    assert row.country == finland
    assert row.value == Decimal("1.2")
    assert row.source_dataset == "FP.CPI.TOTL.ZG"


@pytest.mark.django_db
def test_sync_economic_context_aborts_before_writes_when_any_source_fails(
    monkeypatch,
    finland,
):
    monkeypatch.setattr(
        "apps.culture.management.commands.sync_economic_context."
        "WorldBankEconomicClient.fetch_country",
        lambda self, country_iso3: (_world_bank_observation(country_iso3),),
    )

    def fail_eurostat(self, country_iso2):
        raise EconomicDataSourceError("upstream unavailable")

    monkeypatch.setattr(
        "apps.culture.management.commands.sync_economic_context."
        "EurostatEconomicClient.fetch_country",
        fail_eurostat,
    )
    monkeypatch.setattr(
        "apps.culture.management.commands.sync_economic_context.OECDEconomicClient.fetch_countries",
        lambda self, country_iso3_codes: (),
    )

    with pytest.raises(CommandError, match="aborted before database writes"):
        call_command("sync_economic_context", source="all", country=["FI"])

    assert not EconomicObservation.objects.exists()


@pytest.mark.django_db
def test_scheduled_economic_sync_refuses_empty_provider_result(monkeypatch, finland):
    monkeypatch.setattr(
        "apps.culture.management.commands.sync_economic_context."
        "WorldBankEconomicClient.fetch_country",
        lambda self, country_iso3: (),
    )

    with pytest.raises(CommandError, match="no observations"):
        call_command(
            "sync_economic_context",
            source="world_bank",
            country=["FI"],
            require_observations=True,
        )

    assert not EconomicObservation.objects.exists()


@pytest.mark.django_db
def test_manual_economic_sync_can_explicitly_inspect_empty_coverage(monkeypatch, finland):
    monkeypatch.setattr(
        "apps.culture.management.commands.sync_economic_context."
        "WorldBankEconomicClient.fetch_country",
        lambda self, country_iso3: (),
    )

    call_command(
        "sync_economic_context",
        source="world_bank",
        country=["FI"],
        dry_run=True,
    )
    assert not EconomicObservation.objects.exists()
