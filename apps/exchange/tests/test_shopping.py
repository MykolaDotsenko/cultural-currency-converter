from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from apps.exchange.domain import DEFAULT_SOURCE_POLICY, ConversionResult, RateQuote
from apps.exchange.shopping import (
    ShoppingAssumptions,
    ShoppingCalculationError,
    calculate_shopping_estimate,
)


def _conversion(
    *,
    input_amount: Decimal = Decimal("130"),
    output_amount: Decimal = Decimal("117.00"),
    historical: bool = False,
    base_currency: str = "USD",
    quote_currency: str = "EUR",
) -> ConversionResult:
    return ConversionResult(
        input_amount=input_amount,
        output_amount=output_amount,
        quote=RateQuote(
            base_currency=base_currency,
            quote_currency=quote_currency,
            rate=Decimal("0.9") if base_currency != quote_currency else Decimal("1"),
            requested_date=date(2026, 9, 1) if historical else None,
            effective_date=date(2026, 9, 1) if historical else date(2026, 10, 1),
            fetched_at=datetime(2026, 10, 1, 8, tzinfo=UTC),
            provider_policy=DEFAULT_SOURCE_POLICY,
            provider_keys=("ecb",) if base_currency != quote_currency else (),
            historical=historical,
        ),
        stale=False,
    )


def test_shopping_assumptions_sum_only_explicit_purchase_currency_costs():
    assumptions = ShoppingAssumptions(
        item_price=Decimal("100"),
        shipping=Decimal("20"),
        known_fees=Decimal("10"),
        fx_markup_percent=Decimal("2.5"),
    )

    assert assumptions.purchase_total == Decimal("130")


def test_shopping_estimate_keeps_reference_cost_and_markup_distinct():
    assumptions = ShoppingAssumptions(
        item_price=Decimal("100"),
        shipping=Decimal("20"),
        known_fees=Decimal("10"),
        fx_markup_percent=Decimal("2.5"),
    )

    result = calculate_shopping_estimate(
        conversion=_conversion(),
        assumptions=assumptions,
        home_minor_units=2,
    )

    assert result.purchase_currency == "USD"
    assert result.home_currency == "EUR"
    assert result.reference_home_cost == Decimal("117.00")
    assert result.estimated_home_cost == Decimal("119.92")
    assert result.fx_markup_cost == Decimal("2.92")
    assert result.unknown_costs == (
        "duties not explicitly entered",
        "taxes not explicitly entered",
        "issuer or merchant fees not explicitly entered",
    )


def test_zero_markup_never_changes_reference_home_cost():
    assumptions = ShoppingAssumptions(item_price=Decimal("130"))

    result = calculate_shopping_estimate(
        conversion=_conversion(),
        assumptions=assumptions,
        home_minor_units=2,
    )

    assert result.estimated_home_cost == result.reference_home_cost
    assert result.fx_markup_cost == Decimal("0.00")


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("item_price", Decimal("0"), "greater than zero"),
        ("shipping", Decimal("-1"), "non-negative"),
        ("known_fees", Decimal("NaN"), "finite Decimal"),
        ("fx_markup_percent", Decimal("25.01"), "cannot exceed"),
    ],
)
def test_invalid_explicit_shopping_inputs_fail_closed(field, value, message):
    kwargs = {"item_price": Decimal("100")}
    kwargs[field] = value

    with pytest.raises(ShoppingCalculationError, match=message):
        ShoppingAssumptions(**kwargs)


def test_conversion_input_must_equal_explicit_purchase_total():
    assumptions = ShoppingAssumptions(
        item_price=Decimal("100"),
        shipping=Decimal("20"),
        known_fees=Decimal("10"),
    )

    with pytest.raises(ShoppingCalculationError, match="must equal"):
        calculate_shopping_estimate(
            conversion=_conversion(input_amount=Decimal("129")),
            assumptions=assumptions,
            home_minor_units=2,
        )


def test_historical_conversion_is_rejected():
    assumptions = ShoppingAssumptions(item_price=Decimal("130"))

    with pytest.raises(ShoppingCalculationError, match="current reference"):
        calculate_shopping_estimate(
            conversion=_conversion(historical=True),
            assumptions=assumptions,
            home_minor_units=2,
        )


def test_same_currency_purchase_is_not_presented_as_foreign_shopping():
    assumptions = ShoppingAssumptions(item_price=Decimal("130"))

    with pytest.raises(ShoppingCalculationError, match="different purchase and home"):
        calculate_shopping_estimate(
            conversion=_conversion(
                input_amount=Decimal("130"),
                output_amount=Decimal("130"),
                base_currency="EUR",
                quote_currency="EUR",
            ),
            assumptions=assumptions,
            home_minor_units=2,
        )


@pytest.mark.parametrize("minor_units", [-1, 7, True])
def test_invalid_home_minor_units_fail_closed(minor_units):
    assumptions = ShoppingAssumptions(item_price=Decimal("130"))

    with pytest.raises(ShoppingCalculationError, match="minor units"):
        calculate_shopping_estimate(
            conversion=_conversion(),
            assumptions=assumptions,
            home_minor_units=minor_units,
        )
