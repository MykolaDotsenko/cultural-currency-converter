from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from apps.culture.services import (
    DestinationContext,
    TypicalPriceContext,
    calculate_purchase_equivalent,
)
from apps.exchange.budget import (
    BudgetAssumptions,
    BudgetBand,
    BudgetBasis,
    BudgetCategoryAssumption,
    BudgetInterpretationError,
    BudgetInterpretationState,
    BudgetScope,
    interpret_budget,
)
from apps.exchange.domain import DEFAULT_SOURCE_POLICY, ConversionResult, RateQuote
from apps.exchange.money_context import (
    MoneyContext,
    MoneyContextState,
    apply_payment_assumptions,
)
from apps.exchange.payment_estimate import PaymentEstimateAssumptions


def _conversion(
    *,
    output_amount: Decimal = Decimal("1000"),
    historical: bool = False,
) -> ConversionResult:
    requested_date = date(2020, 1, 2) if historical else None
    return ConversionResult(
        input_amount=Decimal("100"),
        output_amount=output_amount,
        quote=RateQuote(
            base_currency="EUR",
            quote_currency="JPY",
            rate=output_amount / Decimal("100"),
            requested_date=requested_date,
            effective_date=requested_date or date(2026, 9, 30),
            fetched_at=datetime(2026, 9, 30, 8, tzinfo=UTC),
            provider_policy=DEFAULT_SOURCE_POLICY,
            provider_keys=("ecb",),
            historical=historical,
        ),
        stale=False,
    )


def _price(
    *,
    category: str,
    label: str,
    low: Decimal,
    high: Decimal | None = None,
    city: str = "",
    city_slug: str = "",
) -> TypicalPriceContext:
    return TypicalPriceContext(
        label=label,
        category=category,
        city=city,
        country_name="Japan",
        currency_code="JPY",
        currency_minor_units=0,
        amount_low=low,
        amount_high=high,
        observed_at=date(2026, 9, 1),
        source_class="curated_factual",
        confidence="high",
        source_name="Test source",
        source_url="https://example.com/prices",
        equivalent=calculate_purchase_equivalent(Decimal("1000"), low, high),
        city_slug=city_slug,
    )


def _context(
    *,
    output_amount: Decimal = Decimal("1000"),
    prices: tuple[TypicalPriceContext, ...],
    city_slug: str = "",
    historical: bool = False,
) -> MoneyContext:
    destination = DestinationContext(
        country_code="JP",
        country_name="Japan",
        as_of=date(2026, 9, 30),
        payment=None,
        prices=prices,
        city_slug=city_slug,
        city_name="Tokyo" if city_slug else "",
    )
    return MoneyContext(
        conversion=_conversion(output_amount=output_amount, historical=historical),
        destination_country_code="JP",
        destination_city_slug=city_slug,
        as_of=date(2026, 9, 30),
        destination_context=destination,
        destination_state=MoneyContextState.AVAILABLE,
    )


def _assumptions(
    *categories: BudgetCategoryAssumption,
    duration_days: int = 2,
    travelers: int = 1,
    basis: BudgetBasis = BudgetBasis.REFERENCE_CONVERSION,
) -> BudgetAssumptions:
    return BudgetAssumptions(
        duration_days=duration_days,
        travelers=travelers,
        categories=tuple(categories),
        basis=basis,
    )


def test_complete_budget_uses_explicit_daily_basket_and_preserves_provenance():
    context = _context(
        prices=(
            _price(
                category="coffee",
                label="Coffee",
                low=Decimal("100"),
                high=Decimal("150"),
            ),
            _price(
                category="casual_meal",
                label="Casual meal",
                low=Decimal("200"),
                high=Decimal("300"),
            ),
        ),
    )

    result = interpret_budget(
        context,
        assumptions=_assumptions(
            BudgetCategoryAssumption("coffee", Decimal("1")),
            BudgetCategoryAssumption("casual_meal", Decimal("2")),
        ),
        destination_minor_units=0,
    )

    assert result.state is BudgetInterpretationState.COMPLETE
    assert result.band is BudgetBand.WITHIN_REFERENCE
    assert result.available_destination_budget == Decimal("1000")
    assert result.daily_budget_per_person == Decimal("500")
    assert result.known_reference_total_low == Decimal("1000")
    assert result.known_reference_total_high == Decimal("1500")
    assert result.missing_categories == ()
    assert [line.category for line in result.lines] == ["coffee", "casual_meal"]
    assert result.lines[0].scope is BudgetScope.NATIONAL
    assert result.lines[0].source_url == "https://example.com/prices"


