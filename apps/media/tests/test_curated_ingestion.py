from __future__ import annotations

import io
import tempfile
from dataclasses import replace
from datetime import date
from email.message import Message
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings
from PIL import Image

from apps.countries.models import Country, Currency
from apps.media.acquisition import DownloadedMedia, MediaAcquisitionError, download_media_bytes
from apps.media.curated import CURATED_MEDIA, JPY_AKIHABARA_1995_THEN, CuratedMediaSpec
from apps.media.models import (
    DatePrecision,
    MediaAsset,
    MediaKind,
    MediaRole,
    MediaSourceKind,
    MediaStatus,
)
from apps.media.services import approve_media_asset


class _Response:
    def __init__(
        self,
        data: bytes,
        *,
        url: str,
        content_type: str = "image/png",
        content_length: str | None = None,
    ):
        self._data = data
        self._url = url
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        if content_length is not None:
            self.headers["Content-Length"] = content_length

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def geturl(self) -> str:
        return self._url

    def read(self, limit: int) -> bytes:
        return self._data[:limit]


def _png(*, size=(64, 48), color=(30, 60, 90)) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", size, color).save(output, format="PNG")
    return output.getvalue()


@pytest.fixture
def media_root():
    with tempfile.TemporaryDirectory() as directory:
        with override_settings(MEDIA_ROOT=Path(directory)):
            yield Path(directory)


@pytest.fixture
def finland(db):
    return Country.objects.create(iso2="FI", iso3="FIN", name="Finland")


@pytest.fixture
def yen(db):
    return Currency.objects.create(code="JPY", name="Japanese yen", symbol="¥", minor_units=0)


@pytest.fixture
def curated_spec(monkeypatch):
    spec = CuratedMediaSpec(
        slug="test-finland-hero",
        country_code="FI",
        city="Helsinki",
        role=MediaRole.COUNTRY_HERO,
        kind=MediaKind.CONTEMPORARY_PHOTO,
        source_kind=MediaSourceKind.WIKIMEDIA_COMMONS,
        external_id="commons:test-finland-hero",
        title="Helsinki tram",
        alt_text="A Helsinki tram on a central city street.",
        caption="Helsinki tram in May 2026.",
        source_name="Wikimedia Commons",
        source_url="https://commons.wikimedia.org/wiki/File:Test_Helsinki.png",
        source_media_url="https://upload.wikimedia.org/wikipedia/commons/a/ab/Test_Helsinki.png",
        creator="Creator",
        licence_id="CC BY-SA 4.0",
        licence_url="https://creativecommons.org/licenses/by-sa/4.0/",
        rights_statement="Creative Commons Attribution-ShareAlike 4.0 International",
        attribution_text="Creator · CC BY-SA 4.0",
        expected_width=64,
        expected_height=48,
    )
    monkeypatch.setitem(CURATED_MEDIA, spec.slug, spec)
    return spec


def test_download_media_bytes_accepts_bounded_approved_raster(monkeypatch) -> None:
    url = "https://upload.wikimedia.org/wikipedia/commons/a/ab/Test.png"
    payload = _png()
    monkeypatch.setattr(
        "apps.media.acquisition.urlopen",
        lambda request, timeout: _Response(
            payload,
            url=url,
            content_type="image/png",
            content_length=str(len(payload)),
        ),
    )

    downloaded = download_media_bytes(url, timeout_seconds=2)

    assert downloaded.data == payload
    assert downloaded.filename == "Test.png"
    assert downloaded.content_type == "image/png"
    assert downloaded.final_url == url


@pytest.mark.parametrize(
    "url",
    [
        "http://upload.wikimedia.org/test.jpg",
        "https://example.org/test.jpg",
        "https://user:secret@upload.wikimedia.org/test.jpg",
        "https://upload.wikimedia.org/test.jpg?token=secret",
        "https://upload.wikimedia.org/test.svg",
    ],
)
def test_download_media_bytes_rejects_unapproved_url_shapes(url: str) -> None:
    with pytest.raises(MediaAcquisitionError):
        download_media_bytes(url)


def test_download_media_bytes_rejects_redirect_to_unapproved_host(monkeypatch) -> None:
    source = "https://upload.wikimedia.org/wikipedia/commons/a/ab/Test.png"
    monkeypatch.setattr(
        "apps.media.acquisition.urlopen",
        lambda request, timeout: _Response(
            _png(),
            url="https://evil.example/Test.png",
        ),
    )

    with pytest.raises(MediaAcquisitionError, match="approved host"):
        download_media_bytes(source)


