from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from apps.exchange.domain import DEFAULT_SOURCE_POLICY, ConversionResult, RateQuote
from apps.exchange.shopping import ShoppingAssumptions
from apps.exchange.shopping_snapshot import (
    ShoppingContextTokenError,
    build_shopping_context_snapshot_token,
    load_shopping_context_snapshot_token,
)


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


def test_shopping_snapshot_round_trips_exact_inputs_and_fx_semantics():
    assumptions = ShoppingAssumptions(
        item_price=Decimal("100"),
        shipping=Decimal("20"),
        known_fees=Decimal("10"),
        fx_markup_percent=Decimal("2.5"),
    )
    token = build_shopping_context_snapshot_token(
        conversion=_conversion(),
        assumptions=assumptions,
        purchase_country_code="US",
    )

    snapshot = load_shopping_context_snapshot_token(token)

    assert snapshot.purchase_country_code == "US"
    assert snapshot.assumptions == assumptions
    assert snapshot.conversion.input_amount == Decimal("130")
    assert snapshot.conversion.output_amount == Decimal("117.00")
    assert snapshot.conversion.quote.base_currency == "USD"
    assert snapshot.conversion.quote.quote_currency == "EUR"
    assert snapshot.conversion.quote.provider_keys == ("ecb",)


def test_shopping_snapshot_rejects_tampering():
    token = build_shopping_context_snapshot_token(
        conversion=_conversion(),
        assumptions=ShoppingAssumptions(item_price=Decimal("130")),
    )

    with pytest.raises(ShoppingContextTokenError, match="invalid"):
        load_shopping_context_snapshot_token(f"{token}tampered")