@pytest.mark.parametrize(
    ("available", "expected"),
    [
        (Decimal("999"), BudgetBand.BELOW_REFERENCE),
        (Decimal("1000"), BudgetBand.WITHIN_REFERENCE),
        (Decimal("1500"), BudgetBand.WITHIN_REFERENCE),
        (Decimal("1501"), BudgetBand.ABOVE_REFERENCE),
    ],
)
def test_budget_band_uses_reference_range_boundaries(available, expected):
    context = _context(
        output_amount=available,
        prices=(
            _price(
                category="casual_meal",
                label="Casual meal",
                low=Decimal("500"),
                high=Decimal("750"),
            ),
        ),
    )

    result = interpret_budget(
        context,
        assumptions=_assumptions(
            BudgetCategoryAssumption("casual_meal", Decimal("1")),
        ),
        destination_minor_units=0,
    )

    assert result.band is expected


def test_missing_requested_category_returns_insufficient_data_without_guessing_band():
    context = _context(
        prices=(
            _price(
                category="coffee",
                label="Coffee",
                low=Decimal("100"),
                high=Decimal("150"),
            ),
        ),
    )

    result = interpret_budget(
        context,
        assumptions=_assumptions(
            BudgetCategoryAssumption("coffee", Decimal("1")),
            BudgetCategoryAssumption("transit", Decimal("2")),
        ),
        destination_minor_units=0,
    )

    assert result.state is BudgetInterpretationState.INSUFFICIENT_DATA
    assert result.band is None
    assert result.missing_categories == ("transit",)
    assert result.known_reference_total_low == Decimal("200")
    assert result.known_reference_total_high == Decimal("300")


def test_country_budget_does_not_silently_treat_city_price_as_national():
    context = _context(
        prices=(
            _price(
                category="coffee",
                label="Tokyo coffee",
                low=Decimal("400"),
                city="Tokyo",
                city_slug="tokyo",
            ),
        ),
    )

    result = interpret_budget(
        context,
        assumptions=_assumptions(
            BudgetCategoryAssumption("coffee", Decimal("1")),
        ),
        destination_minor_units=0,
    )

    assert result.state is BudgetInterpretationState.INSUFFICIENT_DATA
    assert result.lines == ()
    assert result.missing_categories == ("coffee",)


def test_city_budget_uses_matching_city_first_and_allows_explicit_national_fallback():
    context = _context(
        city_slug="tokyo",
        prices=(
            _price(
                category="coffee",
                label="Tokyo coffee",
                low=Decimal("400"),
                high=Decimal("500"),
                city="Tokyo",
                city_slug="tokyo",
            ),
            _price(
                category="transit",
                label="National transit anchor",
                low=Decimal("200"),
                city="",
                city_slug="",
            ),
        ),
    )

    result = interpret_budget(
        context,
        assumptions=_assumptions(
            BudgetCategoryAssumption("coffee", Decimal("1")),
            BudgetCategoryAssumption("transit", Decimal("1")),
        ),
        destination_minor_units=0,
    )

    assert result.state is BudgetInterpretationState.COMPLETE
    assert [line.scope for line in result.lines] == [BudgetScope.CITY, BudgetScope.NATIONAL]
    assert result.lines[0].city_slug == "tokyo"
    assert result.lines[1].scope_label == "Japan · national estimate"


