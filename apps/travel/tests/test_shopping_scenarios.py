from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from apps.countries.models import Country, CountryCurrency, Currency
from apps.exchange.domain import DEFAULT_SOURCE_POLICY, ConversionResult, RateQuote
from apps.exchange.shopping import ShoppingAssumptions
from apps.travel.models import SavedScenarioKind
from apps.travel.scenarios import SavedScenarioError, SavedScenarioSpec, create_saved_scenario

User = get_user_model()


@pytest.fixture
def shopping_scenario_reference_data(db):
    us = Country.objects.create(iso2="US", iso3="USA", name="United States")
    usd = Currency.objects.create(code="USD", name="US dollar", symbol="$", minor_units=2)
    eur = Currency.objects.create(code="EUR", name="Euro", symbol="€", minor_units=2)
    CountryCurrency.objects.create(country=us, currency=usd, is_primary=True, source="test")
    return us, usd, eur


def _conversion() -> ConversionResult:
    return ConversionResult(
        input_amount=Decimal("130"),
        output_amount=Decimal("117.00"),
        quote=RateQuote(
            base_currency="USD",
            quote_currency="EUR",
            rate=Decimal("0.9"),
            requested_date=None,
            effective_date=date(2026, 10, 1),
            fetched_at=datetime(2026, 10, 2, 8, tzinfo=UTC),
            provider_policy=DEFAULT_SOURCE_POLICY,
            provider_keys=("ecb",),
            historical=False,
        ),
        stale=False,
    )


@pytest.mark.django_db
def test_create_saved_shopping_scenario_persists_inputs_and_initial_observation(
    shopping_scenario_reference_data,
):
    us, usd, eur = shopping_scenario_reference_data
    user = User.objects.create_user(username="shop-owner", password="StrongPass-482!")
    assumptions = ShoppingAssumptions(
        item_price=Decimal("100"),
        shipping=Decimal("20"),
        known_fees=Decimal("10"),
        fx_markup_percent=Decimal("2.5"),
    )

    scenario = create_saved_scenario(
        user,
        spec=SavedScenarioSpec(
            kind=SavedScenarioKind.SHOPPING,
            title="US headphones",
            source_currency=usd,
            destination_currency=eur,
            source_country=us,
            source_amount=Decimal("130"),
            shopping_assumptions=assumptions,
        ),
        conversion=_conversion(),
    )

    assert scenario.kind == SavedScenarioKind.SHOPPING
    assert scenario.destination_country is None
    assert scenario.source_country == us
    assert scenario.shopping_assumptions.item_price == Decimal("100")
    assert scenario.shopping_assumptions.shipping == Decimal("20")
    assert scenario.shopping_assumptions.known_fees == Decimal("10")
    assert scenario.shopping_assumptions.fx_markup_percent == Decimal("2.5")
    observation = scenario.observations.get()
    assert observation.input_amount == Decimal("130")
    assert observation.output_amount == Decimal("117.00")
    assert observation.provider_keys == ["ecb"]


@pytest.mark.django_db
def test_shopping_scenario_requires_shopping_payload(shopping_scenario_reference_data):
    us, usd, eur = shopping_scenario_reference_data
    user = User.objects.create_user(username="shop-owner-missing", password="StrongPass-482!")

    with pytest.raises(SavedScenarioError, match="require explicit shopping assumptions"):
        create_saved_scenario(
            user,
            spec=SavedScenarioSpec(
                kind=SavedScenarioKind.SHOPPING,
                source_currency=usd,
                destination_currency=eur,
                source_country=us,
                source_amount=Decimal("130"),
            ),
            conversion=_conversion(),
        )


@pytest.mark.django_db
def test_nonshopping_scenario_rejects_shopping_payload(shopping_scenario_reference_data):
    us, usd, eur = shopping_scenario_reference_data
    user = User.objects.create_user(username="shop-owner-wrong-kind", password="StrongPass-482!")

    with pytest.raises(SavedScenarioError, match="only for Shopping"):
        create_saved_scenario(
            user,
            spec=SavedScenarioSpec(
                kind=SavedScenarioKind.TRIP,
                source_currency=usd,
                destination_currency=eur,
                source_country=us,
                source_amount=Decimal("130"),
                shopping_assumptions=ShoppingAssumptions(item_price=Decimal("130")),
            ),
            conversion=_conversion(),
        )
