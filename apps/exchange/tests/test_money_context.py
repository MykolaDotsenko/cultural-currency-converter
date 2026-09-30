from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import Mock

import pytest

from apps.culture.services import DestinationContext, PaymentContext
from apps.exchange.domain import DEFAULT_SOURCE_POLICY, ConversionResult, RateQuote
from apps.exchange.money_context import MoneyContext, apply_payment_assumptions, compose_money_context
from apps.exchange.payment_estimate import PaymentEstimateAssumptions, PaymentEstimateError


def _conversion(*, historical: bool = False, same_currency: bool = False) -> ConversionResult:
    quote_currency = "EUR" if same_currency else "JPY"
    rate = Decimal("1") if same_currency else Decimal("174.50")
    requested_date = date(2026, 9, 18) if historical else None
    quote = RateQuote(
        base_currency="EUR",
        quote_currency=quote_currency,
        rate=rate,
        requested_date=requested_date,
        effective_date=date(2026, 9, 18),
        fetched_at=datetime(2026, 9, 20, 8, tzinfo=UTC),
        provider_policy=DEFAULT_SOURCE_POLICY,
        provider_keys=("ecb",) if not same_currency else (),
        historical=historical,
    )
    return ConversionResult(
        input_amount=Decimal("100.00"),
        output_amount=Decimal("100.00") if same_currency else Decimal("17450"),
        quote=quote,
        stale=False,
    )


def _payment_context() -> PaymentContext:
    return PaymentContext(
        summary="Cards are widely accepted.",
        payment_customs="Use local currency at terminals.",
        cash_usage="Some cash can still be useful.",
        tipping="Tipping is uncommon.",
        atm_notes="Use transparent ATM fees.",
        dcc_warning="Decline dynamic currency conversion.",
        source_name="Test source",
        source_url="https://example.test/payment",
        verified_at=datetime(2026, 9, 20, 8, tzinfo=UTC),
    )


def test_compose_money_context_builds_current_destination_meaning():
    conversion = _conversion()
    destination = DestinationContext(
        country_code="JP",
        country_name="Japan",
        as_of=date(2026, 9, 22),
        payment=_payment_context(),
        prices=(),
    )
    builder = Mock(return_value=destination)

    context = compose_money_context(
        conversion=conversion,
        destination_country="jp",
        context_as_of=date(2026, 9, 22),
        destination_context_builder=builder,
    )

    assert context.destination_country == "JP"
    assert context.destination == destination
    assert context.payment == destination.payment
    assert context.prices == ()
    assert context.has_destination_context is True
    assert context.payment_estimate is None
    builder.assert_called_once_with(
        country_code="JP",
        converted_amount=Decimal("17450"),
        quote_currency="JPY",
        as_of=date(2026, 9, 22),
    )


def test_historical_money_context_never_backdates_current_destination_context():
    builder = Mock()

    context = compose_money_context(
        conversion=_conversion(historical=True),
        destination_country="JP",
        context_as_of=date(2026, 9, 22),
        destination_context_builder=builder,
    )

    assert context.destination is None
    assert context.has_destination_context is False
    builder.assert_not_called()


def test_countryless_money_context_keeps_conversion_without_destination_enrichment():
    builder = Mock()

    context = compose_money_context(
        conversion=_conversion(),
        destination_country="",
        context_as_of=date(2026, 9, 22),
        destination_context_builder=builder,
    )

    assert context.destination_country == ""
    assert context.destination is None
    builder.assert_not_called()


def test_money_context_rejects_mismatched_destination_enrichment():
    destination = DestinationContext(
        country_code="FI",
        country_name="Finland",
        as_of=date(2026, 9, 22),
        payment=None,
        prices=(),
    )

    with pytest.raises(ValueError, match="country must match"):
        MoneyContext(
            conversion=_conversion(),
            destination_country="JP",
            context_as_of=date(2026, 9, 22),
            destination=destination,
        )


def test_apply_payment_assumptions_returns_new_context_without_mutation():
    context = MoneyContext(
        conversion=_conversion(),
        destination_country="JP",
        context_as_of=date(2026, 9, 22),
    )
    assumptions = PaymentEstimateAssumptions(
        fx_markup_percent=Decimal("2.00"),
        source_fixed_fee=Decimal("1.00"),
        destination_fixed_fee=Decimal("220"),
    )

    enriched = apply_payment_assumptions(
        context,
        assumptions=assumptions,
        destination_minor_units=0,
    )

    assert context.payment_estimate is None
    assert enriched.payment_estimate is not None
    assert enriched.payment_estimate.estimated_destination_amount == Decimal("16717")
    assert enriched.payment_estimate.destination_value_lost == Decimal("733")


@pytest.mark.parametrize(
    "conversion",
    [
        _conversion(historical=True),
        _conversion(same_currency=True),
    ],
)
def test_payment_assumptions_reject_unsupported_money_context(conversion):
    context = MoneyContext(
        conversion=conversion,
        destination_country="JP",
        context_as_of=date(2026, 9, 22),
    )

    with pytest.raises(PaymentEstimateError):
        apply_payment_assumptions(
            context,
            assumptions=PaymentEstimateAssumptions(),
            destination_minor_units=0,
        )
