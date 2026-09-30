from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from apps.exchange.domain import DEFAULT_SOURCE_POLICY, ConversionResult, RateQuote
from apps.exchange.payment_estimate import (
    PaymentEstimateAssumptions,
    PaymentEstimateError,
    estimate_conversion_payment_value,
    estimate_payment_value,
)


def _conversion(*, historical: bool = False, same_currency: bool = False) -> ConversionResult:
    quote_currency = "EUR" if same_currency else "JPY"
    requested_date = date(2020, 1, 2) if historical else None
    return ConversionResult(
        input_amount=Decimal("100.00"),
        output_amount=Decimal("100.00") if same_currency else Decimal("17450"),
        quote=RateQuote(
            base_currency="EUR",
            quote_currency=quote_currency,
            rate=Decimal("1") if same_currency else Decimal("174.50"),
            requested_date=requested_date,
            effective_date=requested_date or date(2026, 9, 18),
            fetched_at=datetime(2026, 9, 21, 8, tzinfo=UTC),
            provider_policy=DEFAULT_SOURCE_POLICY,
            provider_keys=() if same_currency else ("ecb",),
            historical=historical,
        ),
        stale=False,
    )


def test_zero_assumptions_preserve_reference_destination_value():
    estimate = estimate_payment_value(
        source_budget=Decimal("100.00"),
        reference_destination_amount=Decimal("17450"),
        rate=Decimal("174.50"),
        fx_markup_percent=Decimal("0"),
        source_fixed_fee=Decimal("0"),
        destination_fixed_fee=Decimal("0"),
        destination_minor_units=0,
    )

    assert estimate.estimated_destination_amount == Decimal("17450")
    assert estimate.destination_value_lost == Decimal("0")


def test_explicit_markup_and_fixed_fees_reduce_value_from_fixed_budget():
    estimate = estimate_payment_value(
        source_budget=Decimal("100.00"),
        reference_destination_amount=Decimal("17450"),
        rate=Decimal("174.50"),
        fx_markup_percent=Decimal("2.00"),
        source_fixed_fee=Decimal("1.00"),
        destination_fixed_fee=Decimal("220"),
        destination_minor_units=0,
    )

    assert estimate.estimated_destination_amount == Decimal("16717")
    assert estimate.destination_value_lost == Decimal("733")
    assert estimate.effective_source_amount < Decimal("100.00")


def test_destination_rounding_uses_currency_minor_units():
    estimate = estimate_payment_value(
        source_budget=Decimal("10.00"),
        reference_destination_amount=Decimal("12.35"),
        rate=Decimal("1.235"),
        fx_markup_percent=Decimal("0"),
        source_fixed_fee=Decimal("0"),
        destination_fixed_fee=Decimal("0"),
        destination_minor_units=2,
    )

    assert estimate.estimated_destination_amount == Decimal("12.35")


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("fx_markup_percent", Decimal("25.01"), "FX markup cannot exceed"),
        ("source_fixed_fee", Decimal("100.01"), "Source fixed fee cannot exceed"),
        ("destination_fixed_fee", Decimal("17451"), "Destination fixed fee cannot exceed"),
    ],
)
def test_assumptions_are_bounded(field, value, message):
    values = {
        "source_budget": Decimal("100.00"),
        "reference_destination_amount": Decimal("17450"),
        "rate": Decimal("174.50"),
        "fx_markup_percent": Decimal("0"),
        "source_fixed_fee": Decimal("0"),
        "destination_fixed_fee": Decimal("0"),
        "destination_minor_units": 0,
    }
    values[field] = value

    with pytest.raises(PaymentEstimateError, match=message):
        estimate_payment_value(**values)


def test_negative_assumptions_are_rejected():
    with pytest.raises(PaymentEstimateError, match=r"FX markup.*non-negative"):
        estimate_payment_value(
            source_budget=Decimal("100"),
            reference_destination_amount=Decimal("17450"),
            rate=Decimal("174.5"),
            fx_markup_percent=Decimal("-1"),
            source_fixed_fee=Decimal("0"),
            destination_fixed_fee=Decimal("0"),
            destination_minor_units=0,
        )


def test_conversion_payment_helper_reuses_trusted_conversion_values():
    estimate = estimate_conversion_payment_value(
        conversion=_conversion(),
        assumptions=PaymentEstimateAssumptions(
            fx_markup_percent=Decimal("2.00"),
            source_fixed_fee=Decimal("1.00"),
            destination_fixed_fee=Decimal("220"),
        ),
        destination_minor_units=0,
    )

    assert estimate.source_budget == Decimal("100.00")
    assert estimate.reference_destination_amount == Decimal("17450")
    assert estimate.estimated_destination_amount == Decimal("16717")


@pytest.mark.parametrize(
    ("conversion", "message"),
    [
        (_conversion(historical=True), "historical"),
        (_conversion(same_currency=True), "same-currency"),
    ],
)
def test_conversion_payment_helper_preserves_payment_estimate_boundaries(conversion, message):
    with pytest.raises(PaymentEstimateError, match=message):
        estimate_conversion_payment_value(
            conversion=conversion,
            assumptions=PaymentEstimateAssumptions(),
            destination_minor_units=0,
        )
