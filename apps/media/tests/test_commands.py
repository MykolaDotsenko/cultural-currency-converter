from __future__ import annotations

from datetime import date
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.media.models import DatePrecision, MediaKind, MediaRole, MediaSourceKind, MediaStatus
from apps.media.sources.base import MediaCandidate


@pytest.mark.django_db
def test_wikimedia_ingestion_command_creates_review_candidate_only(monkeypatch):
    monkeypatch.setattr(
        "apps.media.management.commands.ingest_media_candidates.WikimediaCommonsClient.search",
        lambda self, query, limit: (
            MediaCandidate(
                source_kind=MediaSourceKind.WIKIMEDIA_COMMONS,
                external_id="123",
                title="Helsinki",
                source_name="Wikimedia Commons",
                source_url="https://commons.wikimedia.org/wiki/File:Helsinki.jpg",
                source_media_url="https://upload.wikimedia.org/helsinki.jpg",
                creator="Creator",
                licence_id="CC BY 4.0",
                rights_statement="CC BY 4.0",
                attribution_text="Creator · CC BY 4.0",
            ),
        ),
    )
    stdout = StringIO()

    call_command(
        "ingest_media_candidates",
        source="wikimedia",
        query="Helsinki historical money",
        role=MediaRole.HISTORICAL_TIMELINE,
        kind=MediaKind.ARCHIVAL_PHOTO,
        valid_from="1998-01-01",
        valid_to="1998-12-31",
        date_precision=DatePrecision.YEAR,
        limit=1,
        stdout=stdout,
    )

    from apps.media.models import MediaAsset

    asset = MediaAsset.objects.get()
    assert asset.status == MediaStatus.NEEDS_REVIEW
    assert not asset.storage_file
    assert asset.valid_from == date(1998, 1, 1)
    assert asset.valid_to == date(1998, 12, 31)
    assert asset.date_precision == DatePrecision.YEAR
    assert asset.published_at is None
    assert "APPLIED: +1" in stdout.getvalue()


@pytest.mark.django_db
def test_europeana_command_requires_server_side_api_key(monkeypatch):
    monkeypatch.delenv("EUROPEANA_API_KEY", raising=False)

    with pytest.raises(CommandError, match="EUROPEANA_API_KEY"):
        call_command(
            "ingest_media_candidates",
            source="europeana",
            query="markka",
            role=MediaRole.HISTORICAL_TIMELINE,
            kind=MediaKind.ARCHIVAL_PHOTO,
            valid_from="1950-01-01",
            valid_to="1959-12-31",
            date_precision=DatePrecision.DECADE,
        )


@pytest.mark.django_db
def test_ingestion_command_rejects_unknown_country_before_network(monkeypatch):
    called = False

    def unexpected_search(self, query, limit):
        nonlocal called
        called = True
        return ()

    monkeypatch.setattr(
        "apps.media.management.commands.ingest_media_candidates.WikimediaCommonsClient.search",
        unexpected_search,
    )

    with pytest.raises(CommandError, match="Unknown country"):
        call_command(
            "ingest_media_candidates",
            source="wikimedia",
            query="test",
            role=MediaRole.COUNTRY_HERO,
            kind=MediaKind.CONTEMPORARY_PHOTO,
            country="ZZ",
        )

    assert called is False


@pytest.mark.django_db
def test_comparison_then_ingestion_requires_currency_and_temporal_scope_before_network(monkeypatch):
    called = False

    def unexpected_search(self, query, limit):
        nonlocal called
        called = True
        return ()

    monkeypatch.setattr(
        "apps.media.management.commands.ingest_media_candidates.WikimediaCommonsClient.search",
        unexpected_search,
    )

    with pytest.raises(CommandError, match="currency scope"):
        call_command(
            "ingest_media_candidates",
            source="wikimedia",
            query="Japan 1998 street",
            role=MediaRole.COMPARISON_THEN,
            kind=MediaKind.ARCHIVAL_PHOTO,
            valid_from="1998-01-01",
            valid_to="1998-12-31",
            date_precision=DatePrecision.YEAR,
        )

    assert called is False


