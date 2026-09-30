from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import Mock

import pytest
from django.db import DatabaseError

from apps.culture.services import DestinationContext, PaymentContext
from apps.exchange.domain import DEFAULT_SOURCE_POLICY, ConversionResult, RateQuote
from apps.exchange.money_context import MoneyContextState, build_money_context


def _conversion(
    *,
    historical: bool = False,
    base: str = "EUR",
    quote: str = "JPY",
) -> ConversionResult:
    requested_date = date(2020, 1, 2) if historical else None
    return ConversionResult(
        input_amount=Decimal("100.00"),
        output_amount=Decimal("17450"),
        quote=RateQuote(
            base_currency=base,
            quote_currency=quote,
            rate=Decimal("174.50") if base != quote else Decimal("1"),
            requested_date=requested_date,
            effective_date=requested_date or date(2026, 9, 18),
            fetched_at=datetime(2026, 9, 21, 8, tzinfo=UTC),
            provider_policy=DEFAULT_SOURCE_POLICY,
            provider_keys=("ecb",) if base != quote else (),
            historical=historical,
        ),
        stale=False,
    )


def _payment_context() -> PaymentContext:
    return PaymentContext(
        summary="Current reviewed payment context.",
        payment_customs="Cards are commonly accepted.",
        cash_usage="Cash remains useful.",
        tipping="Tipping is generally not practiced.",
        atm_notes="Use a clearly disclosed ATM fee.",
        dcc_warning="Prefer the local currency when DCC is offered.",
        source_name="Official source",
        source_url="https://example.org/payment",
        verified_at=datetime(2026, 9, 20, 8, tzinfo=UTC),
    )


def test_current_money_context_composes_destination_enrichment():
    conversion = _conversion()
    expected = DestinationContext(
        country_code="JP",
        country_name="Japan",
        as_of=date(2026, 9, 22),
        payment=_payment_context(),
        prices=(),
    )
    builder = Mock(return_value=expected)

    context = build_money_context(
        conversion=conversion,
        destination_country_code="jp",
        as_of=date(2026, 9, 22),
        destination_context_builder=builder,
    )

    assert context.conversion is conversion
    assert context.destination_country_code == "JP"
    assert context.destination_state is MoneyContextState.AVAILABLE
    assert context.destination_context is expected
    assert context.payment_guidance == expected.payment
    assert context.has_payment_guidance is True
    assert context.has_local_value is False
    assert context.can_estimate_payment is True
    builder.assert_called_once_with(
        country_code="JP",
        converted_amount=Decimal("17450"),
        quote_currency="JPY",
        as_of=date(2026, 9, 22),
        price_limit=3,
    )


def test_empty_destination_context_is_distinct_from_dependency_failure():
    empty = DestinationContext(
        country_code="JP",
        country_name="Japan",
        as_of=date(2026, 9, 22),
        payment=None,
        prices=(),
    )

    context = build_money_context(
        conversion=_conversion(),
        destination_country_code="JP",
        as_of=date(2026, 9, 22),
        destination_context_builder=Mock(return_value=empty),
    )

    assert context.destination_state is MoneyContextState.EMPTY
    assert context.destination_context is empty
    assert context.has_payment_guidance is False
    assert context.has_local_value is False


@pytest.mark.parametrize(
    ("historical", "country_code"),
    [
        (True, "JP"),
        (False, ""),
    ],
)
def test_context_is_not_applicable_for_historical_or_currency_only_conversion(
    historical,
    country_code,
):
    builder = Mock()

    context = build_money_context(
        conversion=_conversion(historical=historical),
        destination_country_code=country_code,
        as_of=date(2026, 9, 22),
        destination_context_builder=builder,
    )

    assert context.destination_state is MoneyContextState.NOT_APPLICABLE
    assert context.destination_context is None
    builder.assert_not_called()


@pytest.mark.parametrize("failure", [DatabaseError("database unavailable"), ValueError("bad data")])
def test_known_enrichment_failure_degrades_without_losing_conversion(failure):
    conversion = _conversion()

    context = build_money_context(
        conversion=conversion,
        destination_country_code="JP",
        as_of=date(2026, 9, 22),
        destination_context_builder=Mock(side_effect=failure),
    )

    assert context.conversion is conversion
    assert context.destination_state is MoneyContextState.DEGRADED
    assert context.destination_context is None


def test_programming_error_is_not_silenced():
    with pytest.raises(RuntimeError, match="programming bug"):
        build_money_context(
            conversion=_conversion(),
            destination_country_code="JP",
            as_of=date(2026, 9, 22),
            destination_context_builder=Mock(side_effect=RuntimeError("programming bug")),
        )


def test_invalid_price_limit_is_rejected_before_enrichment():
    builder = Mock()

    with pytest.raises(ValueError, match="between 1 and 6"):
        build_money_context(
            conversion=_conversion(),
            destination_country_code="JP",
            price_limit=0,
            destination_context_builder=builder,
        )

    builder.assert_not_called()


def test_payment_estimate_capability_respects_temporal_and_identity_boundaries():
    current = build_money_context(
        conversion=_conversion(),
        destination_country_code="",
        as_of=date(2026, 9, 22),
    )
    historical = build_money_context(
        conversion=_conversion(historical=True),
        destination_country_code="JP",
        as_of=date(2026, 9, 22),
    )
    identity = build_money_context(
        conversion=_conversion(base="EUR", quote="EUR"),
        destination_country_code="",
        as_of=date(2026, 9, 22),
    )

    assert current.can_estimate_payment is True
    assert historical.can_estimate_payment is False
    assert identity.can_estimate_payment is False
