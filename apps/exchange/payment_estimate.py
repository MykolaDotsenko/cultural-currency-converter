from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation, localcontext

from apps.exchange.domain import FxDomainError, validate_rate_decimal

MAX_FX_MARKUP_PERCENT = Decimal("25")
_EXTRA_CALCULATION_PRECISION = 32


class PaymentEstimateError(FxDomainError):
    pass


class PaymentEstimateRepresentationError(PaymentEstimateError):
    pass


@dataclass(frozen=True, slots=True)
class PaymentEstimate:
    source_budget: Decimal
    reference_destination_amount: Decimal
    estimated_destination_amount: Decimal
    fx_markup_percent: Decimal
    source_fixed_fee: Decimal
    destination_fixed_fee: Decimal
    effective_source_amount: Decimal

    @property
    def destination_value_lost(self) -> Decimal:
        return self.reference_destination_amount - self.estimated_destination_amount


def estimate_payment_value(
    *,
    source_budget: Decimal,
    reference_destination_amount: Decimal,
    rate: Decimal,
    fx_markup_percent: Decimal,
    source_fixed_fee: Decimal,
    destination_fixed_fee: Decimal,
    destination_minor_units: int,
) -> PaymentEstimate:
    """Estimate destination value from a fixed source-currency budget.

    FX markup means an additional source-currency cost over the reference
    rate. Fixed fees are explicit user assumptions: one in the source
    currency and one in the destination currency.
    """

    _validate_non_negative_decimal(source_budget, label="Source budget")
    _validate_non_negative_decimal(
        reference_destination_amount,
        label="Reference destination amount",
    )
    validate_rate_decimal(rate)
    _validate_non_negative_decimal(fx_markup_percent, label="FX markup")
    _validate_non_negative_decimal(source_fixed_fee, label="Source fixed fee")
    _validate_non_negative_decimal(destination_fixed_fee, label="Destination fixed fee")

    if fx_markup_percent > MAX_FX_MARKUP_PERCENT:
        raise PaymentEstimateError(f"FX markup cannot exceed {MAX_FX_MARKUP_PERCENT}%.")
    if source_fixed_fee > source_budget:
        raise PaymentEstimateError("Source fixed fee cannot exceed the source budget.")
    if destination_fixed_fee > reference_destination_amount:
        raise PaymentEstimateError(
            "Destination fixed fee cannot exceed the reference destination amount."
        )
    if isinstance(destination_minor_units, bool) or not isinstance(destination_minor_units, int):
        raise PaymentEstimateError("Destination minor units must be an integer.")
    if not 0 <= destination_minor_units <= 6:
        raise PaymentEstimateError("Destination minor units must be between 0 and 6.")

    quantum = Decimal(1).scaleb(-destination_minor_units)
    try:
        with localcontext() as context:
            context.prec = max(
                64,
                len(rate.as_tuple().digits) + _EXTRA_CALCULATION_PRECISION,
            )
            markup_multiplier = Decimal("1") + (fx_markup_percent / Decimal("100"))
            effective_source_amount = (source_budget - source_fixed_fee) / markup_multiplier
            before_destination_fee = effective_source_amount * rate
            estimated_destination_amount = max(
                before_destination_fee - destination_fixed_fee,
                Decimal("0"),
            ).quantize(quantum, rounding=ROUND_HALF_EVEN)
            reference_amount = reference_destination_amount.quantize(
                quantum,
                rounding=ROUND_HALF_EVEN,
            )
    except InvalidOperation as exc:
        raise PaymentEstimateRepresentationError(
            "Payment estimate cannot be represented at the requested precision."
        ) from exc

    if estimated_destination_amount > reference_amount:
        # Non-negative fee/markup assumptions should never improve the reference value.
        raise PaymentEstimateError("Payment estimate assumptions produced an invalid result.")

    return PaymentEstimate(
        source_budget=source_budget,
        reference_destination_amount=reference_amount,
        estimated_destination_amount=estimated_destination_amount,
        fx_markup_percent=fx_markup_percent,
        source_fixed_fee=source_fixed_fee,
        destination_fixed_fee=destination_fixed_fee,
        effective_source_amount=effective_source_amount,
    )


def _validate_non_negative_decimal(value: Decimal, *, label: str) -> None:
    if not isinstance(value, Decimal):
        raise PaymentEstimateError(f"{label} must be a Decimal.")
    if not value.is_finite() or value < 0:
        raise PaymentEstimateError(f"{label} must be a finite non-negative Decimal.")
