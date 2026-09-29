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
from apps.media.curated import (
    CURATED_MEDIA,
    CuratedMediaSpec,
    get_curated_media_spec,
    validate_curated_media_spec,
)
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
def curated_spec(monkeypatch):
    spec = CuratedMediaSpec(
        slug="test-finland-hero",
        country_code="FI",
        currency_code="",
        city="Helsinki",
        valid_from=date(2026, 5, 24),
        valid_to=date(2026, 5, 24),
        date_precision=DatePrecision.EXACT_DAY,
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


@pytest.fixture
def yen(db):
    return Currency.objects.create(code="JPY", name="Japanese yen", symbol="¥")


@pytest.fixture
def comparison_curated_spec(monkeypatch):
    spec = CuratedMediaSpec(
        slug="test-jpy-1998-archive",
        country_code="",
        currency_code="JPY",
        city="",
        valid_from=date(1998, 1, 1),
        valid_to=date(1998, 12, 31),
        date_precision=DatePrecision.YEAR,
        role=MediaRole.COMPARISON_THEN,
        kind=MediaKind.ARCHIVAL_PHOTO,
        source_kind=MediaSourceKind.WIKIMEDIA_COMMONS,
        external_id="commons:test-jpy-1998-archive",
        title="Japanese yen archive",
        alt_text="A sourced archival image associated with Japanese yen in 1998.",
        caption="Archival Japanese yen reference material, 1998 scope.",
        source_name="Wikimedia Commons",
        source_url="https://commons.wikimedia.org/wiki/File:Test_JPY_1998.png",
        source_media_url="https://upload.wikimedia.org/wikipedia/commons/a/ab/Test_JPY_1998.png",
        creator="Archive creator",
        licence_id="CC BY-SA 4.0",
        licence_url="https://creativecommons.org/licenses/by-sa/4.0/",
        rights_statement="Creative Commons Attribution-ShareAlike 4.0 International",
        attribution_text="Archive creator · CC BY-SA 4.0",
        expected_width=64,
        expected_height=48,
    )
    monkeypatch.setitem(CURATED_MEDIA, spec.slug, spec)
    return spec


def test_japan_hero_manifest_matches_reviewed_source_contract() -> None:
    spec = get_curated_media_spec("japan-tokyo-street-night-2019")

    assert spec.country_code == "JP"
    assert spec.currency_code == ""
    assert spec.city == "Tokyo"
    assert spec.role == MediaRole.COUNTRY_HERO
    assert spec.kind == MediaKind.CONTEMPORARY_PHOTO
    assert spec.source_kind == MediaSourceKind.WIKIMEDIA_COMMONS
    assert spec.valid_from == date(2019, 11, 29)
    assert spec.valid_to == date(2019, 11, 29)
    assert spec.date_precision == DatePrecision.EXACT_DAY
    assert spec.expected_width == 4000
    assert spec.expected_height == 3000
    assert spec.creator == "Another Believer"
    assert spec.licence_id == "CC BY-SA 4.0"
    assert spec.source_media_url.startswith("https://upload.wikimedia.org/")


@pytest.mark.django_db
def test_japan_hero_manifest_creates_country_scoped_review_candidate() -> None:
    japan = Country.objects.create(iso2="JP", iso3="JPN", name="Japan")

    call_command(
        "ingest_curated_media",
        slug="japan-tokyo-street-night-2019",
        metadata_only=True,
    )

    asset = MediaAsset.objects.get(external_id="commons:Tokyo_street_at_night,_2019_-_771.jpg")
    assert asset.status == MediaStatus.NEEDS_REVIEW
    assert not asset.storage_file
    assert asset.country == japan
    assert asset.currency is None
    assert asset.role == MediaRole.COUNTRY_HERO
    assert asset.kind == MediaKind.CONTEMPORARY_PHOTO
    assert asset.valid_from == date(2019, 11, 29)
    assert asset.valid_to == date(2019, 11, 29)
    assert asset.date_precision == DatePrecision.EXACT_DAY


def test_japan_everyday_value_manifest_matches_reviewed_source_contract() -> None:
    spec = get_curated_media_spec("japan-shoyu-ramen-everyday-value-2025")

    assert spec.country_code == "JP"
    assert spec.currency_code == ""
    assert spec.city == ""
    assert spec.role == MediaRole.EVERYDAY_VALUE
    assert spec.kind == MediaKind.CONTEMPORARY_PHOTO
    assert spec.source_kind == MediaSourceKind.WIKIMEDIA_COMMONS
    assert spec.valid_from == date(2025, 5, 11)
    assert spec.valid_to == date(2025, 5, 11)
    assert spec.date_precision == DatePrecision.EXACT_DAY
    assert spec.expected_width == 3299
    assert spec.expected_height == 2474
    assert spec.creator == "Quercus acuta"
    assert spec.licence_id == "CC BY-SA 4.0"


@pytest.mark.django_db
def test_japan_everyday_value_manifest_creates_country_scoped_review_candidate() -> None:
    japan = Country.objects.create(iso2="JP", iso3="JPN", name="Japan")

    call_command(
        "ingest_curated_media",
        slug="japan-shoyu-ramen-everyday-value-2025",
        metadata_only=True,
    )

    asset = MediaAsset.objects.get(external_id="commons:shoyu-ramen-tokyo-ramen-01-2025")
    assert asset.status == MediaStatus.NEEDS_REVIEW
    assert not asset.storage_file
    assert asset.country == japan
    assert asset.currency is None
    assert asset.city == ""
    assert asset.role == MediaRole.EVERYDAY_VALUE
    assert asset.kind == MediaKind.CONTEMPORARY_PHOTO
    assert asset.valid_from == date(2025, 5, 11)
    assert asset.valid_to == date(2025, 5, 11)


def test_japan_payment_culture_manifest_matches_reviewed_source_contract() -> None:
    spec = get_curated_media_spec("japan-suica-vending-payment-2020")

    assert spec.country_code == "JP"
    assert spec.currency_code == ""
    assert spec.city == ""
    assert spec.role == MediaRole.PAYMENT_CULTURE
    assert spec.kind == MediaKind.CONTEMPORARY_PHOTO
    assert spec.source_kind == MediaSourceKind.WIKIMEDIA_COMMONS
    assert spec.valid_from == date(2020, 11, 14)
    assert spec.valid_to == date(2020, 11, 14)
    assert spec.date_precision == DatePrecision.EXACT_DAY
    assert spec.expected_width == 6240
    assert spec.expected_height == 4160
    assert spec.creator == "Real Estate Japan / Scott Kouchi"
    assert spec.licence_id == "CC BY 2.0"
    assert spec.source_media_url.startswith("https://upload.wikimedia.org/")


@pytest.mark.django_db
def test_japan_payment_culture_manifest_creates_country_scoped_review_candidate() -> None:
    japan = Country.objects.create(iso2="JP", iso3="JPN", name="Japan")

    call_command(
        "ingest_curated_media",
        slug="japan-suica-vending-payment-2020",
        metadata_only=True,
    )

    asset = MediaAsset.objects.get(
        external_id="commons:Suica_payment_on_vending_machine_50607340823"
    )
    assert asset.status == MediaStatus.NEEDS_REVIEW
    assert not asset.storage_file
    assert asset.country == japan
    assert asset.currency is None
    assert asset.city == ""
    assert asset.role == MediaRole.PAYMENT_CULTURE
    assert asset.kind == MediaKind.CONTEMPORARY_PHOTO
    assert asset.valid_from == date(2020, 11, 14)
    assert asset.valid_to == date(2020, 11, 14)


def test_japan_local_detail_manifest_matches_reviewed_source_contract() -> None:
    spec = get_curated_media_spec("japan-tokyo-metro-local-detail-2021")

    assert spec.country_code == "JP"
    assert spec.currency_code == ""
    assert spec.city == ""
    assert spec.role == MediaRole.LOCAL_DETAIL
    assert spec.kind == MediaKind.CONTEMPORARY_PHOTO
    assert spec.source_kind == MediaSourceKind.WIKIMEDIA_COMMONS
    assert spec.valid_from == date(2021, 4, 20)
    assert spec.valid_to == date(2021, 4, 20)
    assert spec.date_precision == DatePrecision.EXACT_DAY
    assert spec.expected_width == 5004
    assert spec.expected_height == 3336
    assert spec.creator == "MaedaAkihiko"
    assert spec.licence_id == "CC BY-SA 4.0"
    assert spec.source_media_url.startswith("https://upload.wikimedia.org/")


@pytest.mark.django_db
def test_japan_local_detail_manifest_creates_country_scoped_review_candidate() -> None:
    japan = Country.objects.create(iso2="JP", iso3="JPN", name="Japan")

    call_command(
        "ingest_curated_media",
        slug="japan-tokyo-metro-local-detail-2021",
        metadata_only=True,
    )

    asset = MediaAsset.objects.get(
        external_id="commons:Tokyo-Metro-13000-Digital_signage-On_the_door.jpg"
    )
    assert asset.status == MediaStatus.NEEDS_REVIEW
    assert not asset.storage_file
    assert asset.country == japan
    assert asset.currency is None
    assert asset.city == ""
    assert asset.role == MediaRole.LOCAL_DETAIL
    assert asset.kind == MediaKind.CONTEMPORARY_PHOTO
    assert asset.valid_from == date(2021, 4, 20)
    assert asset.valid_to == date(2021, 4, 20)



def test_jpy_historical_manifest_matches_reviewed_source_contract() -> None:
    spec = get_curated_media_spec("jpy-series-d-1000-yen-1984-2007")

    assert spec.country_code == ""
    assert spec.currency_code == "JPY"
    assert spec.role == MediaRole.COMPARISON_THEN
    assert spec.kind == MediaKind.HERITAGE_OBJECT
    assert spec.source_kind == MediaSourceKind.WIKIMEDIA_COMMONS
    assert spec.valid_from == date(1984, 11, 1)
    assert spec.valid_to == date(2007, 4, 2)
    assert spec.date_precision == DatePrecision.RANGE
    assert spec.expected_width == 900
    assert spec.expected_height == 456
    assert spec.source_media_url.startswith("https://upload.wikimedia.org/")


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
    assert asset.country == finland
    assert asset.currency is None
    assert asset.valid_from == date(2026, 5, 24)
    assert asset.valid_to == date(2026, 5, 24)
    assert asset.date_precision == DatePrecision.EXACT_DAY
    assert asset.generated_by_ai is False


@pytest.mark.django_db
def test_curated_comparison_metadata_is_countryless_currency_and_time_scoped(
    yen,
    comparison_curated_spec,
) -> None:
    call_command(
        "ingest_curated_media",
        slug=comparison_curated_spec.slug,
        metadata_only=True,
    )

    asset = MediaAsset.objects.get()
    assert asset.role == MediaRole.COMPARISON_THEN
    assert asset.country is None
    assert asset.currency == yen
    assert asset.valid_from == date(1998, 1, 1)
    assert asset.valid_to == date(1998, 12, 31)
    assert asset.date_precision == DatePrecision.YEAR
    assert not asset.storage_file
    assert asset.status == MediaStatus.NEEDS_REVIEW


def test_curated_country_hero_manifest_requires_country_scope(curated_spec) -> None:
    missing_country = replace(curated_spec, country_code="")
    currency_scoped = replace(curated_spec, currency_code="EUR")

    with pytest.raises(ValueError, match="requires country_code"):
        validate_curated_media_spec(missing_country)

    with pytest.raises(ValueError, match="currency-neutral"):
        validate_curated_media_spec(currency_scoped)


def test_curated_country_hero_manifest_rejects_generated_media(curated_spec) -> None:
    invalid = replace(
        curated_spec,
        kind=MediaKind.GENERATED_ILLUSTRATION,
        source_kind=MediaSourceKind.GENERATED,
    )

    with pytest.raises(ValueError, match="sourced contemporary photography"):
        validate_curated_media_spec(invalid)


def test_curated_destination_supporting_manifest_requires_country_scope(
    curated_spec,
) -> None:
    missing_country = replace(
        curated_spec,
        role=MediaRole.EVERYDAY_VALUE,
        country_code="",
        city="",
    )
    currency_scoped = replace(
        curated_spec,
        role=MediaRole.EVERYDAY_VALUE,
        currency_code="JPY",
    )
    generated = replace(
        curated_spec,
        role=MediaRole.EVERYDAY_VALUE,
        kind=MediaKind.GENERATED_ILLUSTRATION,
        source_kind=MediaSourceKind.GENERATED,
    )

    with pytest.raises(ValueError, match="requires country_code"):
        validate_curated_media_spec(missing_country)

    with pytest.raises(ValueError, match="currency-neutral"):
        validate_curated_media_spec(currency_scoped)

    with pytest.raises(ValueError, match="requires a sourced asset"):
        validate_curated_media_spec(generated)


def test_curated_comparison_manifest_rejects_country_scope(comparison_curated_spec) -> None:
    invalid = replace(comparison_curated_spec, country_code="JP")

    with pytest.raises(ValueError, match="must be countryless"):
        validate_curated_media_spec(invalid)


def test_curated_comparison_manifest_rejects_generated_evidence(
    comparison_curated_spec,
) -> None:
    invalid = replace(
        comparison_curated_spec,
        kind=MediaKind.GENERATED_ILLUSTRATION,
        source_kind=MediaSourceKind.GENERATED,
    )

    with pytest.raises(ValueError, match="historical evidence kind"):
        validate_curated_media_spec(invalid)


@pytest.mark.django_db
def test_curated_ingest_rejects_unknown_currency_before_network(
    comparison_curated_spec,
    monkeypatch,
) -> None:
    invalid = replace(comparison_curated_spec, currency_code="ZZZ")
    monkeypatch.setitem(CURATED_MEDIA, invalid.slug, invalid)

    def unexpected_download(*args, **kwargs):
        raise AssertionError("reference-data failure must happen before network I/O")

    monkeypatch.setattr(
        "apps.media.management.commands.ingest_curated_media.download_media_bytes",
        unexpected_download,
    )

    with pytest.raises(CommandError, match="requires currency ZZZ"):
        call_command("ingest_curated_media", slug=invalid.slug)

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