def test_download_media_bytes_rejects_oversized_or_wrong_mime(monkeypatch) -> None:
    url = "https://upload.wikimedia.org/wikipedia/commons/a/ab/Test.png"
    monkeypatch.setattr(
        "apps.media.acquisition.urlopen",
        lambda request, timeout: _Response(
            b"x",
            url=url,
            content_type="text/html",
        ),
    )
    with pytest.raises(MediaAcquisitionError, match="content type"):
        download_media_bytes(url)

    monkeypatch.setattr(
        "apps.media.acquisition.urlopen",
        lambda request, timeout: _Response(
            b"x",
            url=url,
            content_length="101",
        ),
    )
    with pytest.raises(MediaAcquisitionError, match="byte-size"):
        download_media_bytes(url, max_bytes=100)


@pytest.mark.django_db
def test_curated_ingest_dry_run_has_no_network_or_database_effect(
    finland,
    curated_spec,
    monkeypatch,
) -> None:
    def unexpected_download(*args, **kwargs):
        raise AssertionError("dry-run must not access the network")

    monkeypatch.setattr(
        "apps.media.management.commands.ingest_curated_media.download_media_bytes",
        unexpected_download,
    )

    call_command("ingest_curated_media", slug=curated_spec.slug, dry_run=True)

    assert MediaAsset.objects.count() == 0


@pytest.mark.django_db
def test_curated_metadata_only_creates_review_candidate_without_bytes(
    finland,
    curated_spec,
) -> None:
    call_command("ingest_curated_media", slug=curated_spec.slug, metadata_only=True)

    asset = MediaAsset.objects.get()
    assert asset.status == MediaStatus.NEEDS_REVIEW
    assert not asset.storage_file
    assert asset.city == "Helsinki"
    assert asset.alt_text == curated_spec.alt_text
    assert asset.caption == curated_spec.caption
    assert asset.generated_by_ai is False


@pytest.mark.django_db
def test_curated_archival_metadata_is_currency_and_year_scoped(yen) -> None:
    call_command(
        "ingest_curated_media",
        slug=JPY_AKIHABARA_1995_THEN.slug,
        metadata_only=True,
    )

    asset = MediaAsset.objects.get()
    assert asset.status == MediaStatus.NEEDS_REVIEW
    assert asset.role == MediaRole.COMPARISON_THEN
    assert asset.kind == MediaKind.ARCHIVAL_PHOTO
    assert asset.country is None
    assert asset.currency == yen
    assert asset.city == "Tokyo"
    assert asset.valid_from == date(1995, 1, 1)
    assert asset.valid_to == date(1995, 12, 31)
    assert asset.date_precision == DatePrecision.YEAR
    assert asset.width == 930
    assert asset.height == 622
    assert asset.licence_id == "CC BY-SA 2.0"
    assert not asset.storage_file


@pytest.mark.django_db
def test_curated_archival_ingest_requires_seeded_currency_before_network(monkeypatch) -> None:
    def unexpected_download(*args, **kwargs):
        raise AssertionError("missing reference data must fail before network access")

    monkeypatch.setattr(
        "apps.media.management.commands.ingest_curated_media.download_media_bytes",
        unexpected_download,
    )

    with pytest.raises(CommandError, match="requires currency JPY"):
        call_command("ingest_curated_media", slug=JPY_AKIHABARA_1995_THEN.slug)

    assert not MediaAsset.objects.exists()


@pytest.mark.django_db
def test_curated_comparison_manifest_rejects_missing_temporal_scope(yen, monkeypatch) -> None:
    invalid = replace(
        JPY_AKIHABARA_1995_THEN,
        slug="test-jpy-archive-without-date",
        external_id="commons:test-jpy-archive-without-date",
        valid_from=None,
        valid_to=None,
        date_precision=DatePrecision.UNKNOWN,
    )
    monkeypatch.setitem(CURATED_MEDIA, invalid.slug, invalid)

    with pytest.raises(CommandError, match="requires explicit temporal scope"):
        call_command("ingest_curated_media", slug=invalid.slug, metadata_only=True)

    assert not MediaAsset.objects.exists()


