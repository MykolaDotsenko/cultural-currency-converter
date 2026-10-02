from __future__ import annotations

from datetime import date

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.countries.models import Country, CountryCurrency, Currency
from apps.culture.models import (
    StoryDatePrecision,
    StoryMoment,
    StoryMomentCategory,
    StoryMomentStatus,
    StorySourceKind,
)
from apps.culture.services import approve_story_moment, publish_story_moment
from apps.culture.story import StoryRequest, compose_story


@pytest.fixture
def context_data(db):
    fi = Country.objects.create(iso2="FI", iso3="FIN", name="Finland")
    jp = Country.objects.create(iso2="JP", iso3="JPN", name="Japan")
    eur = Currency.objects.create(code="EUR", name="Euro", symbol="€")
    jpy = Currency.objects.create(code="JPY", name="Japanese yen", symbol="¥")
    CountryCurrency.objects.create(
        country=fi,
        currency=eur,
        is_primary=True,
        valid_from=date(2002, 1, 1),
        source="https://example.org/finland-euro",
    )
    CountryCurrency.objects.create(
        country=jp,
        currency=jpy,
        is_primary=True,
        source="https://example.org/japan-yen",
    )
    return fi, jp, eur, jpy


def _request(*, selected_date=date(2026, 9, 21), historical=False):
    return StoryRequest(
        source_country="FI",
        source_currency="EUR",
        destination_country="JP",
        destination_currency="JPY",
        selected_date=selected_date,
        historical=historical,
    )


@pytest.mark.django_db
def test_composer_builds_currency_eras_without_inventing_filler(context_data):
    story = compose_story(_request())

    assert story.status == "full"
    assert [chapter.kind for chapter in story.chapters] == [
        "source_currency_era",
        "destination_currency_era",
    ]
    assert "Finland records Euro" in story.chapters[0].body
    assert story.chapters[0].source_refs[0].url == "https://example.org/finland-euro"
    assert story.currency_era_chapters == story.chapters
    assert story.historical_moment_chapters == ()


@pytest.mark.django_db
def test_composer_suppresses_credentialed_currency_relationship_source(context_data):
    fi, _jp, eur, _jpy = context_data
    link = CountryCurrency.objects.get(country=fi, currency=eur)
    link.source = "https://user:secret@example.org/finland-euro"
    link.save(update_fields=("source",))

    story = compose_story(_request())

    source_chapter = next(
        chapter for chapter in story.chapters if chapter.kind == "source_currency_era"
    )
    assert source_chapter.source_refs == ()


@pytest.mark.django_db
def test_composer_adds_reviewed_story_moment(context_data):
    fi, _jp, eur, _jpy = context_data
    moment = StoryMoment.objects.create(
        category=StoryMomentCategory.MONETARY_UNION,
        title="Finland adopted the euro",
        summary="Finland adopted the euro in a sourced transition.",
        start_date=date(1999, 1, 1),
        end_date=date(1999, 1, 1),
        date_precision=StoryDatePrecision.EXACT_DAY,
        source_kind=StorySourceKind.OFFICIAL,
        source_name="Official source",
        source_url="https://example.org/euro",
        verified_at=timezone.now(),
        relevance_weight=95,
        status=StoryMomentStatus.NEEDS_REVIEW,
    )
    moment.countries.add(fi)
    moment.currencies.add(eur)
    approve_story_moment(moment)
    publish_story_moment(moment)

    story = compose_story(_request())

    assert any(chapter.title == "Finland adopted the euro" for chapter in story.chapters)
    chapter = next(c for c in story.chapters if c.title == "Finland adopted the euro")
    assert chapter.body == "Finland adopted the euro in a sourced transition."
    assert chapter.source_refs[0].label == "Official source"
    assert [item.kind for item in story.currency_era_chapters] == [
        "source_currency_era",
        "destination_currency_era",
    ]
    assert story.historical_moment_chapters == (chapter,)


@pytest.mark.django_db
def test_historical_story_excludes_future_moment_but_keeps_currency_era(context_data):
    fi, _jp, eur, _jpy = context_data
    moment = StoryMoment.objects.create(
        category=StoryMomentCategory.CASH_CHANGEOVER,
        title="Future from selected date",
        summary="Euro cash entered circulation later.",
        start_date=date(2002, 1, 1),
        end_date=date(2002, 2, 28),
        date_precision=StoryDatePrecision.RANGE,
        source_kind=StorySourceKind.OFFICIAL,
        source_name="Official source",
        source_url="https://example.org/euro",
        verified_at=timezone.now(),
        status=StoryMomentStatus.NEEDS_REVIEW,
    )
    moment.countries.add(fi)
    moment.currencies.add(eur)
    approve_story_moment(moment)
    publish_story_moment(moment)

    story = compose_story(_request(selected_date=date(2001, 1, 1), historical=True))

    assert all(chapter.title != "Future from selected date" for chapter in story.chapters)
    assert any(chapter.kind == "destination_currency_era" for chapter in story.chapters)


@pytest.mark.django_db
def test_no_relationships_and_no_story_moments_returns_unavailable(db):
    story = compose_story(
        StoryRequest(
            source_country="",
            source_currency="AAA",
            destination_country="",
            destination_currency="BBB",
            selected_date=date(2026, 9, 21),
            historical=False,
        )
    )

    assert story.status == "unavailable"
    assert story.chapters == ()


@pytest.mark.django_db
def test_story_composer_has_bounded_query_count_with_reviewed_fact(context_data):
    fi, _jp, eur, _jpy = context_data
    moment = StoryMoment.objects.create(
        category=StoryMomentCategory.MONETARY_UNION,
        title="Bounded query story",
        summary="A reviewed sourced monetary fact.",
        start_date=date(1999, 1, 1),
        end_date=date(1999, 1, 1),
        date_precision=StoryDatePrecision.EXACT_DAY,
        source_kind=StorySourceKind.OFFICIAL,
        source_name="Official source",
        source_url="https://example.org/query-budget",
        verified_at=timezone.now(),
        relevance_weight=80,
        status=StoryMomentStatus.NEEDS_REVIEW,
    )
    moment.countries.add(fi)
    moment.currencies.add(eur)
    approve_story_moment(moment)
    publish_story_moment(moment)

    with CaptureQueriesContext(connection) as captured:
        story = compose_story(_request())

    assert story.status == "full"
    assert len(captured) <= 4
