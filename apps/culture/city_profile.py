from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from urllib.parse import urlencode

from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format

from apps.countries.models import City, CountryCurrency
from apps.culture.services import DestinationContext, PaymentContext, TypicalPriceContext, build_destination_context


@dataclass(frozen=True, slots=True)
class CityMoneyProfile:
    """Provider-free city money profile composed from canonical reviewed context."""

    country_code: str
    country_name: str
    city_slug: str
    city_name: str
    currency_code: str
    currency_name: str
    currency_symbol: str
    currency_minor_units: int
    as_of: date
    prices: tuple[TypicalPriceContext, ...]
    payment: PaymentContext | None
    direct_price_count: int
    national_fallback_count: int
    earliest_price_observed_at: date
    latest_price_observed_at: date

    @property
    def scope_label(self) -> str:
        return f"{self.city_name}, {self.country_name}"

    @property
    def has_national_fallback(self) -> bool:
        return self.national_fallback_count > 0


def build_city_money_profile(
    *,
    country_code: str,
    city_slug: str,
    as_of: date | None = None,
) -> CityMoneyProfile | None:
    """Build one reviewed city profile without requesting FX or creating parallel state."""

    selected_date = as_of or timezone.localdate()
    city = (
        City.objects.filter(
            country__iso2=country_code.upper(),
            country__is_active=True,
            slug=city_slug.strip().lower(),
            is_active=True,
        )
        .select_related("country")
        .first()
    )
    if city is None:
        return None

    link = (
        CountryCurrency.objects.current(selected_date)
        .primary()
        .filter(country=city.country)
        .select_related("currency")
        .first()
    )
    if link is None:
        return None

    context = build_destination_context(
        country_code=city.country.iso2,
        city_slug=city.slug,
        converted_amount=Decimal("1"),
        quote_currency=link.currency.code,
        as_of=selected_date,
        price_limit=6,
    )
    if context is None:
        return None

    direct_prices = tuple(price for price in context.prices if price.city_slug == city.slug)
    if not direct_prices:
        # National context alone must never manufacture a city profile.
        return None

    fallback_prices = tuple(price for price in context.prices if not price.city_slug)
    observed_dates = tuple(price.observed_at for price in context.prices)

    return CityMoneyProfile(
        country_code=city.country.iso2,
        country_name=city.country.name,
        city_slug=city.slug,
        city_name=city.name,
        currency_code=link.currency.code,
        currency_name=link.currency.name,
        currency_symbol=link.currency.symbol,
        currency_minor_units=link.currency.minor_units,
        as_of=selected_date,
        prices=context.prices,
        payment=context.payment,
        direct_price_count=len(direct_prices),
        national_fallback_count=len(fallback_prices),
        earliest_price_observed_at=min(observed_dates),
        latest_price_observed_at=max(observed_dates),
    )


def _money_text(value: Decimal, *, minor_units: int) -> str:
    return f"{value:.{minor_units}f}"


def _profile_price_component(price: TypicalPriceContext) -> dict[str, object]:
    high = (
        _money_text(price.amount_high, minor_units=price.currency_minor_units)
        if price.amount_high is not None and price.amount_high != price.amount_low
        else ""
    )
    low = _money_text(price.amount_low, minor_units=price.currency_minor_units)
    price_text = f"{low}–{high} {price.currency_code}" if high else f"{low} {price.currency_code}"
    return {
        "label": price.label,
        "category": price.category,
        "price_text": price_text,
        "scope": price.scope_label,
        "is_city_scope": bool(price.city_slug),
        "observed": date_format(price.observed_at, "j M Y"),
        "source_class": price.source_class.replace("_", " ").capitalize(),
        "confidence": price.confidence.capitalize(),
        "source_name": price.source_name,
        "source_url": price.source_url,
    }


def build_city_money_profile_component(profile: CityMoneyProfile) -> dict[str, object]:
    """Create display data and canonical action handoffs for one city profile."""

    destination_token = f"{profile.country_code}:{profile.city_slug}"
    converter_params = {
        "load": "1",
        "destination_country": profile.country_code,
        "destination_currency": profile.currency_code,
        "destination_city_slug": profile.city_slug,
    }
    plan_params = {"destination": destination_token}
    compare_params = {"left_destination": destination_token}

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
            "rows": tuple({"label": label, "text": text} for label, text in rows if text.strip()),
            "source_name": profile.payment.source_name,
            "source_url": profile.payment.source_url,
            "verified": date_format(profile.payment.verified_at, "j M Y"),
        }

    return {
        "scope_label": profile.scope_label,
        "country_code": profile.country_code,
        "country_name": profile.country_name,
        "city_slug": profile.city_slug,
        "city_name": profile.city_name,
        "currency_code": profile.currency_code,
        "currency_name": profile.currency_name,
        "currency_symbol": profile.currency_symbol,
        "prices": tuple(_profile_price_component(price) for price in profile.prices),
        "payment": payment,
        "direct_price_count": profile.direct_price_count,
        "national_fallback_count": profile.national_fallback_count,
        "has_national_fallback": profile.has_national_fallback,
        "earliest_price_observed": date_format(profile.earliest_price_observed_at, "j M Y"),
        "latest_price_observed": date_format(profile.latest_price_observed_at, "j M Y"),
        "as_of": date_format(profile.as_of, "j M Y"),
        "converter_url": f"{reverse('converter')}?{urlencode(converter_params)}",
        "budget_url": f"{reverse('destination_mode')}?{urlencode(plan_params)}",
        "compare_url": f"{reverse('destination_comparison')}?{urlencode(compare_params)}",
        "saved_url": reverse("saved_state"),
    }