@pytest.mark.django_db
def test_comparison_then_ingestion_rejects_country_scope_before_network(monkeypatch):
    from apps.countries.models import Country, Currency

    Country.objects.create(iso2="JP", iso3="JPN", name="Japan")
    Currency.objects.create(code="JPY", name="Japanese yen", minor_units=0)
    called = False

    def unexpected_search(self, query, limit):
        nonlocal called
        called = True
        return ()

    monkeypatch.setattr(
        "apps.media.management.commands.ingest_media_candidates.WikimediaCommonsClient.search",
        unexpected_search,
    )

    with pytest.raises(CommandError, match="countryless"):
        call_command(
            "ingest_media_candidates",
            source="wikimedia",
            query="Japan 1998 street",
            role=MediaRole.COMPARISON_THEN,
            kind=MediaKind.ARCHIVAL_PHOTO,
            country="JP",
            currency="JPY",
            valid_from="1998-01-01",
            valid_to="1998-12-31",
            date_precision=DatePrecision.YEAR,
        )

    assert called is False


@pytest.mark.django_db
def test_historical_ingestion_rejects_non_iso_date_before_network(monkeypatch):
    called = False

    def unexpected_search(self, query, limit):
        nonlocal called
        called = True
        return ()

    monkeypatch.setattr(
        "apps.media.management.commands.ingest_media_candidates.WikimediaCommonsClient.search",
        unexpected_search,
    )

    with pytest.raises(CommandError, match="YYYY-MM-DD"):
        call_command(
            "ingest_media_candidates",
            source="wikimedia",
            query="Japan 1998 street",
            role=MediaRole.HISTORICAL_TIMELINE,
            kind=MediaKind.ARCHIVAL_PHOTO,
            valid_from="01-01-1998",
            date_precision=DatePrecision.YEAR,
        )

    assert called is False


@pytest.mark.django_db
def test_historical_ingestion_rejects_invalid_temporal_scope_before_network(monkeypatch):
    called = False

    def unexpected_search(self, query, limit):
        nonlocal called
        called = True
        return ()

    monkeypatch.setattr(
        "apps.media.management.commands.ingest_media_candidates.WikimediaCommonsClient.search",
        unexpected_search,
    )

    with pytest.raises(CommandError, match="cannot end before"):
        call_command(
            "ingest_media_candidates",
            source="wikimedia",
            query="Japan 1998 street",
            role=MediaRole.HISTORICAL_TIMELINE,
            kind=MediaKind.ARCHIVAL_PHOTO,
            valid_from="1999-01-01",
            valid_to="1998-12-31",
            date_precision=DatePrecision.RANGE,
        )

    assert called is False


@pytest.mark.django_db
def test_comparison_then_ingestion_persists_currency_and_reviewed_temporal_scope(monkeypatch):
    from apps.countries.models import Currency

    Currency.objects.create(code="JPY", name="Japanese yen", minor_units=0)
    monkeypatch.setattr(
        "apps.media.management.commands.ingest_media_candidates.WikimediaCommonsClient.search",
        lambda self, query, limit: (
            MediaCandidate(
                source_kind=MediaSourceKind.WIKIMEDIA_COMMONS,
                external_id="jpy-1998-archive",
                title="Tokyo in 1998",
                source_name="Wikimedia Commons",
                source_url="https://commons.wikimedia.org/wiki/File:Tokyo_1998.jpg",
                source_media_url="https://upload.wikimedia.org/tokyo-1998.jpg",
                creator="Archive photographer",
                licence_id="CC BY-SA 4.0",
                rights_statement="CC BY-SA 4.0",
                attribution_text="Archive photographer · CC BY-SA 4.0",
            ),
        ),
    )

    call_command(
        "ingest_media_candidates",
        source="wikimedia",
        query="Tokyo 1998 street",
        role=MediaRole.COMPARISON_THEN,
        kind=MediaKind.ARCHIVAL_PHOTO,
        currency="JPY",
        valid_from="1998-01-01",
        valid_to="1998-12-31",
        date_precision=DatePrecision.YEAR,
        limit=1,
    )

    from apps.media.models import MediaAsset

    asset = MediaAsset.objects.get(external_id="jpy-1998-archive")
    assert asset.currency.code == "JPY"
    assert asset.valid_from == date(1998, 1, 1)
    assert asset.valid_to == date(1998, 12, 31)
    assert asset.date_precision == DatePrecision.YEAR
    assert asset.status == MediaStatus.NEEDS_REVIEW
