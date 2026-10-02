from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from urllib.parse import urlencode

from django.urls import reverse
from django.utils.text import slugify

from apps.countries.models import Country
from apps.culture.explore import ExploreDestination
from apps.culture.explore_collections import (
    ExploreCollection,
    ExploreCollectionEvidence,
    ExploreCollectionKind,
)


@dataclass(frozen=True, slots=True)
class ExploreDestinationCard:
    destination: ExploreDestination
    converter_url: str
    profile_url: str = ""


@dataclass(frozen=True, slots=True)
class ExploreCountryNode:
    country_code: str
    country_name: str
    region_name: str
    region_slug: str
    subregion_name: str
    currency_code: str
    filter_url: str
    country_card: ExploreDestinationCard | None
    city_cards: tuple[ExploreDestinationCard, ...]

    @property
    def city_count(self) -> int:
        return len(self.city_cards)

    @property
    def reviewed_scope_count(self) -> int:
        return self.city_count + (1 if self.country_card is not None else 0)


@dataclass(frozen=True, slots=True)
class ExploreRegionNode:
    name: str
    slug: str
    filter_url: str
    countries: tuple[ExploreCountryNode, ...]

    @property
    def country_count(self) -> int:
        return len(self.countries)

    @property
    def city_count(self) -> int:
        return sum(country.city_count for country in self.countries)

    @property
    def reviewed_scope_count(self) -> int:
        return sum(country.reviewed_scope_count for country in self.countries)


@dataclass(frozen=True, slots=True)
class ExploreNavigation:
    regions: tuple[ExploreRegionNode, ...]
    selected_region_slug: str
    selected_region_name: str
    selected_country_code: str
    selected_country_name: str
    visible_countries: tuple[ExploreCountryNode, ...]
    visible_destinations: tuple[ExploreDestinationCard, ...]
    scope_country_codes: tuple[str, ...]

    @property
    def region_count(self) -> int:
        return len(self.regions)

    @property
    def country_count(self) -> int:
        return sum(region.country_count for region in self.regions)

    @property
    def city_count(self) -> int:
        return sum(region.city_count for region in self.regions)

    @property
    def focus_label(self) -> str:
        if self.selected_country_name:
            return self.selected_country_name
        if self.selected_region_name:
            return self.selected_region_name
        return "All reviewed destinations"


@dataclass(frozen=True, slots=True)
class ExploreCollectionItemCard:
    key: str
    title: str
    summary: str
    reviewed_on: date | None
    evidence: tuple[ExploreCollectionEvidence, ...]
    primary_label: str
    primary_url: str
    primary_external: bool = False


@dataclass(frozen=True, slots=True)
class ExploreCollectionSection:
    kind: ExploreCollectionKind
    slug: str
    title: str
    description: str
    items: tuple[ExploreCollectionItemCard, ...]


def build_destination_card(destination: ExploreDestination) -> ExploreDestinationCard:
    params = {
        "load": "1",
        "destination_country": destination.country_code,
        "destination_currency": destination.currency_code,
    }
    if destination.city_slug:
        params["destination_city_slug"] = destination.city_slug

    profile_url = ""
    if destination.city_slug:
        profile_url = reverse(
            "city_money_profile",
            kwargs={
                "country_code": destination.country_code,
                "city_slug": destination.city_slug,
            },
        )

    return ExploreDestinationCard(
        destination=destination,
        converter_url=f"{reverse('converter')}?{urlencode(params)}",
        profile_url=profile_url,
    )


