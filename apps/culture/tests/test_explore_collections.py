from __future__ import annotations

from datetime import date
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command

from apps.countries.models import CountryCurrency
from apps.culture.explore_collections import (
    ExploreCollectionKind,
    build_explore_collections,
)
from apps.culture.models import CulturalProfile, StoryMoment

AS_OF = date(2026, 10, 1)


@pytest.fixture
def seeded_collections(db):
    call_command("seed_reference_data", stdout=StringIO())
    call_command("seed_story_data", stdout=StringIO())
    call_command("seed_destination_context", stdout=StringIO())


@pytest.mark.django_db
def test_explore_collections_compose_all_reviewed_domain_kinds(seeded_collections):
    collections = build_explore_collections(as_of=AS_OF)

    assert [collection.kind for collection in collections] == [
        ExploreCollectionKind.CITY_MONEY_PROFILES,
        ExploreCollectionKind.CURRENCY_STORIES,
        ExploreCollectionKind.CASH_CARD_BEHAVIOUR,
        ExploreCollectionKind.SHARED_CURRENCY_COUNTRIES,
        ExploreCollectionKind.RECENTLY_REVIEWED_DESTINATIONS,
    ]
    assert all(collection.items for collection in collections)
    assert all(item.has_provenance for collection in collections for item in collection.items)


@pytest.mark.django_db
def test_city_money_profile_collection_uses_direct_city_evidence_only(seeded_collections):
    collection = next(
        collection
        for collection in build_explore_collections(as_of=AS_OF)
        if collection.kind == ExploreCollectionKind.CITY_MONEY_PROFILES
    )

    assert [item.title for item in collection.items] == [
        "Auckland, New Zealand",
        "Berlin, Germany",
        "Copenhagen, Denmark",
        "Helsinki, Finland",
        "Oslo, Norway",
        "Singapore, Singapore",
    ]
    assert all(item.city_slug for item in collection.items)
    assert all(item.reviewed_on == AS_OF for item in collection.items)
    assert all(item.key.startswith("city:") for item in collection.items)
    assert all(item.evidence for item in collection.items)


@pytest.mark.django_db
def test_currency_story_collection_is_published_provenance_aware_and_alphabetic(
    seeded_collections,
):
    collection = next(
        collection
        for collection in build_explore_collections(as_of=AS_OF)
        if collection.kind == ExploreCollectionKind.CURRENCY_STORIES
    )

    assert [item.title for item in collection.items] == [
        "Euro cash arrived in Finland",
        "Finland adopted the euro",
        "The yen became Japan's currency unit",
    ]
    assert all(item.key.startswith("story:") for item in collection.items)
    assert all(item.reviewed_on is not None for item in collection.items)
    assert all(item.evidence[0].source_url.startswith("https://") for item in collection.items)


@pytest.mark.django_db
def test_cash_card_collection_uses_reviewed_current_country_context(seeded_collections):
    collection = next(
        collection
        for collection in build_explore_collections(as_of=AS_OF)
        if collection.kind == ExploreCollectionKind.CASH_CARD_BEHAVIOUR
    )

    assert len(collection.items) == 1
    japan = collection.items[0]
    assert japan.key == "payment:JP"
    assert japan.title == "Japan"
    assert japan.country_codes == ("JP",)
    assert japan.currency_codes == ("JPY",)
    assert japan.evidence[0].source_url.startswith("https://")


@pytest.mark.django_db
def test_shared_currency_collection_requires_multiple_current_primary_countries(
    seeded_collections,
):
    collection = next(
        collection
        for collection in build_explore_collections(as_of=AS_OF)
        if collection.kind == ExploreCollectionKind.SHARED_CURRENCY_COUNTRIES
    )

    assert len(collection.items) == 1
    euro = collection.items[0]
    assert euro.key == "shared-currency:EUR"
    assert euro.title == "Euro · EUR"
    assert euro.country_codes == ("FI", "DE")
    assert euro.currency_codes == ("EUR",)
    assert "Finland, Germany" in euro.summary
    assert euro.reviewed_on is None
    assert euro.has_provenance is True


@pytest.mark.django_db
def test_recent_destination_collection_orders_by_price_evidence_not_popularity(
    seeded_collections,
):
    collection = next(
        collection
        for collection in build_explore_collections(as_of=AS_OF)
        if collection.kind == ExploreCollectionKind.RECENTLY_REVIEWED_DESTINATIONS
    )

    assert [item.title for item in collection.items] == [
        "Auckland, New Zealand",
        "Berlin, Germany",
        "Copenhagen, Denmark",
        "Helsinki, Finland",
        "Oslo, Norway",
        "Singapore, Singapore",
    ]
    assert all(item.reviewed_on == AS_OF for item in collection.items)
    assert all("popular" not in item.summary.casefold() for item in collection.items)


@pytest.mark.django_db
def test_collection_item_limit_is_applied_independently_per_collection(seeded_collections):
    collections = build_explore_collections(as_of=AS_OF, item_limit=2)

    assert all(1 <= len(collection.items) <= 2 for collection in collections)
    story = next(
        collection
        for collection in collections
        if collection.kind == ExploreCollectionKind.CURRENCY_STORIES
    )
    assert len(story.items) == 2


@pytest.mark.django_db
def test_invalid_story_provenance_is_suppressed_without_hiding_valid_collection(
    seeded_collections,
):
    corrupted = StoryMoment.objects.get(external_id="curated:fi-euro-cash-changeover")
    StoryMoment.objects.filter(pk=corrupted.pk).update(
        source_url="https://user:secret@example.org/story"
    )

    collection = next(
        collection
        for collection in build_explore_collections(as_of=AS_OF)
        if collection.kind == ExploreCollectionKind.CURRENCY_STORIES
    )

    assert corrupted.title not in {item.title for item in collection.items}
    assert len(collection.items) == 2
    assert all(item.has_provenance for item in collection.items)


@pytest.mark.django_db
def test_shared_currency_collection_fails_closed_when_one_relationship_loses_provenance(
    seeded_collections,
):
    germany_euro = CountryCurrency.objects.get(country__iso2="DE", currency__code="EUR")
    CountryCurrency.objects.filter(pk=germany_euro.pk).update(source="not-a-url")

    kinds = {collection.kind for collection in build_explore_collections(as_of=AS_OF)}

    assert ExploreCollectionKind.SHARED_CURRENCY_COUNTRIES not in kinds


@pytest.mark.django_db
def test_cash_card_collection_fails_closed_on_invalid_profile_provenance(seeded_collections):
    CulturalProfile.objects.filter(country__iso2="JP").update(
        source_url="https://user:secret@example.org/payment"
    )

    kinds = {collection.kind for collection in build_explore_collections(as_of=AS_OF)}

    assert ExploreCollectionKind.CASH_CARD_BEHAVIOUR not in kinds


def test_explore_collection_item_limit_is_bounded():
    with pytest.raises(ValueError, match="between 1 and 12"):
        build_explore_collections(item_limit=13)


@pytest.mark.django_db
def test_explore_collections_can_reuse_precomputed_destinations(seeded_collections):
    from apps.culture.explore import build_explore_destinations

    destinations = build_explore_destinations(as_of=AS_OF, limit=24)
    with patch(
        "apps.culture.explore_collections.build_explore_destinations",
        side_effect=AssertionError("destinations should be reused"),
    ):
        collections = build_explore_collections(
            as_of=AS_OF,
            destinations=destinations,
        )

    assert collections
    assert collections[0].kind == ExploreCollectionKind.CITY_MONEY_PROFILES
