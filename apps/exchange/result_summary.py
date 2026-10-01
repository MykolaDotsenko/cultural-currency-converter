from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal
from enum import StrEnum

from apps.exchange.domain import ConversionResult
from apps.exchange.money_context import MoneyContext, MoneyContextState


class SmartResultSummaryKind(StrEnum):
    IDENTITY = "identity"
    HISTORICAL = "historical"
    CACHED = "cached"
    LOCAL_VALUE = "local_value"
    PAYMENT = "payment"
    REFERENCE = "reference"


@dataclass(frozen=True, slots=True)
class SmartResultSummary:
    kind: SmartResultSummaryKind
    text: str
    evidence_label: str = ""
    evidence_url: str = ""


def build_smart_result_summary(
    conversion: ConversionResult,
    *,
    money_context: MoneyContext | None = None,
) -> SmartResultSummary:
    same_currency = conversion.quote.base_currency == conversion.quote.quote_currency

    if conversion.quote.historical:
        if same_currency:
            return SmartResultSummary(
                kind=SmartResultSummaryKind.HISTORICAL,
                text=(
                    "This is an exact 1:1 historical identity conversion; "
                    "it does not describe historical purchasing power."
                ),
            )
        return SmartResultSummary(
            kind=SmartResultSummaryKind.HISTORICAL,
            text=(
                "This is a historical FX reference observation, not a measure of historical "
                "purchasing power."
            ),
        )

    if same_currency:
        return SmartResultSummary(
            kind=SmartResultSummaryKind.IDENTITY,
            text=(
                f"No exchange-rate lookup is needed because both sides use "
                f"{conversion.quote.base_currency}; the amount remains exact 1:1."
            ),
        )

    if conversion.stale:
        return SmartResultSummary(
            kind=SmartResultSummaryKind.CACHED,
            text=(
                "Fresh provider data was unavailable, so this result uses a labelled cached "
                "reference observation."
            ),
        )

    context = (
        money_context
        if money_context is not None and money_context.conversion == conversion
        else None
    )
    if context is not None and context.destination_state is MoneyContextState.AVAILABLE:
        for price in context.local_value:
            if price.equivalent.status == "zero":
                continue
            return SmartResultSummary(
                kind=SmartResultSummaryKind.LOCAL_VALUE,
                text=(
                    f"Using the reviewed {price.scope_label} price anchor for {price.label}, "
                    f"this amount corresponds to {_purchase_phrase(price.equivalent)}."
                ),
                evidence_label=(
                    f"Observed {price.observed_at.isoformat()} · {price.source_name}"
                ),
                evidence_url=price.source_url,
            )

        if context.payment_guidance is not None and context.destination_context is not None:
            payment = context.payment_guidance
            return SmartResultSummary(
                kind=SmartResultSummaryKind.PAYMENT,
                text=(
                    "This is a reference conversion, not a bank or card quote; reviewed payment "
                    f"guidance for {context.destination_context.country_name} is available below."
                ),
                evidence_label=(
                    f"Verified {payment.verified_at.date().isoformat()} · {payment.source_name}"
                ),
                evidence_url=payment.source_url,
            )

    return SmartResultSummary(
        kind=SmartResultSummaryKind.REFERENCE,
        text=(
            "Treat this as a reference conversion rather than an executable bank or card quote; "
            "payment providers may use different rates or add fees."
        ),
    )


def _whole_count(value: Decimal) -> int:
    return int(value.to_integral_value(rounding=ROUND_FLOOR))


def _purchase_phrase(equivalent: object) -> str:
    status = getattr(equivalent, "status")
    minimum_count = getattr(equivalent, "minimum_count")
    maximum_count = getattr(equivalent, "maximum_count")

    if status == "below_one":
        return "less than one typical purchase"
    if status == "up_to":
        return f"up to {_whole_count(maximum_count)} typical purchases"
    if status == "single":
        return f"about {_whole_count(maximum_count)} typical purchases"
    if status == "range":
        return (
            f"about {_whole_count(minimum_count)}–{_whole_count(maximum_count)} "
            "typical purchases"
        )
    raise ValueError("Unsupported purchase-equivalent status for smart result summary.")
