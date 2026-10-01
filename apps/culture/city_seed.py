from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.utils import timezone

from apps.countries.models import City, Country, Currency
from apps.culture.models import (
    TypicalPrice,
    TypicalPriceCategory,
    TypicalPriceConfidence,
    TypicalPriceSourceClass,
)
from apps.culture.price_quality import TypicalPriceUnit

_WAVE_ONE_OBSERVED_AT = date(2026, 10, 1)
_CITY_CONTEXT_SOURCE_CLASS = TypicalPriceSourceClass.APPROXIMATE_CONTEXTUAL
_CITY_CONTEXT_CONFIDENCE = TypicalPriceConfidence.MEDIUM


@dataclass(frozen=True, slots=True)
class _PriceSpec:
    category: str
    unit: str
    label: str
    amount_low: Decimal
    amount_high: Decimal | None
    source_name: str
    source_url: str
    source_class: str
    confidence: str
    notes: str
    display_order: int


@dataclass(frozen=True, slots=True)
class _CitySpec:
    country_code: str
    currency_code: str
    slug: str
    name: str
    contextual_source_url: str
    prices: tuple[_PriceSpec, ...]


def _money(value: str) -> Decimal:
    return Decimal(value)


def _context_price(
    *,
    category: str,
    unit: str,
    label: str,
    low: str,
    high: str,
    city_name: str,
    source_url: str,
    notes: str,
    display_order: int,
) -> _PriceSpec:
    return _PriceSpec(
        category=category,
        unit=unit,
        label=label,
        amount_low=_money(low),
        amount_high=_money(high),
        source_name=f"Numbeo · {city_name}",
        source_url=source_url,
        source_class=_CITY_CONTEXT_SOURCE_CLASS,
        confidence=_CITY_CONTEXT_CONFIDENCE,
        notes=notes,
        display_order=display_order,
    )


def _transit_price(
    *,
    label: str,
    low: str,
    high: str | None,
    source_name: str,
    source_url: str,
    notes: str,
) -> _PriceSpec:
    return _PriceSpec(
        category=TypicalPriceCategory.TRANSIT,
        unit=TypicalPriceUnit.RIDE,
        label=label,
        amount_low=_money(low),
        amount_high=_money(high) if high is not None else None,
        source_name=source_name,
        source_url=source_url,
        source_class=TypicalPriceSourceClass.AUTHORITATIVE,
        confidence=TypicalPriceConfidence.HIGH,
        notes=notes,
        display_order=30,
    )


def _city_prices(
    *,
    city_name: str,
    source_url: str,
    coffee: tuple[str, str],
    meal: tuple[str, str],
    groceries: tuple[str, str],
    transit: _PriceSpec,
) -> tuple[_PriceSpec, ...]:
    reviewed_note = (
        "City-level crowdsourced price range reviewed on 2026-10-01; "
        "contextual rather than authoritative."
    )
    return (
        _context_price(
            category=TypicalPriceCategory.COFFEE,
            unit=TypicalPriceUnit.SERVING,
            label="Cappuccino",
            low=coffee[0],
            high=coffee[1],
            city_name=city_name,
            source_url=source_url,
            notes=reviewed_note,
            display_order=10,
        ),
        _context_price(
            category=TypicalPriceCategory.CASUAL_MEAL,
            unit=TypicalPriceUnit.MEAL,
            label="Inexpensive restaurant meal",
            low=meal[0],
            high=meal[1],
            city_name=city_name,
            source_url=source_url,
            notes=reviewed_note,
            display_order=20,
        ),
        transit,
        _context_price(
            category=TypicalPriceCategory.GROCERIES,
            unit=TypicalPriceUnit.BASKET,
            label="Basic grocery basket",
            low=groceries[0],
            high=groceries[1],
            city_name=city_name,
            source_url=source_url,
            notes=(
                "Derived from the source's city-level ranges for a fixed basket: "
                "1 L milk + 500 g fresh white bread + 1 kg white rice + 12 eggs. "
                "Reviewed on 2026-10-01; contextual rather than authoritative."
            ),
            display_order=40,
        ),
    )


_HELSINKI_SOURCE = "https://de.numbeo.com/lebenshaltungskosten/stadt/Helsinki"
_TURKU_SOURCE = "https://de.numbeo.com/lebenshaltungskosten/stadt/Turku"
_STOCKHOLM_SOURCE = "https://de.numbeo.com/lebenshaltungskosten/stadt/Stockholm"
_COPENHAGEN_SOURCE = "https://de.numbeo.com/lebenshaltungskosten/stadt/Kopenhagen"
_OSLO_SOURCE = "https://de.numbeo.com/lebenshaltungskosten/stadt/Oslo"
_BERLIN_SOURCE = "https://de.numbeo.com/lebenshaltungskosten/stadt/Berlin"