@pytest.mark.django_db
def test_curated_ingest_attaches_sanitized_bytes_but_never_publishes(
    finland,
    curated_spec,
    media_root,
    monkeypatch,
) -> None:
    payload = _png()
    monkeypatch.setattr(
        "apps.media.management.commands.ingest_curated_media.download_media_bytes",
        lambda url: DownloadedMedia(
            data=payload,
            filename="Test_Helsinki.png",
            content_type="image/png",
            final_url=curated_spec.source_media_url,
        ),
    )

    call_command("ingest_curated_media", slug=curated_spec.slug)

    asset = MediaAsset.objects.get()
    assert asset.status == MediaStatus.NEEDS_REVIEW
    assert asset.storage_file
    assert asset.width == 64
    assert asset.height == 48
    assert len(asset.content_hash) == 64
    assert asset.source_url == curated_spec.source_url
    assert asset.licence_id == "CC BY-SA 4.0"
    assert asset.published_at is None


@pytest.mark.django_db
def test_curated_ingest_is_idempotent_once_managed_bytes_exist(
    finland,
    curated_spec,
    media_root,
    monkeypatch,
) -> None:
    payload = _png()
    calls = 0

    def download(url):
        nonlocal calls
        calls += 1
        return DownloadedMedia(
            data=payload,
            filename="Test_Helsinki.png",
            content_type="image/png",
            final_url=curated_spec.source_media_url,
        )

    monkeypatch.setattr(
        "apps.media.management.commands.ingest_curated_media.download_media_bytes",
        download,
    )

    call_command("ingest_curated_media", slug=curated_spec.slug)
    call_command("ingest_curated_media", slug=curated_spec.slug)

    assert calls == 1
    assert MediaAsset.objects.count() == 1


@pytest.mark.django_db
def test_curated_ingest_never_mutates_reviewed_protected_media(
    finland,
    curated_spec,
    media_root,
    monkeypatch,
) -> None:
    payload = _png()
    monkeypatch.setattr(
        "apps.media.management.commands.ingest_curated_media.download_media_bytes",
        lambda url: DownloadedMedia(
            data=payload,
            filename="Test_Helsinki.png",
            content_type="image/png",
            final_url=curated_spec.source_media_url,
        ),
    )
    call_command("ingest_curated_media", slug=curated_spec.slug)
    asset = MediaAsset.objects.get()
    approve_media_asset(asset)
    original_title = asset.title

    monkeypatch.setattr(
        "apps.media.management.commands.ingest_curated_media.download_media_bytes",
        lambda url: (_ for _ in ()).throw(AssertionError("protected media must not download")),
    )
    call_command("ingest_curated_media", slug=curated_spec.slug)

    asset.refresh_from_db()
    assert asset.status == MediaStatus.APPROVED
    assert asset.title == original_title


@pytest.mark.django_db
def test_curated_ingest_preserves_rejected_editorial_decision(
    finland,
    curated_spec,
    media_root,
    monkeypatch,
) -> None:
    payload = _png()
    monkeypatch.setattr(
        "apps.media.management.commands.ingest_curated_media.download_media_bytes",
        lambda url: DownloadedMedia(
            data=payload,
            filename="Test_Helsinki.png",
            content_type="image/png",
            final_url=curated_spec.source_media_url,
        ),
    )
    call_command("ingest_curated_media", slug=curated_spec.slug)
    asset = MediaAsset.objects.get()
    asset.status = MediaStatus.REJECTED
    asset.save(update_fields=("status", "updated_at"))

    monkeypatch.setattr(
        "apps.media.management.commands.ingest_curated_media.download_media_bytes",
        lambda url: (_ for _ in ()).throw(AssertionError("rejected media must remain protected")),
    )
    call_command("ingest_curated_media", slug=curated_spec.slug)

    asset.refresh_from_db()
    assert asset.status == MediaStatus.REJECTED


@pytest.mark.django_db
def test_curated_ingest_rejects_upstream_dimension_drift(
    finland,
    curated_spec,
    media_root,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "apps.media.management.commands.ingest_curated_media.download_media_bytes",
        lambda url: DownloadedMedia(
            data=_png(size=(32, 24)),
            filename="Test_Helsinki.png",
            content_type="image/png",
            final_url=curated_spec.source_media_url,
        ),
    )

    with pytest.raises(CommandError, match="dimensions changed"):
        call_command("ingest_curated_media", slug=curated_spec.slug)

    asset = MediaAsset.objects.get()
    assert not asset.storage_file
    assert asset.status == MediaStatus.NEEDS_REVIEW
