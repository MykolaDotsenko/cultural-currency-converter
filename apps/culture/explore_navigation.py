from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from django.utils.text import slugify

from apps.countries.models import Country
from apps.culture.explore import ExploreDestination


@dataclass(frozen=True, slots=True)
class ExploreCityNode:
    slug: str
    name: str
    scope_label: str
    currency_code: str


@dataclass(frozen=True, slots=True)
class ExploreCountryNode:
    country_code: str
    country_name: str
    subregion: str
    currency_code: str
    has_country_scope: bool
    cities: tuple[ExploreCityNode, ...]


@dataclass(frozen=True, slots=True)
class ExploreRegionNode:
    slug: str
    name: str
    countries: tuple[ExploreCountryNode, ...]


def build_explore_regions(
    destinations: Iterable[ExploreDestination],
) -> tuple[ExploreRegionNode, ...]:
    """Group already-reviewed Explore scopes through canonical Country geography."""

    destination_rows = tuple(destinations)
    country_codes = {destination.country_code for destination in destination_rows}
    if not country_codes:
        return ()

    countries = {
        country.iso2: country
        for country in Country.objects.filter(
            iso2__in=country_codes,
            is_active=True,
        ).only("iso2", "name", "region", "subregion")
    }

    country_scopes: set[str] = set()
    city_rows: dict[str, list[ExploreCityNode]] = {}
    currency_by_country: dict[str, str] = {}

    for destination in destination_rows:
        country = countries.get(destination.country_code)
        if country is None:
            continue
        currency_by_country.setdefault(country.iso2, destination.currency_code)
        if destination.is_city_scope:
            city_rows.setdefault(country.iso2, []).append(
                ExploreCityNode(
                    slug=destination.city_slug,
                    name=destination.city_name,
                    scope_label=destination.scope_label,
                    currency_code=destination.currency_code,
                )
            )
        else:
            country_scopes.add(country.iso2)

    grouped: dict[str, list[ExploreCountryNode]] = {}
    for code in sorted(
        currency_by_country,
        key=lambda value: (countries[value].name.casefold(), value),
    ):
        country = countries[code]
        region_name = country.region.strip() or "Other reviewed destinations"
        cities = tuple(
            sorted(
                city_rows.get(code, ()),
                key=lambda city: (city.name.casefold(), city.slug),
            )
        )
        grouped.setdefault(region_name, []).append(
            ExploreCountryNode(
                country_code=code,
                country_name=country.name,
                subregion=country.subregion.strip(),
                currency_code=currency_by_country[code],
                has_country_scope=code in country_scopes,
                cities=cities,
            )
        )

    regions = [
        ExploreRegionNode(
            slug=slugify(region_name) or "other-reviewed-destinations",
            name=region_name,
            countries=tuple(
                sorted(
                    country_nodes,
                    key=lambda item: (item.country_name.casefold(), item.country_code),
                )
            ),
        )
        for region_name, country_nodes in grouped.items()
    ]
    regions.sort(
        key=lambda region: (
            region.name == "Other reviewed destinations",
            region.name.casefold(),
        )
    )
    return tuple(regions)
