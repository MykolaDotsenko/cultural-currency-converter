from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation, localcontext

from apps.exchange.domain import ConversionResult
from apps.exchange.payment_estimate import MAX_FX_MARKUP_PERCENT


MAX_SHOPPING_COMPONENT = Decimal("1000000000")


class ShoppingCalculationError(ValueError):
    """Raised when an explicit shopping assumption cannot be calculated safely."""


@dataclass(frozen=True, slots=True)
class ShoppingAssumptions:
    """Explicit foreign-purchase inputs in the purchase currency.

    Duties, taxes and issuer/merchant fees are intentionally absent unless the
    user can enter them as a known fee. The domain never invents those costs.
    """

    item_price: Decimal
    shipping: Decimal = Decimal("0")
    known_fees: Decimal = Decimal("0")
    fx_markup_percent: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        _validate_component(self.item_price, label="Item price", allow_zero=False)
        _validate_component(self.shipping, label="Shipping", allow_zero=True)
        _validate_component(self.known_fees, label="Known fees", allow_zero=True)
        _validate_component(self.fx_markup_percent, label="FX markup", allow_zero=True)
        if self.fx_markup_percent > MAX_FX_MARKUP_PERCENT:
            raise ShoppingCalculationError(f"FX markup cannot exceed {MAX_FX_MARKUP_PERCENT}%.")

    @property
    def purchase_total(self) -> Decimal:
        try:
            with localcontext() as context:
                context.prec = 64
                total = self.item_price + self.shipping + self.known_fees
        except InvalidOperation as exc:
            raise ShoppingCalculationError("Shopping total cannot be represented safely.") from exc
        if not total.is_finite() or total <= 0 or total > MAX_SHOPPING_COMPONENT:
            raise ShoppingCalculationError("Shopping total is outside supported bounds.")
        return total


@dataclass(frozen=True, slots=True)
class ShoppingEstimate:
    """Deterministic cost estimate layered on one trusted current conversion."""

    assumptions: ShoppingAssumptions
    conversion: ConversionResult
    reference_home_cost: Decimal
    estimated_home_cost: Decimal
    fx_markup_cost: Decimal
    unknown_costs: tuple[str, ...] = (
        "duties not explicitly entered",
        "taxes not explicitly entered",
        "issuer or merchant fees not explicitly entered",
    )

    @property
    def purchase_currency(self) -> str:
        return self.conversion.quote.base_currency

    @property
    def home_currency(self) -> str:
        return self.conversion.quote.quote_currency


def calculate_shopping_estimate(
    *,
    conversion: ConversionResult,
    assumptions: ShoppingAssumptions,
    home_minor_units: int,
) -> ShoppingEstimate:
    """Calculate one foreign-purchase estimate from trusted FX truth.

    The canonical conversion direction is purchase currency -> home currency.
    Its input must equal item + shipping + explicitly known purchase-currency
    fees. Optional FX markup is then applied transparently to the trusted
    reference home-currency cost.
    """

    if not isinstance(assumptions, ShoppingAssumptions):
        raise ShoppingCalculationError("Shopping assumptions are invalid.")
    if conversion.quote.historical:
        raise ShoppingCalculationError("Shopping estimates require a current reference conversion.")
    if conversion.quote.base_currency == conversion.quote.quote_currency:
        raise ShoppingCalculationError(
            "Shopping estimates require different purchase and home currencies."
        )
    if conversion.input_amount != assumptions.purchase_total:
        raise ShoppingCalculationError(
            "Trusted conversion input must equal the explicit shopping total."
        )
    if (
        isinstance(home_minor_units, bool)
        or not isinstance(home_minor_units, int)
        or not 0 <= home_minor_units <= 6
    ):
        raise ShoppingCalculationError("Home currency minor units must be between 0 and 6.")
    if not conversion.output_amount.is_finite() or conversion.output_amount < 0:
        raise ShoppingCalculationError("Reference home-currency cost is invalid.")

    quantum = Decimal(1).scaleb(-home_minor_units)
    try:
        with localcontext() as context:
            context.prec = 64
            reference = conversion.output_amount.quantize(
                quantum,
                rounding=ROUND_HALF_EVEN,
            )
            multiplier = Decimal("1") + (assumptions.fx_markup_percent / Decimal("100"))
            estimated = (reference * multiplier).quantize(
                quantum,
                rounding=ROUND_HALF_EVEN,
            )
            markup_cost = (estimated - reference).quantize(
                quantum,
                rounding=ROUND_HALF_EVEN,
            )
    except InvalidOperation as exc:
        raise ShoppingCalculationError(
            "Shopping estimate cannot be represented at the requested precision."
        ) from exc

    if estimated < reference or markup_cost < 0:
        raise ShoppingCalculationError(
            "Non-negative shopping assumptions produced an invalid estimate."
        )

    return ShoppingEstimate(
        assumptions=assumptions,
        conversion=conversion,
        reference_home_cost=reference,
        estimated_home_cost=estimated,
        fx_markup_cost=markup_cost,
    )


def _validate_component(value: Decimal, *, label: str, allow_zero: bool) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ShoppingCalculationError(f"{label} must be a finite Decimal.")
    if value < 0 or (not allow_zero and value == 0):
        qualifier = "non-negative" if allow_zero else "greater than zero"
        raise ShoppingCalculationError(f"{label} must be {qualifier}.")
    if value > MAX_SHOPPING_COMPONENT:
        raise ShoppingCalculationError(f"{label} must be no greater than {MAX_SHOPPING_COMPONENT}.")
