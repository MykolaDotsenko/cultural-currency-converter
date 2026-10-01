from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from apps.culture.services import (
    DestinationContext,
    PaymentContext,
    TypicalPriceContext,
    calculate_purchase_equivalent,
)
from apps.exchange.budget import (
    BudgetAssumptions,
    BudgetBand,
    BudgetBasis,
    BudgetCategoryAssumption,
    BudgetInterpretationState,
    BudgetScope,
)
from apps.exchange.comparison import (
    DestinationComparisonError,
    DestinationComparisonState,
    compare_destinations,
)
from apps.exchange.domain import DEFAULT_SOURCE_POLICY, ConversionResult, RateQuote
from apps.exchange.money_context import MoneyContext, MoneyContextState


def _conversion(
    *,
    quote_currency: str,
    output_amount: Decimal,
    source_amount: Decimal = Decimal("100"),
    base_currency: str = "EUR",
    historical: bool = False,
) -> ConversionResult:
    requested_date = date(2020, 1, 2) if historical else None
    return ConversionResult(
        input_amount=source_amount,
        output_amount=output_amount,
        quote=RateQuote(
            base_currency=base_currency,
            quote_currency=quote_currency,
            rate=output_amount / source_amount,
            requested_date=requested_date,
            effective_date=requested_date or date(2026, 10, 1),
            fetched_at=datetime(2026, 10, 1, 4, tzinfo=UTC),
            provider_policy=DEFAULT_SOURCE_POLICY,
            provider_keys=("ecb",),
            historical=historical,
        ),
        stale=False,
    )


def _payment(country_name: str) -> PaymentContext:
    return PaymentContext(
        summary=f"Reviewed payment context for {country_name}.",
        payment_customs="Cards are commonly accepted.",
        cash_usage="Carry some cash when useful.",
        tipping="Follow local tipping guidance.",
        atm_notes="Review disclosed ATM fees.",
        dcc_warning="Prefer transparent local-currency pricing.",
        source_name="Official source",
        source_url="https://example.com/payment",
        verified_at=datetime(2026, 9, 30, 8, tzinfo=UTC),
    )


def _price(
    *,
    country_name: str,
    currency_code: str,
    minor_units: int,
    category: str,
    label: str,
    low: Decimal,
    high: Decimal,
    converted_amount: Decimal,
    city: str = "",
    city_slug: str = "",
) -> TypicalPriceContext:
    return TypicalPriceContext(
        label=label,
        category=category,
        city=city,
        country_name=country_name,
        currency_code=currency_code,
        currency_minor_units=minor_units,
        amount_low=low,
        amount_high=high,
        observed_at=date(2026, 9, 15),
        source_class="curated_factual",
        confidence="high",
        source_name="Test source",
        source_url="https://example.com/prices",
        equivalent=calculate_purchase_equivalent(converted_amount, low, high),
        city_slug=city_slug,
    )


def _context(
    *,
    country_code: str,
    country_name: str,
    currency_code: str,
    output_amount: Decimal,
    minor_units: int,
    city_slug: str = "",
    city_name: str = "",
    categories: tuple[str, ...] = ("coffee", "casual_meal"),
    source_amount: Decimal = Decimal("100"),
    base_currency: str = "EUR",
    historical: bool = False,
) -> MoneyContext:
    prices = tuple(
        _price(
            country_name=country_name,
            currency_code=currency_code,
            minor_units=minor_units,
            category=category,
            label=category.replace("_", " ").title(),
            low=Decimal("100") if currency_code == "JPY" else Decimal("40"),
            high=Decimal("150") if currency_code == "JPY" else Decimal("60"),
            converted_amount=output_amount,
            city=city_name,
            city_slug=city_slug,
        )
        for category in categories
    )
    destination = DestinationContext(
        country_code=country_code,
        country_name=country_name,
        as_of=date(2026, 10, 1),
        payment=_payment(country_name),
        prices=prices,
        city_slug=city_slug,
        city_name=city_name,
    )
    return MoneyContext(
        conversion=_conversion(
            quote_currency=currency_code,
            output_amount=output_amount,
            source_amount=source_amount,
            base_currency=base_currency,
            historical=historical,
        ),
        destination_country_code=country_code,
        destination_city_slug=city_slug,
        as_of=date(2026, 10, 1),
        destination_context=destination,
        destination_state=MoneyContextState.AVAILABLE,
    )


def _assumptions(*, basis: BudgetBasis = BudgetBasis.REFERENCE_CONVERSION) -> BudgetAssumptions:
    return BudgetAssumptions(
        duration_days=2,
        travelers=1,
        categories=(
            BudgetCategoryAssumption("coffee", Decimal("1")),
            BudgetCategoryAssumption("casual_meal", Decimal("2")),
        ),
        basis=basis,
    )


def test_complete_comparison_preserves_each_destination_scope_and_local_currency():
    tokyo = _context(
        country_code="JP",
        country_name="Japan",
        currency_code="JPY",
        output_amount=Decimal("3000"),
        minor_units=0,
        city_slug="tokyo",
        city_name="Tokyo",
    )
    norway = _context(
        country_code="NO",
        country_name="Norway",
        currency_code="NOK",
        output_amount=Decimal("1200"),
        minor_units=2,
    )

    result = compare_destinations(
        tokyo,
        norway,
        assumptions=_assumptions(),
        left_minor_units=0,
        right_minor_units=2,
    )

    assert result.state is DestinationComparisonState.COMPLETE
    assert result.coverage_complete is True
    assert result.source_currency_code == "EUR"
    assert result.source_amount == Decimal("100")
    assert result.shared_categories == ("coffee", "casual_meal")

    assert result.left.destination_country_code == "JP"
    assert result.left.destination_city_slug == "tokyo"
    assert result.left.currency_code == "JPY"
    assert result.left.converted_amount == Decimal("3000")
    assert result.left.budget.state is BudgetInterpretationState.COMPLETE
    assert all(line.scope is BudgetScope.CITY for line in result.left.budget.lines)

    assert result.right.destination_country_code == "NO"
    assert result.right.destination_city_slug == ""
    assert result.right.currency_code == "NOK"
    assert result.right.converted_amount == Decimal("1200.00")
    assert result.right.budget.state is BudgetInterpretationState.COMPLETE
    assert all(line.scope is BudgetScope.NATIONAL for line in result.right.budget.lines)
    assert result.left.payment_guidance is not None
    assert result.right.payment_guidance is not None