_WAVE_ONE_CITIES: tuple[_CitySpec, ...] = (
    _CitySpec(
        country_code="FI",
        currency_code="EUR",
        slug="helsinki",
        name="Helsinki",
        contextual_source_url=_HELSINKI_SOURCE,
        prices=_city_prices(
            city_name="Helsinki",
            source_url=_HELSINKI_SOURCE,
            coffee=("3.00", "5.70"),
            meal=("13.70", "25.00"),
            groceries=("5.29", "14.30"),
            transit=_transit_price(
                label="HSL adult AB single ticket",
                low="3.30",
                high="3.50",
                source_name="HSL",
                source_url=(
                    "https://www.hsl.fi/en/tickets-and-fares/single-tickets/"
                    "single-ticket-prices-in-the-hsl-area"
                ),
                notes=(
                    "Adult AB single-ticket price observed 2026-10-01: €3.30 in the HSL app, "
                    "card or ticket machine and €3.50 with contactless payment."
                ),
            ),
        ),
    ),
    _CitySpec(
        country_code="FI",
        currency_code="EUR",
        slug="turku",
        name="Turku",
        contextual_source_url=_TURKU_SOURCE,
        prices=_city_prices(
            city_name="Turku",
            source_url=_TURKU_SOURCE,
            coffee=("3.00", "5.00"),
            meal=("13.00", "25.00"),
            groceries=("7.37", "10.88"),
            transit=_transit_price(
                label="Föli adult single ticket",
                low="3.15",
                high=None,
                source_name="Föli",
                source_url="https://www.foli.fi/en/tickets",
                notes=(
                    "Standard adult single-ticket price observed 2026-10-01. "
                    "Cash purchase has a separate higher fare and is intentionally not blended "
                    "into this anchor."
                ),
            ),
        ),
    ),
    _CitySpec(
        country_code="SE",
        currency_code="SEK",
        slug="stockholm",
        name="Stockholm",
        contextual_source_url=_STOCKHOLM_SOURCE,
        prices=_city_prices(
            city_name="Stockholm",
            source_url=_STOCKHOLM_SOURCE,
            coffee=("39.00", "75.00"),
            meal=("129.00", "283.30"),
            groceries=("93.00", "205.00"),
            transit=_transit_price(
                label="SL adult single journey ticket",
                low="43.00",
                high=None,
                source_name="SL",
                source_url=(
                    "https://sl.se/en/fares-and-tickets/visitor-tickets/"
                    "single-journey-tickets"
                ),
                notes="Adult 75-minute single-journey ticket price observed 2026-10-01.",
            ),
        ),
    ),
    _CitySpec(
        country_code="DK",
        currency_code="DKK",
        slug="copenhagen",
        name="Copenhagen",
        contextual_source_url=_COPENHAGEN_SOURCE,
        prices=_city_prices(
            city_name="Copenhagen",
            source_url=_COPENHAGEN_SOURCE,
            coffee=("30.00", "60.00"),
            meal=("90.00", "300.00"),
            groceries=("55.00", "134.34"),
            transit=_transit_price(
                label="DOT adult 2-zone single ticket",
                low="24.00",
                high=None,
                source_name="DOT",
                source_url=(
                    "https://dinoffentligetransport.dk/media/pmngcey0/"
                    "dot-takstblad-2026-a.pdf"
                ),
                notes="Adult 2-zone single-ticket fare from the 2026 DOT tariff sheet.",
            ),
        ),
    ),
    _CitySpec(
        country_code="NO",
        currency_code="NOK",
        slug="oslo",
        name="Oslo",
        contextual_source_url=_OSLO_SOURCE,
        prices=_city_prices(
            city_name="Oslo",
            source_url=_OSLO_SOURCE,
            coffee=("38.17", "80.00"),
            meal=("148.92", "300.00"),
            groceries=("96.40", "218.00"),
            transit=_transit_price(
                label="Ruter adult Zone 1 single ticket",
                low="46.00",
                high=None,
                source_name="Ruter",
                source_url=(
                    "https://ruter.no/en/about-our-tickets/ticket-prices/"
                    "how-prices-are-set"
                ),
                notes=(
                    "Adult Zone 1 single-ticket fare effective from 2026-01-25 and "
                    "reviewed 2026-10-01."
                ),
            ),
        ),
    ),
    _CitySpec(
        country_code="DE",
        currency_code="EUR",
        slug="berlin",
        name="Berlin",
        contextual_source_url=_BERLIN_SOURCE,
        prices=_city_prices(
            city_name="Berlin",
            source_url=_BERLIN_SOURCE,
            coffee=("2.50", "5.00"),
            meal=("10.00", "30.00"),
            groceries=("5.94", "15.12"),
            transit=_transit_price(
                label="BVG adult AB single ticket",
                low="4.00",
                high=None,
                source_name="BVG",
                source_url=(
                    "https://www.bvg.de/en/subscriptions-and-tickets/all-tickets/"
                    "single-tickets/single-ticket"
                ),
                notes="Adult Berlin AB single-ticket fare observed 2026-10-01.",
            ),
        ),
    ),
)


def seed_curated_city_prices_wave1() -> tuple[int, int]:
    """Seed reviewed city-scoped price anchors without bypassing TypicalPrice contracts."""

    verified_at = timezone.now()
    created = existing = 0

    for city_spec in _WAVE_ONE_CITIES:
        country = Country.objects.get(iso2=city_spec.country_code)
        currency = Currency.objects.get(code=city_spec.currency_code)
        city, _city_created = City.objects.update_or_create(
            country=country,
            slug=city_spec.slug,
            defaults={"name": city_spec.name, "is_active": True},
        )

        for price_spec in city_spec.prices:
            row = TypicalPrice.objects.filter(
                country=country,
                city_ref=city,
                category=price_spec.category,
                unit=price_spec.unit,
                label=price_spec.label,
                observed_at=_WAVE_ONE_OBSERVED_AT,
            ).first()
            row_created = row is None
            if row is None:
                row = TypicalPrice(
                    country=country,
                    city_ref=city,
                    category=price_spec.category,
                    unit=price_spec.unit,
                    label=price_spec.label,
                    observed_at=_WAVE_ONE_OBSERVED_AT,
                )

            row.amount_low = price_spec.amount_low
            row.amount_high = price_spec.amount_high
            row.currency = currency
            row.source_name = price_spec.source_name
            row.source_url = price_spec.source_url
            row.verified_at = verified_at
            row.source_class = price_spec.source_class
            row.confidence = price_spec.confidence
            row.notes = price_spec.notes
            row.display_order = price_spec.display_order
            row.is_published = True
            row.full_clean()
            row.save()

            if row_created:
                created += 1
            else:
                existing += 1

    return created, existing
