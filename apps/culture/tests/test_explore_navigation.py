from __future__ import annotations

from datetime import date
from io import StringIO
from urllib.parse import parse_qs, urlparse

import pytest
from django.core.management import call_command
from django.urls import reverse

from apps.common.presentation.media_view_models import ImageViewModel
from apps.countries.models import Country
from apps.culture.explore import build_explore_destinations
from apps.culture.explore_collections import build_explore_collections
from apps.culture.explore_navigation import build_explore_regions
from apps.culture.explore_presentation import (
    build_explore_collection_components,
    build_explore_region_components,
)

AS_OF = date(2026, 10, 1)


@pytest.fixture
def seeded_explore_ux(db):
    call_command("seed_reference_data", stdout=StringIO())
    call_command("seed_story_data", stdout=StringIO())
    call_command("seed_destination_context", stdout=StringIO())

@pytest.mark.django_db
def test_regional_explore_groups_only_reviewed_destination_scopes(seeded_explore_ux):
    destinations = build_explore_destinations(as_of=AS_OF, limit=24)
    regions = build_explore_regions(destinations)

    assert [region.name for region in regions] == [
        "Americas",
        "Asia",
        "Europe",
        "Oceania",
    ]

    by_name = {region.name: region for region in regions}
    assert [country.country_name for country in by_name["Americas"].countries] == ["Canada"]
    assert [country.country_name for country in by_name["Asia"].countries] == [
        "Japan",
        "Singapore",
    ]
    assert [country.country_name for country in by_name["Oceania"].countries] == ["New Zealand"]

    europe = by_name["Europe"]
    assert {country.country_name for country in europe.countries} == {
        "Denmark",
        "Finland",
        "Germany",
        "Norway",
        "Sweden",
    }

    japan = next(country for country in by_name["Asia"].countries if country.country_code == "JP")
    assert japan.currency_code == "JPY"
    assert japan.has_country_scope is True
    assert [city.name for city in japan.cities] == ["Tokyo"]
    assert japan.cities[0].slug == "tokyo"

    # The reference seed contains the US, but Explore has no reviewed US context yet.
    assert all(country.country_code != "US" for region in regions for country in region.countries)

@pytest.mark.django_db
def test_regional_explore_keeps_unknown_geography_visible_but_last(seeded_explore_ux):
    Country.objects.filter(iso2="JP").update(region="", subregion="")
    destinations = build_explore_destinations(as_of=AS_OF, limit=24)
    regions = build_explore_regions(destinations)

    assert regions[-1].name == "Other reviewed destinations"
    japan = regions[-1].countries[0]
    assert japan.country_code == "JP"
    assert japan.cities[0].name == "Tokyo"

@pytest.mark.django_db
def test_regional_presentation_preserves_canonical_converter_and_profile_handoffs(
    seeded_explore_ux,
):
    destinations = build_explore_destinations(as_of=AS_OF, limit=24)
    regions = build_explore_region_components(build_explore_regions(destinations))

    asia = next(region for region in regions if region["name"] == "Asia")
    japan = next(country for country in asia["countries"] if country["country_code"] == "JP")
    tokyo = japan["cities"][0]

    country_url = urlparse(str(japan["converter_url"]))
    country_query = parse_qs(country_url.query)
    assert country_query["destination_country"] == ["JP"]
    assert country_query["destination_currency"] == ["JPY"]
    assert "destination_city_slug" not in country_query

    city_url = urlparse(str(tokyo["converter_url"]))
    city_query = parse_qs(city_url.query)
    assert city_query["destination_country"] == ["JP"]
    assert city_query["destination_currency"] == ["JPY"]
    assert city_query["destination_city_slug"] == ["tokyo"]
    assert str(tokyo["profile_url"]) == "/city/JP/tokyo/"

    country_compare_url = urlparse(str(japan["comparison_url"]))
    assert country_compare_url.path == reverse("destination_comparison")
    assert parse_qs(country_compare_url.query)["left_destination"] == ["JP"]

    city_compare_url = urlparse(str(tokyo["comparison_url"]))
    assert city_compare_url.path == reverse("destination_comparison")
    assert parse_qs(city_compare_url.query)["left_destination"] == ["JP:tokyo"]

@pytest.mark.django_db
def test_collection_presentation_uses_curated_country_teaser_without_changing_actions(
    seeded_explore_ux,
):
    destinations = build_explore_destinations(as_of=AS_OF, limit=24)
    collections = build_explore_collections(
        as_of=AS_OF,
        item_limit=6,
        destinations=destinations,
    )
    teaser = ImageViewModel(
        src="/media/japan-teaser.webp",
        ratio="4 / 3",
        alt="Reviewed Japan destination teaser.",
        decorative=False,
        kind="contemporary_photo",
        label="Japan teaser",
        width=1200,
        height=900,
    )

    components = build_explore_collection_components(
        collections,
        selected_date=AS_OF,
        teaser_media_by_country={"JP": teaser},
    )

    japan_items = [
        item
        for component in components
        for item in component["items"]
        if item["country_codes"] == ("JP",)
    ]
    assert japan_items
    assert all(item["teaser_image"] is teaser for item in japan_items)
    assert all(item["action_url"] for item in japan_items)

@pytest.mark.django_db
def test_collection_presentation_exposes_evidence_and_useful_actions(seeded_explore_ux):
    destinations = build_explore_destinations(as_of=AS_OF, limit=24)
    collections = build_explore_collections(
        as_of=AS_OF,
        item_limit=6,
        destinations=destinations,
    )
    components = build_explore_collection_components(
        collections,
        selected_date=AS_OF,
    )

    assert len(components) == 5
    assert all(component["items"] for component in components)
    assert all(item["evidence"] for component in components for item in component["items"])

    city_profiles = next(
        component for component in components if component["kind"] == "city_money_profiles"
    )
    assert city_profiles["items"][0]["action_label"] == "View city profile"
    assert str(city_profiles["items"][0]["action_url"]).startswith("/city/")
    city_compare_url = urlparse(str(city_profiles["items"][0]["comparison_url"]))
    assert city_compare_url.path == reverse("destination_comparison")
    assert parse_qs(city_compare_url.query)["left_destination"][0].count(":") == 1

    stories = next(component for component in components if component["kind"] == "currency_stories")
    assert stories["items"][0]["action_label"] == "Read money story"
    story_url = urlparse(str(stories["items"][0]["action_url"]))
    assert story_url.path == reverse("money_culture_story")
    story_query = parse_qs(story_url.query)
    assert story_query["historical"] == ["0"]
    assert story_query["selected_date"] == [AS_OF.isoformat()]
    assert stories["items"][0]["comparison_url"] == ""

    shared = next(
        component for component in components if component["kind"] == "shared_currency_countries"
    )
    assert shared["items"][0]["action_url"] == "#regional-directory"
