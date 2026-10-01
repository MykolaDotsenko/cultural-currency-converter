from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from apps.culture.services import (
    DestinationContext,
    PaymentContext,
    PurchaseEquivalent,
    TypicalPriceContext,
)
from apps.exchange.domain import DEFAULT_SOURCE_POLICY, ConversionResult, RateQuote
from apps.exchange.money_context import MoneyContext, MoneyContextState
from apps.exchange.result_summary import (
    SmartResultSummaryKind,
    build_smart_result_summary,
)


def _conversion(
    *,
    base: str = "EUR",
    quote: str = "JPY",
    output: Decimal = Decimal("17450"),
    historical: bool = False,
    stale: bool = False,
) -> ConversionResult:
    return ConversionResult(
        input_amount=Decimal("100"),
        output_amount=output,
        quote=RateQuote(
            base_currency=base,
            quote_currency=quote,
            rate=Decimal("1") if base == quote else Decimal("174.50"),
            requested_date=date(1998, 6, 14) if historical else None,
            effective_date=date(1998, 6, 12) if historical else date(2026, 9, 18),
            fetched_at=datetime(2026, 10, 1, 8, tzinfo=UTC),
            provider_policy=DEFAULT_SOURCE_POLICY,
            provider_keys=() if base == quote else ("ecb",),
            historical=historical,
        ),
        stale=stale,
    )


def _payment() -> PaymentContext:
    return PaymentContext(
        summary="Reviewed payment context.",
        payment_customs="Cards are commonly accepted.",
        cash_usage="Cash remains useful.",
        tipping="Tipping is generally not practiced.",
        atm_notes="Check disclosed ATM fees.",
        dcc_warning="Prefer the local currency when DCC is offered.",
        source_name="Official payment source",
        source_url="https://example.org/payment",
        verified_at=datetime(2026, 9, 20, 8, tzinfo=UTC),
    )


def _price(
    *,
    status: str = "range",
    minimum_count: Decimal = Decimal("29.08"),
    maximum_count: Decimal = Decimal("34.90"),
) -> TypicalPriceContext:
    return TypicalPriceContext(
        label="Cup of coffee",
        category="coffee",
        city="Tokyo",
        country_name="Japan",
        currency_code="JPY",
        currency_minor_units=0,
        amount_low=Decimal("500"),
        amount_high=Decimal("600"),
        observed_at=date(2026, 8, 1),
        source_class="official",
        confidence="high",
        source_name="Reviewed price source",
        source_url="https://example.org/coffee",
        equivalent=PurchaseEquivalent(
            minimum_count=minimum_count,
            maximum_count=maximum_count,
            status=status,
        ),
        city_slug="tokyo",
    )


def _context(
    conversion: ConversionResult,
    *,
    prices: tuple[TypicalPriceContext, ...] = (),
    payment: PaymentContext | None = None,
) -> MoneyContext:
    destination = DestinationContext(
        country_code="JP",
        country_name="Japan",
        as_of=date(2026, 10, 1),
        payment=payment,
        prices=prices,
        city_slug="tokyo",
        city_name="Tokyo",
    )
    return MoneyContext(
        conversion=conversion,
        destination_country_code="JP",
        destination_city_slug="tokyo",
        as_of=date(2026, 10, 1),
        destination_context=destination,
        destination_state=MoneyContextState.AVAILABLE,
    )


def test_current_reviewed_price_anchor_produces_local_value_summary():
    conversion = _conversion()
    summary = build_smart_result_summary(
        conversion,
        money_context=_context(conversion, prices=(_price(),), payment=_payment()),
    )

    assert summary.kind is SmartResultSummaryKind.LOCAL_VALUE
    assert summary.text == (
        "Using the reviewed Tokyo price anchor for Cup of coffee, this amount corresponds to "
        "about 29–34 typical purchases."
    )
    assert summary.evidence_label == "Observed 2026-08-01 · Reviewed price source"
    assert summary.evidence_url == "https://example.org/coffee"


def test_stale_reference_outranks_optional_local_value_context():
    conversion = _conversion(stale=True)
    summary = build_smart_result_summary(
        conversion,
        money_context=_context(conversion, prices=(_price(),), payment=_payment()),
    )

    assert summary.kind is SmartResultSummaryKind.CACHED
    assert "labelled cached reference observation" in summary.text
    assert summary.evidence_url == ""


def test_historical_reference_never_uses_current_local_value_as_purchasing_power():
    conversion = _conversion(historical=True)
    summary = build_smart_result_summary(conversion)

    assert summary.kind is SmartResultSummaryKind.HISTORICAL
    assert summary.text == (
        "This is a historical FX reference observation, not a measure of historical "
        "purchasing power."
    )


def test_same_currency_summary_is_exact_and_provider_free():
    conversion = _conversion(base="EUR", quote="EUR", output=Decimal("100"))
    summary = build_smart_result_summary(conversion)

    assert summary.kind is SmartResultSummaryKind.IDENTITY
    assert summary.text == (
        "No exchange-rate lookup is needed because both sides use EUR; the amount remains exact 1:1."
    )


def test_payment_guidance_is_used_when_no_price_anchor_is_available():
    conversion = _conversion()
    summary = build_smart_result_summary(
        conversion,
        money_context=_context(conversion, payment=_payment()),
    )

    assert summary.kind is SmartResultSummaryKind.PAYMENT
    assert "reviewed payment guidance for Japan is available below" in summary.text
    assert summary.evidence_label == (
        "Verified 2026-09-20 · Official payment source"
    )
    assert summary.evidence_url == "https://example.org/payment"


def test_zero_purchase_equivalent_falls_back_instead_of_claiming_buying_power():
    conversion = _conversion(output=Decimal("0"))
    zero_price = _price(
        status="zero",
        minimum_count=Decimal("0"),
        maximum_count=Decimal("0"),
    )
    summary = build_smart_result_summary(
        conversion,
        money_context=_context(conversion, prices=(zero_price,)),
    )

    assert summary.kind is SmartResultSummaryKind.REFERENCE
    assert "reference conversion" in summary.text


def test_unknown_purchase_status_is_ignored_instead_of_breaking_conversion():
    conversion = _conversion()
    unknown_price = _price(status="future_status")
    summary = build_smart_result_summary(
        conversion,
        money_context=_context(conversion, prices=(unknown_price,)),
    )

    assert summary.kind is SmartResultSummaryKind.REFERENCE
    assert "reference conversion" in summary.text


def test_mismatched_money_context_is_ignored_fail_closed():
    conversion = _conversion()
    other_conversion = _conversion(output=Decimal("34900"))
    summary = build_smart_result_summary(
        conversion,
        money_context=_context(other_conversion, prices=(_price(),)),
    )

    assert summary.kind is SmartResultSummaryKind.REFERENCE
    assert "payment providers may use different rates or add fees" in summary.text


def test_historical_identity_keeps_purchasing_power_boundary():
    conversion = _conversion(
        base="EUR",
        quote="EUR",
        output=Decimal("100"),
        historical=True,
    )
    summary = build_smart_result_summary(conversion)

    assert summary.kind is SmartResultSummaryKind.HISTORICAL
    assert "exact 1:1 historical identity conversion" in summary.text
    assert "does not describe historical purchasing power" in summary.text