def test_partial_comparison_keeps_known_lines_without_inventing_missing_category():
    complete = _context(
        country_code="JP",
        country_name="Japan",
        currency_code="JPY",
        output_amount=Decimal("3000"),
        minor_units=0,
    )
    partial = _context(
        country_code="NO",
        country_name="Norway",
        currency_code="NOK",
        output_amount=Decimal("1200"),
        minor_units=2,
        categories=("coffee",),
    )

    result = compare_destinations(
        complete,
        partial,
        assumptions=_assumptions(),
        left_minor_units=0,
        right_minor_units=2,
    )

    assert result.state is DestinationComparisonState.PARTIAL
    assert result.coverage_complete is False
    assert result.shared_categories == ("coffee",)
    assert result.right.budget.state is BudgetInterpretationState.INSUFFICIENT_DATA
    assert result.right.budget.band is None
    assert result.right.budget.missing_categories == ("casual_meal",)


@pytest.mark.parametrize(
    ("left", "right", "message"),
    [
        (
            _context(
                country_code="JP",
                country_name="Japan",
                currency_code="JPY",
                output_amount=Decimal("3000"),
                minor_units=0,
                source_amount=Decimal("100"),
            ),
            _context(
                country_code="NO",
                country_name="Norway",
                currency_code="NOK",
                output_amount=Decimal("2400"),
                minor_units=2,
                source_amount=Decimal("200"),
            ),
            "same source amount",
        ),
        (
            _context(
                country_code="JP",
                country_name="Japan",
                currency_code="JPY",
                output_amount=Decimal("3000"),
                minor_units=0,
                base_currency="EUR",
            ),
            _context(
                country_code="NO",
                country_name="Norway",
                currency_code="NOK",
                output_amount=Decimal("1200"),
                minor_units=2,
                base_currency="USD",
            ),
            "same source currency",
        ),
    ],
)
def test_comparison_rejects_different_source_basis(left, right, message):
    with pytest.raises(DestinationComparisonError, match=message):
        compare_destinations(
            left,
            right,
            assumptions=_assumptions(),
            left_minor_units=0,
            right_minor_units=2,
        )


def test_comparison_rejects_identical_destination_scope():
    left = _context(
        country_code="JP",
        country_name="Japan",
        currency_code="JPY",
        output_amount=Decimal("3000"),
        minor_units=0,
        city_slug="tokyo",
        city_name="Tokyo",
    )
    right = _context(
        country_code="JP",
        country_name="Japan",
        currency_code="JPY",
        output_amount=Decimal("3000"),
        minor_units=0,
        city_slug="tokyo",
        city_name="Tokyo",
    )

    with pytest.raises(DestinationComparisonError, match="different destination"):
        compare_destinations(
            left,
            right,
            assumptions=_assumptions(),
            left_minor_units=0,
            right_minor_units=0,
        )


def test_comparison_rejects_historical_context():
    historical = _context(
        country_code="JP",
        country_name="Japan",
        currency_code="JPY",
        output_amount=Decimal("3000"),
        minor_units=0,
        historical=True,
    )
    current = _context(
        country_code="NO",
        country_name="Norway",
        currency_code="NOK",
        output_amount=Decimal("1200"),
        minor_units=2,
    )

    with pytest.raises(DestinationComparisonError, match="historical"):
        compare_destinations(
            historical,
            current,
            assumptions=_assumptions(),
            left_minor_units=0,
            right_minor_units=2,
        )


def test_comparison_rejects_payment_estimate_basis_until_assumptions_can_be_shared():
    left = _context(
        country_code="JP",
        country_name="Japan",
        currency_code="JPY",
        output_amount=Decimal("3000"),
        minor_units=0,
    )
    right = _context(
        country_code="NO",
        country_name="Norway",
        currency_code="NOK",
        output_amount=Decimal("1200"),
        minor_units=2,
    )

    with pytest.raises(DestinationComparisonError, match="reference-conversion"):
        compare_destinations(
            left,
            right,
            assumptions=_assumptions(basis=BudgetBasis.PAYMENT_ESTIMATE),
            left_minor_units=0,
            right_minor_units=2,
        )


def test_comparison_does_not_expose_a_winner_or_cross_currency_price_ratio():
    left = _context(
        country_code="JP",
        country_name="Japan",
        currency_code="JPY",
        output_amount=Decimal("3000"),
        minor_units=0,
    )
    right = _context(
        country_code="NO",
        country_name="Norway",
        currency_code="NOK",
        output_amount=Decimal("1200"),
        minor_units=2,
    )

    result = compare_destinations(
        left,
        right,
        assumptions=_assumptions(),
        left_minor_units=0,
        right_minor_units=2,
    )

    assert not hasattr(result, "winner")
    assert not hasattr(result, "cheaper_destination")
    assert result.left.budget.band in set(BudgetBand)
    assert result.right.budget.band in set(BudgetBand)
