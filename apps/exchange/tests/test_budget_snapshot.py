from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from apps.culture.services import DestinationContext
from apps.exchange.budget_snapshot import (
    BudgetContextTokenError,
    build_budget_context_snapshot_token,
    load_budget_context_snapshot_token,
)
from apps.exchange.domain import DEFAULT_SOURCE_POLICY, ConversionResult, RateQuote
from apps.exchange.money_context import MoneyContext, MoneyContextState


def _context(*, historical: bool = False, city_slug: str = "") -> MoneyContext:
    requested_date = date(2026, 9, 18) if historical else None
    quote = RateQuote(
        base_currency="EUR",
        quote_currency="JPY",
        rate=Decimal("174.50"),
        requested_date=requested_date,
        effective_date=requested_date or date(2026, 9, 30),
        fetched_at=datetime(2026, 9, 30, 8, tzinfo=UTC),
        provider_policy=DEFAULT_SOURCE_POLICY,
        provider_keys=("ecb",),
        historical=historical,
    )
    conversion = ConversionResult(
        input_amount=Decimal("100"),
        output_amount=Decimal("17450"),
        quote=quote,
        stale=True,
    )
    if historical:
        return MoneyContext(
            conversion=conversion,
            destination_country_code="JP",
            destination_city_slug=city_slug,
            as_of=date(2026, 9, 30),
            destination_context=None,
            destination_state=MoneyContextState.NOT_APPLICABLE,
        )

    destination = DestinationContext(
        country_code="JP",
        country_name="Japan",
        as_of=date(2026, 9, 30),
        payment=None,
        prices=(),
        city_slug=city_slug,
        city_name="Tokyo" if city_slug else "",
    )
    return MoneyContext(
        conversion=conversion,
        destination_country_code="JP",
        destination_city_slug=city_slug,
        as_of=date(2026, 9, 30),
        destination_context=destination,
        destination_state=MoneyContextState.EMPTY,
    )


def test_budget_context_snapshot_round_trips_conversion_and_scope():
    token = build_budget_context_snapshot_token(_context(city_slug="tokyo"))

    snapshot = load_budget_context_snapshot_token(token)

    assert snapshot.destination_country_code == "JP"
    assert snapshot.destination_city_slug == "tokyo"
    assert snapshot.as_of == date(2026, 9, 30)
    assert snapshot.conversion.input_amount == Decimal("100")
    assert snapshot.conversion.output_amount == Decimal("17450")
    assert snapshot.conversion.quote.base_currency == "EUR"
    assert snapshot.conversion.quote.quote_currency == "JPY"
    assert snapshot.conversion.quote.rate == Decimal("174.50")
    assert snapshot.conversion.quote.effective_date == date(2026, 9, 30)
    assert snapshot.conversion.quote.fetched_at == datetime(2026, 9, 30, 8, tzinfo=UTC)
    assert snapshot.conversion.quote.provider_keys == ("ecb",)
    assert snapshot.conversion.stale is True


def test_budget_context_snapshot_rejects_tampering():
    token = build_budget_context_snapshot_token(_context())
    tampered = f"{token[:-1]}x"

    with pytest.raises(BudgetContextTokenError, match="invalid"):
        load_budget_context_snapshot_token(tampered)


def test_budget_context_snapshot_is_not_created_for_historical_conversion():
    with pytest.raises(BudgetContextTokenError, match="current conversions only"):
        build_budget_context_snapshot_token(_context(historical=True))
