from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from apps.countries.models import City, Country, Currency
from apps.culture.models import (
    TypicalPrice,
    TypicalPriceCategory,
    TypicalPriceConfidence,
    TypicalPriceSourceClass,
)
from apps.culture.price_quality import TypicalPriceUnit

_WAVE_ONE_OBSERVED_AT = date(2026, 10, 1)
_WAVE_ONE_VERIFIED_AT = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
_WAVE_TWO_OBSERVED_AT = date(2026, 10, 1)
_WAVE_TWO_VERIFIED_AT = datetime(2026, 10, 1, 13, 0, tzinfo=UTC)
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
    transit: _PriceSpec | None,
) -> tuple[_PriceSpec, ...]:
    reviewed_note = (
        "City-level crowdsourced price range reviewed on 2026-10-01; "
        "contextual rather than authoritative."
    )
    prices = [
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
    ]
    if transit is not None:
        prices.append(transit)
    prices.append(
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
        )
    )
    return tuple(prices)


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
                    "https://sl.se/en/fares-and-tickets/visitor-tickets/single-journey-tickets"
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
                source_name="Public Transport Denmark (DOT)",
                source_url="https://www.publictransport.dk/en/tickets",
                notes=(
                    "Adult single tickets start at DKK 24 for 2 zones; "
                    "official fare page reviewed 2026-10-01."
                ),
            ),
        ),
    ),
    _CitySpec(
        country_code="NO",
        currency_code="NOK",
        slug="oslo",
        name="Oslo",
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
                    "https://ruter.no/en/about-our-tickets/ticket-prices/how-prices-are-set"
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


_TOKYO_SOURCE = "https://www.numbeo.com/cost-of-living/in/Tokyo"
_SINGAPORE_SOURCE = "https://www.numbeo.com/cost-of-living/in/Singapore"
_TORONTO_SOURCE = "https://www.numbeo.com/cost-of-living/in/Toronto"
_AUCKLAND_SOURCE = "https://www.numbeo.com/cost-of-living/in/Auckland"

_WAVE_TWO_CITIES: tuple[_CitySpec, ...] = (
    _CitySpec(
        country_code="JP",
        currency_code="JPY",
        slug="tokyo",
        name="Tokyo",
        prices=_city_prices(
            city_name="Tokyo",
            source_url=_TOKYO_SOURCE,
            coffee=("261.24", "900.00"),
            meal=("800.00", "2000.00"),
            groceries=("1280.00", "2248.00"),
            transit=None,
        ),
    ),
    _CitySpec(
        country_code="SG",
        currency_code="SGD",
        slug="singapore",
        name="Singapore",
        prices=_city_prices(
            city_name="Singapore",
            source_url=_SINGAPORE_SOURCE,
            coffee=("4.23", "8.00"),
            meal=("7.00", "25.00"),
            groceries=("8.46", "24.00"),
            transit=_transit_price(
                label="Adult MRT/LRT card fare",
                low="1.28",
                high="2.57",
                source_name="Public Transport Council Singapore",
                source_url=("https://www.ptc.gov.sg/fares/public-transport-fares-and-passes/"),
                notes=(
                    "Adult card fare range across the published distance bands for MRT/LRT; "
                    "official fare table reviewed 2026-10-01."
                ),
            ),
        ),
    ),
    _CitySpec(
        country_code="CA",
        currency_code="CAD",
        slug="toronto",
        name="Toronto",
        prices=_city_prices(
            city_name="Toronto",
            source_url=_TORONTO_SOURCE,
            coffee=("3.00", "8.00"),
            meal=("16.00", "39.00"),
            groceries=("9.57", "25.99"),
            transit=_transit_price(
                label="TTC adult single fare",
                low="3.30",
                high="3.35",
                source_name="Toronto Transit Commission (TTC)",
                source_url="https://www.ttc.ca/Fares-and-passes",
                notes=(
                    "Adult fare reviewed 2026-10-01: CAD 3.30 with PRESTO/contactless and "
                    "CAD 3.35 with cash or one-ride PRESTO ticket."
                ),
            ),
        ),
    ),
    _CitySpec(
        country_code="NZ",
        currency_code="NZD",
        slug="auckland",
        name="Auckland",
        prices=_city_prices(
            city_name="Auckland",
            source_url=_AUCKLAND_SOURCE,
            coffee=("5.08", "8.00"),
            meal=("20.00", "40.00"),
            groceries=("13.94", "26.20"),
            transit=_transit_price(
                label="Auckland adult 1-zone bus/train fare",
                low="3.00",
                high=None,
                source_name="Auckland Transport",
                source_url=(
                    "https://at.govt.nz/bus-train-ferry/fares-and-discounts/"
                    "public-transport-fare-changes"
                ),
                notes=(
                    "Adult AT HOP/contactless 1-zone bus/train fare effective 2026-02-01 and "
                    "reviewed 2026-10-01."
                ),
            ),
        ),
    ),
)


def _seed_curated_city_prices(
    *,
    cities: tuple[_CitySpec, ...],
    observed_at: date,
    verified_at: datetime,
) -> tuple[int, int]:
    created = existing = 0

    for city_spec in cities:
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
                observed_at=observed_at,
            ).first()
            row_created = row is None
            if row is None:
                row = TypicalPrice(
                    country=country,
                    city_ref=city,
                    category=price_spec.category,
                    unit=price_spec.unit,
                    label=price_spec.label,
                    observed_at=observed_at,
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


def seed_curated_city_prices_wave1() -> tuple[int, int]:
    """Seed reviewed European/Nordic city anchors through the canonical quality contract."""

    return _seed_curated_city_prices(
        cities=_WAVE_ONE_CITIES,
        observed_at=_WAVE_ONE_OBSERVED_AT,
        verified_at=_WAVE_ONE_VERIFIED_AT,
    )


def seed_curated_city_prices_wave2() -> tuple[int, int]:
    """Seed reviewed Asia/Oceania/North America city anchors without parallel state."""

    return _seed_curated_city_prices(
        cities=_WAVE_TWO_CITIES,
        observed_at=_WAVE_TWO_OBSERVED_AT,
        verified_at=_WAVE_TWO_VERIFIED_AT,
    )
