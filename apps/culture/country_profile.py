"""Country-level reviewed money profile: provider-free, not a country price index."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from urllib.parse import urlencode

from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format

from apps.countries.models import CountryCurrency
from apps.countries.theme_profiles import country_theme_key
from apps.culture.calendar import CalendarContext
from apps.culture.economic import EconomicContext
from apps.culture.presentation import economic_metric_component, holiday_item_component
from apps.culture.services import PaymentContext, TypicalPriceContext, build_destination_context


@dataclass(frozen=True, slots=True)
class CountryMoneyProfile:
    country_code: str
    country_name: str
    currency_code: str
    currency_name: str
    as_of: date
    prices: tuple[TypicalPriceContext, ...]
    payment: PaymentContext | None
    economic: EconomicContext | None
    calendar: CalendarContext | None


def build_country_money_profile(
    *, country_code: str, as_of: date | None = None
) -> CountryMoneyProfile | None:
    """Use canonical current country/currency and reviewed, bounded context.

    Some evidence is city-specific; the UI must never display those prices
    as a national average or infer affordability from a synthetic amount.
    """
    selected_date = as_of or timezone.localdate()
    link = (
        CountryCurrency.objects.current(selected_date)
        .primary()
        .filter(country__iso2=country_code.strip().upper(), country__is_active=True)
        .select_related("country", "currency")
        .first()
    )
    if link is None:
        return None
    context = build_destination_context(
        country_code=link.country.iso2,
        converted_amount=Decimal("0"),
        quote_currency=link.currency.code,
        as_of=selected_date,
        price_limit=6,
    )
    if context is None or not context.has_content:
        return None
    return CountryMoneyProfile(
        country_code=link.country.iso2,
        country_name=link.country.name,
        currency_code=link.currency.code,
        currency_name=link.currency.name,
        as_of=selected_date,
        prices=context.prices,
        payment=context.payment,
        economic=context.economic,
        calendar=context.calendar,
    )


def build_country_money_profile_component(profile: CountryMoneyProfile) -> dict[str, object]:
    """Read-only presentation composed exclusively from source-labelled data."""
    prices = []
    for price in profile.prices:
        low = f"{price.amount_low:.{price.currency_minor_units}f}"
        high = (
            f"{price.amount_high:.{price.currency_minor_units}f}"
            if price.amount_high is not None and price.amount_high != price.amount_low
            else ""
        )
        is_national = not (price.city or price.city_slug)
        prices.append(
            {
                "label": price.label,
                "price_text": (
                    f"{low}–{high} {price.currency_code}"
                    if high
                    else f"{low} {price.currency_code}"
                ),
                "scope": price.scope_label,
                "is_national": is_national,
                "observed": date_format(price.observed_at, "j M Y"),
                "source_class": price.source_class.replace("_", " ").capitalize(),
                "confidence": price.confidence.capitalize(),
                "source_name": price.source_name,
                "source_url": price.source_url,
            }
        )

    payment = None
    if profile.payment is not None:
        rows = (
            ("Cards", profile.payment.payment_customs),
            ("Cash", profile.payment.cash_usage),
            ("ATMs", profile.payment.atm_notes),
            ("Tipping", profile.payment.tipping),
            ("Dynamic currency conversion", profile.payment.dcc_warning),
        )
        payment = {
            "summary": profile.payment.summary,
            "rows": tuple({"label": label, "text": value} for label, value in rows if value.strip()),
            "source_name": profile.payment.source_name,
            "source_url": profile.payment.source_url,
            "verified": date_format(profile.payment.verified_at, "j M Y"),
        }

    economic = None
    if profile.economic is not None:
        economic = {
            "inflation": (
                economic_metric_component(profile.economic.inflation)
                if profile.economic.inflation is not None
                else None
            ),
            "price_level": (
                economic_metric_component(profile.economic.price_level)
                if profile.economic.price_level is not None
                else None
            ),
        }
    calendar = None
    if profile.calendar is not None:
        calendar = {
            "today": tuple(
                holiday_item_component(item, as_of=profile.calendar.as_of)
                for item in profile.calendar.today
            ),
            "upcoming": tuple(
                holiday_item_component(item, as_of=profile.calendar.as_of)
                for item in profile.calendar.upcoming
            ),
            "window_days": profile.calendar.window_days,
        }

    destination = profile.country_code
    converter_params = {
        "load": "1",
        "destination_country": destination,
        "destination_currency": profile.currency_code,
    }
    return {
        "country_code": destination,
        "country_name": profile.country_name,
        "currency_code": profile.currency_code,
        "currency_name": profile.currency_name,
        "theme": country_theme_key(destination),
        "as_of": date_format(profile.as_of, "j M Y"),
        "prices": tuple(prices),
        "national_price_count": sum(int(row["is_national"]) for row in prices),
        "city_example_count": sum(int(not row["is_national"]) for row in prices),
        "payment": payment,
        "economic": economic,
        "calendar": calendar,
        "converter_url": f"{reverse('converter')}?{urlencode(converter_params)}",
        "budget_url": f"{reverse('destination_mode')}?{urlencode({'destination': destination})}",
        "compare_url": (
            f"{reverse('destination_comparison')}?"
            f"{urlencode({'left_destination': destination})}"
        ),
    }
