from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal
from enum import StrEnum

from apps.culture.services import PurchaseEquivalent
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


@dataclass(frozen=True, slots=True)
class SupportingMoneyInsight:
    """Optional reviewed context, never a new financial calculation."""

    kind: str
    title: str
    text: str
    evidence_label: str
    evidence_url: str
    detail_href: str
    detail_label: str


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
            purchase_phrase = _purchase_phrase(price.equivalent)
            if purchase_phrase is None:
                continue
            return SmartResultSummary(
                kind=SmartResultSummaryKind.LOCAL_VALUE,
                text=(
                    f"Using the reviewed {price.scope_label} price anchor for {price.label}, "
                    f"this amount corresponds to {purchase_phrase}."
                ),
                evidence_label=(f"Observed {price.observed_at.isoformat()} · {price.source_name}"),
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


def build_supporting_money_insights(
    conversion: ConversionResult,
    *,
    money_context: MoneyContext | None,
    primary_kind: SmartResultSummaryKind,
) -> tuple[SupportingMoneyInsight, ...]:
    """Offer up to three non-duplicative, reviewed facts alongside current FX.

    Trust-sensitive results intentionally receive no supporting current-context
    insights. These facts are never an additional provider call or user ranking.
    """
    if (
        conversion.quote.historical
        or conversion.stale
        or conversion.quote.base_currency == conversion.quote.quote_currency
        or money_context is None
        or money_context.conversion != conversion
        or money_context.destination_state is not MoneyContextState.AVAILABLE
        or money_context.destination_context is None
    ):
        return ()

    destination = money_context.destination_context
    insights: list[SupportingMoneyInsight] = []

    if primary_kind is not SmartResultSummaryKind.PAYMENT:
        payment = destination.payment
        if payment is not None and payment.dcc_warning.strip():
            insights.append(
                SupportingMoneyInsight(
                    kind="payment",
                    title="At the card terminal",
                    text=payment.dcc_warning.strip(),
                    evidence_label=(
                        f"Reviewed {payment.verified_at.date().isoformat()} · {payment.source_name}"
                    ),
                    evidence_url=payment.source_url,
                    detail_href="#payment-context",
                    detail_label="Payment guidance",
                )
            )

    calendar = destination.calendar
    if calendar is not None:
        upcoming = (*calendar.today, *calendar.upcoming)
        if upcoming:
            holiday = upcoming[0]
            insights.append(
                SupportingMoneyInsight(
                    kind="holiday",
                    title="National holiday",
                    text=(
                        f"{holiday.name} on {holiday.date.isoformat()} may affect opening "
                        "hours. Confirm hours with each bank, shop or service."
                    ),
                    evidence_label=f"National calendar · {holiday.source_name}",
                    evidence_url=holiday.source_url,
                    detail_href="#calendar-context",
                    detail_label="Holiday context",
                )
            )

    # The main summary already explains the first usable purchase anchor.
    # Show a different reviewed category rather than repeating the same fact.
    price_candidates = money_context.local_value
    if primary_kind is SmartResultSummaryKind.LOCAL_VALUE:
        price_candidates = price_candidates[1:]
    for price in price_candidates:
        purchase_phrase = _purchase_phrase(price.equivalent)
        if purchase_phrase is None:
            continue
        insights.append(
            SupportingMoneyInsight(
                kind="local_value",
                title=f"Everyday value · {price.label}",
                text=(
                    f"For the reviewed {price.scope_label} price range, this amount "
                    f"corresponds to {purchase_phrase}. Actual prices can vary."
                ),
                evidence_label=(f"Observed {price.observed_at.isoformat()} · {price.source_name}"),
                evidence_url=price.source_url,
                detail_href="#everyday-value",
                detail_label="Price context",
            )
        )
        break

    return tuple(insights[:3])


def _whole_count(value: Decimal) -> int:
    return int(value.to_integral_value(rounding=ROUND_FLOOR))


def _purchase_phrase(equivalent: PurchaseEquivalent) -> str | None:
    if equivalent.status == "zero":
        return None
    if equivalent.status == "below_one":
        return "less than one typical purchase"
    if equivalent.status == "up_to":
        return f"up to {_whole_count(equivalent.maximum_count)} typical purchases"
    if equivalent.status == "single":
        return f"about {_whole_count(equivalent.maximum_count)} typical purchases"
    if equivalent.status == "range":
        return (
            f"about {_whole_count(equivalent.minimum_count)}–"
            f"{_whole_count(equivalent.maximum_count)} "
            "typical purchases"
        )
    return None
