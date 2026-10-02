from __future__ import annotations

from datetime import date
from urllib.parse import urlencode

from django.urls import reverse

from apps.culture.explore import ExploreDestination
from apps.culture.explore_collections import (
    ExploreCollection,
    ExploreCollectionItem,
    ExploreCollectionKind,
)
from apps.culture.explore_navigation import ExploreRegionNode


def _converter_url(*, country_code: str, currency_code: str, city_slug: str = "") -> str:
    params = {
        "load": "1",
        "destination_country": country_code,
        "destination_currency": currency_code,
    }
    if city_slug:
        params["destination_city_slug"] = city_slug
    return f"{reverse('converter')}?{urlencode(params)}"


def _city_profile_url(*, country_code: str, city_slug: str) -> str:
    return reverse(
        "city_money_profile",
        kwargs={"country_code": country_code, "city_slug": city_slug},
    )


def _destination_token(*, country_code: str, city_slug: str = "") -> str:
    return f"{country_code}:{city_slug}" if city_slug else country_code


def _compare_url(*, country_code: str, city_slug: str = "") -> str:
    params = {
        "left_destination": _destination_token(
            country_code=country_code,
            city_slug=city_slug,
        )
    }
    return f"{reverse('destination_comparison')}?{urlencode(params)}"


def _save_place_url(*, country_code: str, city_slug: str = "") -> str:
    params = {
        "place": _destination_token(
            country_code=country_code,
            city_slug=city_slug,
        )
    }
    return f"{reverse('saved_state')}?{urlencode(params)}"


def build_explore_destination_cards(
    destinations: tuple[ExploreDestination, ...],
) -> tuple[dict[str, object], ...]:
    cards: list[dict[str, object]] = []
    for destination in destinations:
        cards.append(
            {
                "destination": destination,
                "converter_url": _converter_url(
                    country_code=destination.country_code,
                    currency_code=destination.currency_code,
                    city_slug=destination.city_slug,
                ),
                "profile_url": (
                    _city_profile_url(
                        country_code=destination.country_code,
                        city_slug=destination.city_slug,
                    )
                    if destination.city_slug
                    else ""
                ),
                "compare_url": _compare_url(
                    country_code=destination.country_code,
                    city_slug=destination.city_slug,
                ),
                "save_place_url": _save_place_url(
                    country_code=destination.country_code,
                    city_slug=destination.city_slug,
                ),
            }
        )
    return tuple(cards)


def build_explore_region_components(
    regions: tuple[ExploreRegionNode, ...],
) -> tuple[dict[str, object], ...]:
    components: list[dict[str, object]] = []
    for region in regions:
        countries: list[dict[str, object]] = []
        for country in region.countries:
            cities = tuple(
                {
                    "slug": city.slug,
                    "name": city.name,
                    "scope_label": city.scope_label,
                    "currency_code": city.currency_code,
                    "profile_url": _city_profile_url(
                        country_code=country.country_code,
                        city_slug=city.slug,
                    ),
                    "converter_url": _converter_url(
                        country_code=country.country_code,
                        currency_code=city.currency_code,
                        city_slug=city.slug,
                    ),
                    "compare_url": _compare_url(
                        country_code=country.country_code,
                        city_slug=city.slug,
                    ),
                    "save_place_url": _save_place_url(
                        country_code=country.country_code,
                        city_slug=city.slug,
                    ),
                }
                for city in country.cities
            )
            countries.append(
                {
                    "country_code": country.country_code,
                    "country_name": country.country_name,
                    "subregion": country.subregion,
                    "currency_code": country.currency_code,
                    "has_country_scope": country.has_country_scope,
                    "converter_url": (
                        _converter_url(
                            country_code=country.country_code,
                            currency_code=country.currency_code,
                        )
                        if country.has_country_scope
                        else ""
                    ),
                    "compare_url": _compare_url(country_code=country.country_code),
                    "save_place_url": _save_place_url(country_code=country.country_code),
                    "cities": cities,
                }
            )
        components.append(
            {
                "slug": region.slug,
                "name": region.name,
                "countries": tuple(countries),
            }
        )
    return tuple(components)


def _collection_action(
    *,
    kind: ExploreCollectionKind,
    item: ExploreCollectionItem,
    selected_date: date,
) -> tuple[str, str]:
    country_code = item.country_codes[0] if item.country_codes else ""
    currency_code = item.currency_codes[0] if item.currency_codes else ""

    if item.city_slug and country_code:
        return (
            _city_profile_url(country_code=country_code, city_slug=item.city_slug),
            "View city profile",
        )

    if kind is ExploreCollectionKind.CURRENCY_STORIES and (country_code or currency_code):
        params = {
            "destination_country": country_code,
            "destination_currency": currency_code,
            "selected_date": selected_date.isoformat(),
            "historical": "0",
        }
        return f"{reverse('money_culture_story')}?{urlencode(params)}", "Read money story"

    if kind is ExploreCollectionKind.CASH_CARD_BEHAVIOUR and country_code and currency_code:
        return (
            _converter_url(country_code=country_code, currency_code=currency_code),
            "Open payment context",
        )

    if kind is ExploreCollectionKind.SHARED_CURRENCY_COUNTRIES:
        return "#regional-directory", "Browse countries"

    if country_code and currency_code:
        return (
            _converter_url(country_code=country_code, currency_code=currency_code),
            "Open destination",
        )

    return "", ""


def build_explore_collection_components(
    collections: tuple[ExploreCollection, ...],
    *,
    selected_date: date,
) -> tuple[dict[str, object], ...]:
    components: list[dict[str, object]] = []
    for collection in collections:
        items: list[dict[str, object]] = []
        for item in collection.items:
            action_url, action_label = _collection_action(
                kind=collection.kind,
                item=item,
                selected_date=selected_date,
            )
            items.append(
                {
                    "key": item.key,
                    "title": item.title,
                    "summary": item.summary,
                    "country_codes": item.country_codes,
                    "currency_codes": item.currency_codes,
                    "reviewed_on": item.reviewed_on,
                    "city_slug": item.city_slug,
                    "evidence": item.evidence,
                    "action_url": action_url,
                    "action_label": action_label,
                }
            )
        components.append(
            {
                "kind": collection.kind.value,
                "slug": collection.slug,
                "title": collection.title,
                "description": collection.description,
                "items": tuple(items),
            }
        )
    return tuple(components)