def test_payment_estimate_basis_uses_explicit_payment_scenario_not_reference_amount():
    context = _context(
        output_amount=Decimal("1000"),
        prices=(
            _price(
                category="coffee",
                label="Coffee",
                low=Decimal("400"),
            ),
        ),
    )
    context = apply_payment_assumptions(
        context,
        assumptions=PaymentEstimateAssumptions(
            fx_markup_percent=Decimal("0"),
            source_fixed_fee=Decimal("10"),
            destination_fixed_fee=Decimal("0"),
        ),
        destination_minor_units=0,
    )

    result = interpret_budget(
        context,
        assumptions=_assumptions(
            BudgetCategoryAssumption("coffee", Decimal("1")),
            duration_days=1,
            basis=BudgetBasis.PAYMENT_ESTIMATE,
        ),
        destination_minor_units=0,
    )

    assert result.available_destination_budget == Decimal("900")
    assert result.basis is BudgetBasis.PAYMENT_ESTIMATE
    assert result.band is BudgetBand.ABOVE_REFERENCE


def test_payment_estimate_basis_requires_attached_estimate():
    context = _context(
        prices=(
            _price(
                category="coffee",
                label="Coffee",
                low=Decimal("100"),
            ),
        ),
    )

    with pytest.raises(BudgetInterpretationError, match="requires a payment estimate"):
        interpret_budget(
            context,
            assumptions=_assumptions(
                BudgetCategoryAssumption("coffee", Decimal("1")),
                basis=BudgetBasis.PAYMENT_ESTIMATE,
            ),
            destination_minor_units=0,
        )


def test_historical_budget_interpretation_is_rejected():
    context = _context(
        historical=True,
        prices=(
            _price(
                category="coffee",
                label="Coffee",
                low=Decimal("100"),
            ),
        ),
    )

    with pytest.raises(BudgetInterpretationError, match="historical"):
        interpret_budget(
            context,
            assumptions=_assumptions(
                BudgetCategoryAssumption("coffee", Decimal("1")),
            ),
            destination_minor_units=0,
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"duration_days": 0},
        {"duration_days": 366},
        {"travelers": 0},
        {"travelers": 21},
    ],
)
def test_budget_assumption_bounds(kwargs):
    values = {
        "duration_days": 2,
        "travelers": 1,
        "categories": (BudgetCategoryAssumption("coffee", Decimal("1")),),
    }
    values.update(kwargs)

    with pytest.raises(BudgetInterpretationError):
        BudgetAssumptions(**values)


def test_duplicate_budget_categories_are_rejected():
    with pytest.raises(BudgetInterpretationError, match="unique"):
        BudgetAssumptions(
            duration_days=2,
            travelers=1,
            categories=(
                BudgetCategoryAssumption("coffee", Decimal("1")),
                BudgetCategoryAssumption(" Coffee ", Decimal("2")),
            ),
        )


@pytest.mark.parametrize("value", [Decimal("0"), Decimal("-1"), Decimal("NaN")])
def test_category_units_must_be_finite_and_positive(value):
    with pytest.raises(BudgetInterpretationError, match="finite positive"):
        BudgetCategoryAssumption("coffee", value)


@pytest.mark.parametrize("minor_units", [-1, 7, True])
def test_destination_minor_units_are_bounded(minor_units):
    context = _context(
        prices=(
            _price(
                category="coffee",
                label="Coffee",
                low=Decimal("100"),
            ),
        ),
    )

    with pytest.raises(BudgetInterpretationError, match="minor units"):
        interpret_budget(
            context,
            assumptions=_assumptions(
                BudgetCategoryAssumption("coffee", Decimal("1")),
            ),
            destination_minor_units=minor_units,
        )


def test_budget_rejects_typical_price_minor_unit_mismatch():
    context = _context(
        prices=(
            _price(
                category="coffee",
                label="Coffee",
                low=Decimal("100"),
            ),
        ),
    )

    with pytest.raises(BudgetInterpretationError, match="minor units do not match"):
        interpret_budget(
            context,
            assumptions=_assumptions(
                BudgetCategoryAssumption("coffee", Decimal("1")),
            ),
            destination_minor_units=2,
        )


def test_budget_basis_must_be_explicit_enum_value():
    with pytest.raises(BudgetInterpretationError, match="Budget basis"):
        BudgetAssumptions(
            duration_days=2,
            travelers=1,
            categories=(BudgetCategoryAssumption("coffee", Decimal("1")),),
            basis="reference_conversion",  # type: ignore[arg-type]
        )
