from __future__ import annotations

from decimal import Decimal
from urllib.parse import urlencode

from django.urls import reverse
from django.utils.formats import date_format

from apps.exchange.same_amount import SameAmountAcrossDestinations, SameAmountDestinationSnapshot


def _money_text(value: Decimal, *, minor_units: int) -> str:
    return f"{value:.{minor_units}f}"


def _provider_label(item: SameAmountDestinationSnapshot) -> str:
    quote = item.context.conversion.quote
    if quote.base_currency == quote.quote_currency:
        return "Exact same-currency rate"
    providers = ", ".join(key.upper() for key in quote.provider_keys)
    return f"Frankfurter · {providers}" if providers else "Frankfurter"


def _converter_url(
    item: SameAmountDestinationSnapshot,
    *,
    source_currency_code: str,
    source_amount: Decimal,
) -> str:
    params = {
        "convert": "1",
        "amount": format(source_amount, "f"),
        "source_currency": source_currency_code,
        "destination_country": item.country_code,
        "destination_currency": item.currency_code,
        "rate_mode": "latest",
    }
    if item.city_slug:
        params["destination_city_slug"] = item.city_slug
    return f"{reverse('converter')}?{urlencode(params)}"


def _budget_url(item: SameAmountDestinationSnapshot) -> str:
    return f"{reverse('destination_mode')}?{urlencode({'destination': item.token})}"


def _price_component(
    price,
    *,
    destination_city_slug: str,
) -> dict[str, object]:
    high = (
        _money_text(price.amount_high, minor_units=price.currency_minor_units)
        if price.amount_high is not None and price.amount_high != price.amount_low
        else ""
    )
    low = _money_text(price.amount_low, minor_units=price.currency_minor_units)
    amount = f"{low}–{high}" if high else low
    return {
        "label": price.label,
        "amount": amount,
        "currency_code": price.currency_code,
        "scope": price.scope_label,
        "is_city_scope": bool(price.city_slug),
        "scope_badge": (
            "City evidence"
            if price.city_slug
            else ("National fallback" if destination_city_slug else "National evidence")
        ),
        "scope_is_fallback": bool(destination_city_slug and not price.city_slug),
        "observed": date_format(price.observed_at, "j M Y"),
        "source_class": price.source_class.replace("_", " ").capitalize(),
        "confidence": price.confidence.capitalize(),
        "source_name": price.source_name,
        "source_url": price.source_url,
    }


def _destination_component(
    item: SameAmountDestinationSnapshot,
    *,
    source_currency_code: str,
    source_amount: Decimal,
) -> dict[str, object]:
    conversion = item.context.conversion
    quote = conversion.quote
    payment = item.context.payment_guidance
    prices = tuple(
        _price_component(
            price,
            destination_city_slug=item.city_slug,
        )
        for price in item.context.local_value[:3]
    )

    city_profile_url = ""
    if item.city_slug:
        city_profile_url = reverse(
            "city_money_profile",
            kwargs={
                "country_code": item.country_code,
                "city_slug": item.city_slug,
            },
        )

    return {
        "token": item.token,
        "scope_label": item.scope_label,
        "country_code": item.country_code,
        "city_slug": item.city_slug,
        "currency_code": item.currency_code,
        "output_amount": _money_text(conversion.output_amount, minor_units=item.minor_units),
        "rate": format(quote.rate, "f"),
        "effective_date": date_format(quote.effective_date, "j M Y"),
        "fetched_at": quote.fetched_at.strftime("%d %b %Y · %H:%M UTC"),
        "provider": _provider_label(item),
        "stale": conversion.stale,
        "context_state": item.context.destination_state.value,
        "price_count": len(item.context.local_value),
        "prices": prices,
        "payment_summary": payment.summary if payment is not None else "",
        "payment_source_name": payment.source_name if payment is not None else "",
        "payment_source_url": payment.source_url if payment is not None else "",
        "payment_verified_at": (
            date_format(payment.verified_at, "j M Y") if payment is not None else ""
        ),
        "context_as_of": date_format(item.context.as_of, "j M Y"),
        "converter_url": _converter_url(
            item,
            source_currency_code=source_currency_code,
            source_amount=source_amount,
        ),
        "budget_url": _budget_url(item),
        "city_profile_url": city_profile_url,
    }


def build_same_amount_component(
    result: SameAmountAcrossDestinations,
    *,
    source_minor_units: int,
    failed_destinations: tuple[dict[str, str], ...] = (),
    destination_order: tuple[str, ...] = (),
) -> dict[str, object]:
    """Build premium descriptive cards without ranking or reordering destinations."""

    destinations = tuple(
        _destination_component(
            item,
            source_currency_code=result.source_currency_code,
            source_amount=result.source_amount,
        )
        for item in result.destinations
    )

    success_by_token = {str(item["token"]): {**item, "available": True} for item in destinations}
    failure_by_token = {
        str(item["token"]): {**item, "available": False} for item in failed_destinations
    }
    item_by_token = {**success_by_token, **failure_by_token}

    if destination_order:
        if set(destination_order) != set(item_by_token) or len(destination_order) != len(
            item_by_token
        ):
            raise ValueError(
                "Same-amount presentation order must match every rendered destination."
            )
        items = tuple(item_by_token[token] for token in destination_order)
    else:
        items = tuple(success_by_token.values()) + tuple(failure_by_token.values())

    return {
        "source_amount": _money_text(result.source_amount, minor_units=source_minor_units),
        "source_currency_code": result.source_currency_code,
        "destinations": destinations,
        "failed_destinations": failed_destinations,
        "items": items,
        "partial": bool(failed_destinations),
    }
