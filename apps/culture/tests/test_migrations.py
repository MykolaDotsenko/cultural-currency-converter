from __future__ import annotations

from decimal import Decimal

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


@pytest.mark.django_db(transaction=True)
def test_typical_price_city_backfill_creates_canonical_city_reference():
    migrate_from = [
        ("countries", "0003_city"),
        ("culture", "0002_destination_context"),
    ]
    migrate_to = [
        ("countries", "0003_city"),
        ("culture", "0003_typicalprice_city_ref"),
    ]

    executor = MigrationExecutor(connection)
    executor.migrate(migrate_from)
    old_apps = executor.loader.project_state(migrate_from).apps

    Country = old_apps.get_model("countries", "Country")
    Currency = old_apps.get_model("countries", "Currency")
    TypicalPrice = old_apps.get_model("culture", "TypicalPrice")

    japan = Country.objects.create(iso2="JP", iso3="JPN", name="Japan")
    jpy = Currency.objects.create(code="JPY", name="Japanese yen")
    legacy = TypicalPrice.objects.create(
        country=japan,
        city="  Tokyo  ",
        category="transit",
        label="Metro ticket",
        amount_low=Decimal("180"),
        currency=jpy,
        source_name="Source",
        source_url="https://example.org/fare",
        observed_at="2026-09-21",
    )

    executor = MigrationExecutor(connection)
    executor.migrate(migrate_to)
    new_apps = executor.loader.project_state(migrate_to).apps

    City = new_apps.get_model("countries", "City")
    TypicalPrice = new_apps.get_model("culture", "TypicalPrice")

    migrated = TypicalPrice.objects.get(pk=legacy.pk)
    city = City.objects.get(pk=migrated.city_ref_id)

    assert migrated.city == "Tokyo"
    assert city.country_id == japan.pk
    assert city.slug == "tokyo"
    assert city.name == "Tokyo"
