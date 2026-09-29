from __future__ import annotations

from datetime import date
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.countries.models import Currency
from apps.media.models import (
    DatePrecision,
    MediaAsset,
    MediaKind,
    MediaRole,
    MediaSourceKind,
    MediaStatus,
)
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
        valid_from=date(1990, 1, 1),
        valid_to=date(1999, 12, 31),
        date_precision=DatePrecision.DECADE,
        limit=1,
        stdout=stdout,
    )

    asset = MediaAsset.objects.get()
    assert asset.status == MediaStatus.NEEDS_REVIEW
    assert asset.valid_from == date(1990, 1, 1)
    assert asset.valid_to == date(1999, 12, 31)
    assert asset.date_precision == DatePrecision.DECADE
    assert not asset.storage_file
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
            valid_from=date(1950, 1, 1),
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
def test_comparison_then_ingestion_preserves_currency_and_temporal_scope(monkeypatch):
    jpy = Currency.objects.create(
        code="JPY",
        name="Japanese yen",
        symbol="¥",
        minor_units=0,
    )

    monkeypatch.setattr(
        "apps.media.management.commands.ingest_media_candidates.WikimediaCommonsClient.search",
        lambda self, query, limit: (
            MediaCandidate(
                source_kind=MediaSourceKind.WIKIMEDIA_COMMONS,
                external_id="jpy-1998",
                title="Tokyo 1998 archive",
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
        valid_from=date(1998, 1, 1),
        valid_to=date(1998, 12, 31),
        date_precision=DatePrecision.YEAR,
        limit=1,
    )

    asset = MediaAsset.objects.get(external_id="jpy-1998")
    assert asset.currency_id == jpy.pk
    assert asset.valid_from == date(1998, 1, 1)
    assert asset.valid_to == date(1998, 12, 31)
    assert asset.date_precision == DatePrecision.YEAR
    assert asset.status == MediaStatus.NEEDS_REVIEW


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        (
            {
                "role": MediaRole.COMPARISON_THEN,
                "currency": None,
                "valid_from": date(1998, 1, 1),
                "date_precision": DatePrecision.YEAR,
            },
            "requires --currency",
        ),
        (
            {
                "role": MediaRole.HISTORICAL_TIMELINE,
                "valid_from": None,
                "date_precision": DatePrecision.YEAR,
            },
            "requires --valid-from or --valid-to",
        ),
        (
            {
                "role": MediaRole.HISTORICAL_TIMELINE,
                "valid_from": date(1999, 1, 1),
                "valid_to": date(1998, 1, 1),
                "date_precision": DatePrecision.RANGE,
            },
            "must not be after",
        ),
    ],
)
def test_historical_ingestion_rejects_invalid_scope_before_network(
    monkeypatch,
    kwargs,
    message,
):
    called = False

    def unexpected_search(self, query, limit):
        nonlocal called
        called = True
        return ()

    monkeypatch.setattr(
        "apps.media.management.commands.ingest_media_candidates.WikimediaCommonsClient.search",
        unexpected_search,
    )
    options = {
        "source": "wikimedia",
        "query": "archive",
        "kind": MediaKind.ARCHIVAL_PHOTO,
        **kwargs,
    }

    with pytest.raises(CommandError, match=message):
        call_command("ingest_media_candidates", **options)

    assert called is False
