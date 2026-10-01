from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date

from django.utils import timezone

from apps.countries.models import City, CountryCurrency
from apps.culture.models import TypicalPrice, TypicalPriceCategory
from apps.culture.price_quality import (
    TypicalPriceQualityCode,
    TypicalPriceQualityInput,
    evaluate_typical_price_quality,
)

CITY_COVERAGE_CORE_CATEGORIES: tuple[str, ...] = (
    TypicalPriceCategory.COFFEE,
    TypicalPriceCategory.CASUAL_MEAL,
    TypicalPriceCategory.TRANSIT,
    TypicalPriceCategory.GROCERIES,
)
_FRESH_CITY_POINTS = 25
_NATIONAL_FALLBACK_POINTS = 15
_PROVENANCE_CODES = frozenset(
    {
        TypicalPriceQualityCode.SOURCE_NAME_MISSING,
        TypicalPriceQualityCode.PROVENANCE_INVALID,
        TypicalPriceQualityCode.VERIFICATION_MISSING,
    }
)


@dataclass(frozen=True, slots=True)
class CityCoverageHealth:
    country_code: str
    country_name: str
    city_slug: str
    city_name: str
    currency_code: str
    total_supported_categories: int
    fresh_categories: tuple[str, ...]
    stale_categories: tuple[str, ...]
    national_fallback_categories: tuple[str, ...]
    provenance_gap_categories: tuple[str, ...]
    coverage_score: int
    summary: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class _PriceClassification:
    category: str
    fresh: bool
    stale: bool
    provenance_gap: bool


def build_city_coverage_health(
    *,
    as_of: date | None = None,
    country_code: str = "",
    city_slug: str = "",
) -> tuple[CityCoverageHealth, ...]:
    selected_date = as_of or timezone.localdate()
    normalized_country = country_code.strip().upper()
    normalized_city = city_slug.strip().lower()

    cities = City.objects.filter(is_active=True).select_related("country")
    if normalized_country:
        cities = cities.filter(country__iso2=normalized_country)
    if normalized_city:
        cities = cities.filter(slug=normalized_city)
    city_rows = tuple(cities.order_by("country__name", "name", "slug"))
    if not city_rows:
        return ()

    country_ids = {city.country_id for city in city_rows}
    current_links = tuple(
        CountryCurrency.objects.current(selected_date)
        .primary()
        .filter(country_id__in=country_ids)
        .select_related("currency")
    )
    links_by_country = {link.country_id: link for link in current_links}

    price_rows = tuple(
        TypicalPrice.objects.filter(
            country_id__in=country_ids,
            is_published=True,
            observed_at__lte=selected_date,
        )
        .select_related("country", "currency", "city_ref", "city_ref__country")
        .order_by("country_id", "city_ref_id", "category", "observed_at", "pk")
    )

    direct_by_city: dict[int, list[TypicalPrice]] = {}
    national_by_country: dict[int, list[TypicalPrice]] = {}
    for row in price_rows:
        if row.city_ref_id is not None:
            direct_by_city.setdefault(row.city_ref_id, []).append(row)
        elif not row.city:
            national_by_country.setdefault(row.country_id, []).append(row)

    reports: list[CityCoverageHealth] = []
    for city in city_rows:
        link = links_by_country.get(city.country_id)
        currency_code = link.currency.code if link is not None else ""

        direct = tuple(
            _classify_price(row, current_currency_code=currency_code, as_of=selected_date)
            for row in direct_by_city.get(city.pk, ())
        )
        national = tuple(
            _classify_price(row, current_currency_code=currency_code, as_of=selected_date)
            for row in national_by_country.get(city.country_id, ())
        )

        fresh = {item.category for item in direct if item.fresh}
        stale = {item.category for item in direct if item.stale and item.category not in fresh}
        national_fallback = {
            item.category
            for item in national
            if item.fresh and item.category not in fresh
        }
        provenance_gaps = {
            item.category
            for item in (*direct, *national)
            if item.provenance_gap
        }
        supported = fresh | national_fallback

        core_fresh = fresh.intersection(CITY_COVERAGE_CORE_CATEGORIES)
        core_fallback = national_fallback.intersection(CITY_COVERAGE_CORE_CATEGORIES)
        score = min(
            100,
            len(core_fresh) * _FRESH_CITY_POINTS
            + len(core_fallback) * _NATIONAL_FALLBACK_POINTS,
        )

        fresh_categories = _ordered_categories(fresh)
        stale_categories = _ordered_categories(stale)
        fallback_categories = _ordered_categories(national_fallback)
        provenance_categories = _ordered_categories(provenance_gaps)

        reports.append(
            CityCoverageHealth(
                country_code=city.country.iso2,
                country_name=city.country.name,
                city_slug=city.slug,
                city_name=city.name,
                currency_code=currency_code,
                total_supported_categories=len(supported),
                fresh_categories=fresh_categories,
                stale_categories=stale_categories,
                national_fallback_categories=fallback_categories,
                provenance_gap_categories=provenance_categories,
                coverage_score=score,
                summary=(
                    f"{len(core_fresh)}/{len(CITY_COVERAGE_CORE_CATEGORIES)} fresh core city "
                    f"categories; {len(core_fallback)} fresh national fallback; "
                    f"{len(stale_categories)} stale city categories; "
                    f"{len(provenance_categories)} provenance gaps."
                ),
            )
        )

    return tuple(reports)


def _classify_price(
    row: TypicalPrice,
    *,
    current_currency_code: str,
    as_of: date,
) -> _PriceClassification:
    city = row.city_ref if row.city_ref_id is not None else None
    issues = evaluate_typical_price_quality(
        TypicalPriceQualityInput(
            category=row.category,
            unit=row.unit,
            amount_low=row.amount_low,
            amount_high=row.amount_high,
            country_code=row.country.iso2,
            currency_code=row.currency.code,
            current_primary_currency_code=current_currency_code,
            city_text=row.city,
            city_slug=city.slug if city is not None else "",
            city_country_code=city.country.iso2 if city is not None else "",
            city_active=city.is_active if city is not None else False,
            source_name=row.source_name,
            source_url=row.source_url,
            observed_at=row.observed_at,
            verified_at=row.verified_at,
            is_published=row.is_published,
        ),
        today=as_of,
    )
    codes = {issue.code for issue in issues}
    return _PriceClassification(
        category=row.category,
        fresh=not codes,
        stale=codes == {TypicalPriceQualityCode.OBSERVATION_STALE},
        provenance_gap=bool(codes.intersection(_PROVENANCE_CODES)),
    )


def _ordered_categories(categories: set[str]) -> tuple[str, ...]:
    order = {category: index for index, category in enumerate(TypicalPriceCategory.values)}
    return tuple(sorted(categories, key=lambda category: (order.get(category, 999), category)))
