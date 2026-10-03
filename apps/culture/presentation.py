from __future__ import annotations

from decimal import ROUND_FLOOR, Decimal

from django.utils.formats import date_format

from apps.common.presentation.media_view_models import ImageViewModel
from apps.culture.services import DestinationContext, PurchaseEquivalent


def _money_text(value: Decimal, *, minor_units: int) -> str:
    return f"{value:.{minor_units}f}"


def _whole_count(value: Decimal) -> int:
    return int(value.to_integral_value(rounding=ROUND_FLOOR))


def _equivalent_text(value: PurchaseEquivalent) -> str:
    if value.status == "zero":
        return "0 for this converted amount"
    if value.status == "below_one":
        return "Less than 1"
    if value.status == "up_to":
        return f"Up to {_whole_count(value.maximum_count)}"
    if value.status == "single":
        return f"About {_whole_count(value.maximum_count)}"
    return f"About {_whole_count(value.minimum_count)}–{_whole_count(value.maximum_count)}"


def build_destination_context_component(
    context: DestinationContext,
    *,
    historical: bool,
    show_explore_nav: bool = True,
    hero_image: ImageViewModel | None = None,
    everyday_value_image: ImageViewModel | None = None,
    payment_culture_image: ImageViewModel | None = None,
    local_detail_image: ImageViewModel | None = None,
) -> dict[str, object]:
    prices = [
        {
            "label": price.label,
            "category": price.category,
            "price_text": (
                f"{_money_text(price.amount_low, minor_units=price.currency_minor_units)}"
                + (
                    f"–{_money_text(price.amount_high, minor_units=price.currency_minor_units)}"
                    if price.amount_high is not None and price.amount_high != price.amount_low
                    else ""
                )
                + f" {price.currency_code}"
            ),
            "equivalent_text": _equivalent_text(price.equivalent),
            "scope": price.scope_label,
            "observed": date_format(price.observed_at, "M Y"),
            "source_class": price.source_class.replace("_", " ").capitalize(),
            "confidence": price.confidence.capitalize(),
            "source_name": price.source_name,
            "source_url": price.source_url,
        }
        for price in context.prices
    ]

    payment = None
    if context.payment is not None:
        rows = [
            {"label": "Cards", "text": context.payment.payment_customs},
            {"label": "Cash", "text": context.payment.cash_usage},
            {"label": "ATMs", "text": context.payment.atm_notes},
            {"label": "Tipping", "text": context.payment.tipping},
            {"label": "Dynamic currency conversion", "text": context.payment.dcc_warning},
        ]
        payment = {
            "summary": context.payment.summary,
            "rows": [row for row in rows if row["text"].strip()],
            "source_name": context.payment.source_name,
            "source_url": context.payment.source_url,
            "verified": date_format(context.payment.verified_at, "j M Y"),
        }

    return {
        "country_code": context.country_code,
        "country_name": context.country_name,
        "has_content": context.has_content,
        "as_of": date_format(context.as_of, "j M Y"),
        "price_count": len(prices),
        "payment_verified": payment["verified"] if payment is not None else "",
        "hero_image": hero_image,
        "everyday_value_image": everyday_value_image if prices else None,
        "payment_culture_image": payment_culture_image if payment is not None else None,
        "local_detail_image": local_detail_image if prices or payment is not None else None,
        "prices": prices,
        "payment": payment,
        "historical_notice": (
            "Current destination context — not historical purchasing power. "
            "These local-price and payment notes use current reviewed data and are not "
            "backdated to the historical exchange-rate date."
            if historical
            else None
        ),
        "show_explore_nav": show_explore_nav,
    }
