from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from apps.culture.services import DestinationContext, TypicalPriceContext, calculate_purchase_equivalent
from apps.exchange.domain import DEFAULT_SOURCE_POLICY, ConversionResult, RateQuote
from apps.exchange.money_context import MoneyContext, MoneyContextState
from apps.exchange.same_amount import (
    SameAmountDestinationSnapshot,
    SameAmountDestinationsError,
    compose_same_amount_across_destinations,
)


def _context(
    *,
    country_code: str,
    country_name: str,
    currency_code: str,
    output_amount: Decimal,
    city_slug: str = "",
    city_name: str = "",
    source_amount: Decimal = Decimal("100"),
    source_currency: str = "EUR",
) -> MoneyContext:
    quote = RateQuote(
        base_currency=source_currency,
        quote_currency=currency_code,
        rate=output_amount / source_amount,
        requested_date=None,
        effective_date=date(2026, 10, 2),
        fetched_at=datetime(2026, 10, 2, 2, tzinfo=UTC),
        provider_policy=DEFAULT_SOURCE_POLICY,
        provider_keys=("ecb",),
        historical=False,
    )
    conversion = ConversionResult(
        input_amount=source_amount,
        output_amount=output_amount,
        quote=quote,
        stale=False,
    )
    price = TypicalPriceContext(
        label="Coffee",
        category="coffee",
        city=city_name,
        country_name=country_name,
        currency_code=currency_code,
        currency_minor_units=0 if currency_code == "JPY" else 2,
        amount_low=Decimal("100") if currency_code == "JPY" else Decimal("4"),
        amount_high=Decimal("150") if currency_code == "JPY" else Decimal("6"),
        observed_at=date(2026, 10, 1),
        source_class="curated_factual",
        confidence="high",
        source_name="Reviewed price source",
        source_url="https://example.com/prices",
        equivalent=calculate_purchase_equivalent(
            output_amount,
            Decimal("100") if currency_code == "JPY" else Decimal("4"),
            Decimal("150") if currency_code == "JPY" else Decimal("6"),
        ),
        city_slug=city_slug,
    )
    destination = DestinationContext(
        country_code=country_code,
        country_name=country_name,
        as_of=date(2026, 10, 2),
        payment=None,
        prices=(price,),
        city_slug=city_slug,
        city_name=city_name,
    )
    return MoneyContext(
        conversion=conversion,
        destination_country_code=country_code,
        destination_city_slug=city_slug,
        as_of=date(2026, 10, 2),
        destination_context=destination,
        destination_state=MoneyContextState.AVAILABLE,
    )


def _snapshot(
    token: str,
    scope_label: str,
    context: MoneyContext,
    *,
    minor_units: int,
) -> SameAmountDestinationSnapshot:
    return SameAmountDestinationSnapshot(
        token=token,
        scope_label=scope_label,
        country_code=context.destination_country_code,
        city_slug=context.destination_city_slug,
        currency_code=context.conversion.quote.quote_currency,
        minor_units=minor_units,
        context=context,
    )


def test_same_amount_contract_preserves_selection_order_and_scope():
    toronto = _snapshot(
        "CA:toronto",
        "Toronto, Canada",
        _context(
            country_code="CA",
            country_name="Canada",
            currency_code="CAD",
            output_amount=Decimal("151.23"),
            city_slug="toronto",
            city_name="Toronto",
        ),
        minor_units=2,
    )
    tokyo = _snapshot(
        "JP:tokyo",
        "Tokyo, Japan",
        _context(
            country_code="JP",
            country_name="Japan",
            currency_code="JPY",
            output_amount=Decimal("17450"),
            city_slug="tokyo",
            city_name="Tokyo",
        ),
        minor_units=0,
    )

    result = compose_same_amount_across_destinations((toronto, tokyo))

    assert result.source_amount == Decimal("100")
    assert result.source_currency_code == "EUR"
    assert [item.token for item in result.destinations] == ["CA:toronto", "JP:tokyo"]
    assert [item.converted_amount for item in result.destinations] == [
        Decimal("151.23"),
        Decimal("17450"),
    ]
    assert not hasattr(result, "winner")
    assert not hasattr(result, "cheapest_destination")
    assert not hasattr(result, "ranking")


def test_same_amount_contract_rejects_duplicate_destination_scope():
    context = _context(
        country_code="JP",
        country_name="Japan",
        currency_code="JPY",
        output_amount=Decimal("17450"),
        city_slug="tokyo",
        city_name="Tokyo",
    )
    first = _snapshot("JP:tokyo", "Tokyo, Japan", context, minor_units=0)
    second = _snapshot("JP:tokyo-copy", "Tokyo, Japan", context, minor_units=0)

    with pytest.raises(SameAmountDestinationsError, match="duplicate"):
        compose_same_amount_across_destinations((first, second))


@pytest.mark.parametrize(
    ("changed", "message"),
    [
        ("amount", "same source amount"),
        ("currency", "same source currency"),
    ],
)
def test_same_amount_contract_rejects_different_source_basis(changed, message):
    first = _snapshot(
        "JP:tokyo",
        "Tokyo, Japan",
        _context(
            country_code="JP",
            country_name="Japan",
            currency_code="JPY",
            output_amount=Decimal("17450"),
            city_slug="tokyo",
            city_name="Tokyo",
        ),
        minor_units=0,
    )
    second = _snapshot(
        "CA:toronto",
        "Toronto, Canada",
        _context(
            country_code="CA",
            country_name="Canada",
            currency_code="CAD",
            output_amount=Decimal("302.46") if changed == "amount" else Decimal("151.23"),
            city_slug="toronto",
            city_name="Toronto",
            source_amount=Decimal("200") if changed == "amount" else Decimal("100"),
            source_currency="USD" if changed == "currency" else "EUR",
        ),
        minor_units=2,
    )

    with pytest.raises(SameAmountDestinationsError, match=message):
        compose_same_amount_across_destinations((first, second))
