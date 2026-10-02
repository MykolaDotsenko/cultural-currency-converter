from __future__ import annotations

from datetime import date

import pytest

from apps.countries.models import Country
from apps.culture.explore import ExploreDestination
from apps.culture.explore_collections import (
    ExploreCollection,
    ExploreCollectionEvidence,
    ExploreCollectionItem,
    ExploreCollectionKind,
)
from apps.culture.explore_presentation import (
    build_explore_collection_sections,
    build_explore_navigation,
)


@pytest.mark.django_db
def test_explore_navigation_uses_canonical_region_country_city_hierarchy():
    Country.objects.create(
        iso2="JP",
        iso3="JPN",
        name="Japan",
        region="Asia",
        subregion="Eastern Asia",
    )
    Country.objects.create(
        iso2="FI",
        iso3="FIN",
        name="Finland",
        region="Europe",
        subregion="Northern Europe",
    )
    destinations = (
        ExploreDestination(
            country_code="FI",
            country_name="Finland",
            currency_code="EUR",
            city_slug="helsinki",
            city_name="Helsinki",
            city_price_anchor_count=4,
        ),
        ExploreDestination(
            country_code="JP",
            country_name="Japan",
            currency_code="JPY",
            payment_available=True,
        ),
        ExploreDestination(
            country_code="JP",
            country_name="Japan",
            currency_code="JPY",
            city_slug="tokyo",
            city_name="Tokyo",
            city_price_anchor_count=4,
        ),
    )

    navigation = build_explore_navigation(
        destinations,
        requested_country="jp",
    )

    assert [region.name for region in navigation.regions] == ["Asia", "Europe"]
    assert navigation.selected_region_slug == "asia"
    assert navigation.selected_country_code == "JP"
    assert navigation.focus_label == "Japan"
    assert [card.destination.scope_label for card in navigation.visible_destinations] == [
        "Japan",
        "Tokyo, Japan",
    ]
    japan = navigation.visible_countries[0]
    assert japan.subregion_name == "Eastern Asia"
    assert japan.currency_code == "JPY"
    assert japan.city_count == 1
    assert japan.reviewed_scope_count == 2
    assert "region=asia" in japan.filter_url
    assert "country=JP" in japan.filter_url


@pytest.mark.django_db
def test_explore_navigation_falls_back_without_inventing_geography():
    Country.objects.create(iso2="ZZ", iso3="ZZZ", name="Testland")
    destinations = (
        ExploreDestination(
            country_code="ZZ",
            country_name="Testland",
            currency_code="TST",
            city_slug="test-city",
            city_name="Test City",
            city_price_anchor_count=1,
        ),
    )

    navigation = build_explore_navigation(destinations)

    assert navigation.region_count == 1
    assert navigation.regions[0].name == "Other reviewed places"
    assert navigation.regions[0].slug == "other-reviewed-places"
    assert navigation.regions[0].countries[0].subregion_name == ""


def test_collection_sections_filter_by_selected_geography_and_keep_truthful_actions():
    evidence = (
        ExploreCollectionEvidence(
            source_name="Reviewed source",
            source_url="https://example.org/source",
            evidence_date=date(2026, 10, 1),
        ),
    )
    collections = (
        ExploreCollection(
            kind=ExploreCollectionKind.CITY_MONEY_PROFILES,
            slug="city-money-profiles",
            title="City money profiles",
            description="Reviewed cities.",
            items=(
                ExploreCollectionItem(
                    key="city:JP:tokyo",
                    title="Tokyo, Japan",
                    summary="Reviewed Tokyo context.",
                    country_codes=("JP",),
                    currency_codes=("JPY",),
                    city_slug="tokyo",
                    reviewed_on=date(2026, 10, 1),
                    evidence=evidence,
                ),
                ExploreCollectionItem(
                    key="city:FI:helsinki",
                    title="Helsinki, Finland",
                    summary="Reviewed Helsinki context.",
                    country_codes=("FI",),
                    currency_codes=("EUR",),
                    city_slug="helsinki",
                    reviewed_on=date(2026, 10, 1),
                    evidence=evidence,
                ),
            ),
        ),
        ExploreCollection(
            kind=ExploreCollectionKind.CURRENCY_STORIES,
            slug="currency-stories",
            title="Currency stories",
            description="Reviewed history.",
            items=(
                ExploreCollectionItem(
                    key="story:1",
                    title="The yen became Japan's currency unit",
                    summary="Reviewed history.",
                    country_codes=("JP",),
                    currency_codes=("JPY",),
                    reviewed_on=date(2026, 10, 1),
                    evidence=evidence,
                ),
            ),
        ),
    )

    sections = build_explore_collection_sections(
        collections,
        scope_country_codes=("JP",),
    )

    assert [section.title for section in sections] == [
        "City money profiles",
        "Currency stories",
    ]
    city = sections[0].items[0]
    assert city.title == "Tokyo, Japan"
    assert city.primary_label == "Open city profile"
    assert city.primary_url == "/city/JP/tokyo/"
    assert all(item.title != "Helsinki, Finland" for item in sections[0].items)

    story = sections[1].items[0]
    assert story.primary_label == "Read reviewed source"
    assert story.primary_url == "https://example.org/source"
    assert story.primary_external is True