def build_explore_navigation(
    destinations: tuple[ExploreDestination, ...],
    *,
    requested_region: str = "",
    requested_country: str = "",
) -> ExploreNavigation:
    """Compose region → country → city navigation from canonical Country/City identities."""

    cards = tuple(build_destination_card(destination) for destination in destinations)
    country_codes = sorted({card.destination.country_code for card in cards})
    countries = {
        country.iso2: country
        for country in Country.objects.filter(iso2__in=country_codes, is_active=True)
    }

    grouped_cards: dict[str, list[ExploreDestinationCard]] = {}
    for card in cards:
        if card.destination.country_code not in countries:
            continue
        grouped_cards.setdefault(card.destination.country_code, []).append(card)

    country_nodes: list[ExploreCountryNode] = []
    for country_code in country_codes:
        country = countries.get(country_code)
        if country is None:
            continue
        country_cards = grouped_cards.get(country_code, [])
        country_card = next(
            (card for card in country_cards if not card.destination.is_city_scope),
            None,
        )
        city_cards = tuple(
            sorted(
                (card for card in country_cards if card.destination.is_city_scope),
                key=lambda card: (
                    card.destination.city_name.casefold(),
                    card.destination.city_slug,
                ),
            )
        )
        region_name = country.region.strip() or "Other reviewed places"
        region_slug = slugify(region_name) or "other-reviewed-places"
        subregion_name = country.subregion.strip()
        currency_code = (
            country_card.destination.currency_code
            if country_card is not None
            else city_cards[0].destination.currency_code
        )
        filter_url = f"{reverse('explore')}?{urlencode({'region': region_slug, 'country': country_code})}"
        country_nodes.append(
            ExploreCountryNode(
                country_code=country_code,
                country_name=country.name,
                region_name=region_name,
                region_slug=region_slug,
                subregion_name=subregion_name,
                currency_code=currency_code,
                filter_url=filter_url,
                country_card=country_card,
                city_cards=city_cards,
            )
        )

    grouped_countries: dict[tuple[str, str], list[ExploreCountryNode]] = {}
    for node in country_nodes:
        grouped_countries.setdefault((node.region_name, node.region_slug), []).append(node)

    regions: list[ExploreRegionNode] = []
    for (region_name, region_slug), nodes in sorted(
        grouped_countries.items(),
        key=lambda item: (item[0][0].casefold(), item[0][1]),
    ):
        sorted_nodes = tuple(
            sorted(nodes, key=lambda node: (node.country_name.casefold(), node.country_code))
        )
        regions.append(
            ExploreRegionNode(
                name=region_name,
                slug=region_slug,
                filter_url=f"{reverse('explore')}?{urlencode({'region': region_slug})}",
                countries=sorted_nodes,
            )
        )

    requested_region_slug = slugify(requested_region.strip())
    requested_country_code = requested_country.strip().upper()

    selected_country = next(
        (
            country
            for region in regions
            for country in region.countries
            if country.country_code == requested_country_code
        ),
        None,
    )
    if selected_country is not None:
        selected_region_slug = selected_country.region_slug
        selected_region_name = selected_country.region_name
        selected_country_code = selected_country.country_code
        selected_country_name = selected_country.country_name
    else:
        selected_region = next(
            (region for region in regions if region.slug == requested_region_slug),
            None,
        )
        selected_region_slug = selected_region.slug if selected_region is not None else ""
        selected_region_name = selected_region.name if selected_region is not None else ""
        selected_country_code = ""
        selected_country_name = ""

    if selected_country_code:
        visible_countries = tuple(
            country
            for region in regions
            for country in region.countries
            if country.country_code == selected_country_code
        )
    elif selected_region_slug:
        visible_countries = next(
            region.countries for region in regions if region.slug == selected_region_slug
        )
    else:
        visible_countries = tuple(country for region in regions for country in region.countries)

    visible_destinations: list[ExploreDestinationCard] = []
    for country in visible_countries:
        if country.country_card is not None:
            visible_destinations.append(country.country_card)
        visible_destinations.extend(country.city_cards)

    return ExploreNavigation(
        regions=tuple(regions),
        selected_region_slug=selected_region_slug,
        selected_region_name=selected_region_name,
        selected_country_code=selected_country_code,
        selected_country_name=selected_country_name,
        visible_countries=visible_countries,
        visible_destinations=tuple(visible_destinations),
        scope_country_codes=tuple(country.country_code for country in visible_countries),
    )


def build_explore_collection_sections(
    collections: tuple[ExploreCollection, ...],
    *,
    scope_country_codes: tuple[str, ...] = (),
) -> tuple[ExploreCollectionSection, ...]:
    """Turn reviewed collection items into truthful user-facing discovery cards."""

    allowed = set(scope_country_codes)
    sections: list[ExploreCollectionSection] = []

    for collection in collections:
        item_cards: list[ExploreCollectionItemCard] = []
        for item in collection.items:
            if allowed and not allowed.intersection(item.country_codes):
                continue

            primary_label = ""
            primary_url = ""
            primary_external = False

            if item.city_slug and item.country_codes:
                primary_label = "Open city profile"
                primary_url = reverse(
                    "city_money_profile",
                    kwargs={
                        "country_code": item.country_codes[0],
                        "city_slug": item.city_slug,
                    },
                )
            elif collection.kind in {
                ExploreCollectionKind.CASH_CARD_BEHAVIOUR,
                ExploreCollectionKind.RECENTLY_REVIEWED_DESTINATIONS,
            } and item.country_codes and item.currency_codes:
                params = {
                    "load": "1",
                    "destination_country": item.country_codes[0],
                    "destination_currency": item.currency_codes[0],
                }
                primary_label = "Open money context"
                primary_url = f"{reverse('converter')}?{urlencode(params)}"
            elif collection.kind == ExploreCollectionKind.CURRENCY_STORIES and item.evidence:
                primary_label = "Read reviewed source"
                primary_url = item.evidence[0].source_url
                primary_external = True

            item_cards.append(
                ExploreCollectionItemCard(
                    key=item.key,
                    title=item.title,
                    summary=item.summary,
                    reviewed_on=item.reviewed_on,
                    evidence=item.evidence,
                    primary_label=primary_label,
                    primary_url=primary_url,
                    primary_external=primary_external,
                )
            )

        if not item_cards:
            continue
        sections.append(
            ExploreCollectionSection(
                kind=collection.kind,
                slug=collection.slug,
                title=collection.title,
                description=collection.description,
                items=tuple(item_cards),
            )
        )

    return tuple(sections)
