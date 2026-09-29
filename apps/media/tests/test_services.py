from __future__ import annotations

import io
import tempfile
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from django.core.files.storage import default_storage
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from PIL import Image

from apps.countries.models import Country, Currency
from apps.media.models import (
    DatePrecision,
    MediaAsset,
    MediaKind,
    MediaRole,
    MediaSourceKind,
    MediaStatus,
)
from apps.media.presentation import select_media_for_display
from apps.media.services import (
    DuplicateMediaContentError,
    MediaPublicationError,
    approve_media_asset,
    attach_media_bytes,
    create_responsive_derivative,
    publish_media_asset,
    select_published_media,
    select_published_media_for_roles,
    upsert_media_candidates,
)
from apps.media.sources.base import MediaCandidate


def _png_bytes(color: tuple[int, int, int], *, size=(32, 24)) -> bytes:
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
def euro(db):
    return Currency.objects.create(code="EUR", name="Euro", symbol="€")


def _sourced_asset(*, title: str, role: str, country=None, external_id="") -> MediaAsset:
    return MediaAsset.objects.create(
        kind=MediaKind.ARCHIVAL_PHOTO,
        source_kind=MediaSourceKind.WIKIMEDIA_COMMONS,
        role=role,
        country=country,
        title=title,
        alt_text=f"{title} editorial image",
        source_name="Wikimedia Commons",
        source_url="https://commons.wikimedia.org/wiki/File:Example.jpg",
        source_media_url="https://upload.wikimedia.org/example.jpg",
        external_id=external_id,
        creator="Example Creator",
        licence_id="CC BY-SA 4.0",
        licence_url="https://creativecommons.org/licenses/by-sa/4.0/",
        rights_statement="CC BY-SA 4.0",
        attribution_text="Example Creator · CC BY-SA 4.0",
        valid_from=date(1990, 1, 1),
        valid_to=date(1999, 12, 31),
        date_precision=DatePrecision.DECADE,
    )


def _publish_sourced(asset: MediaAsset, *, color=(10, 20, 30)) -> MediaAsset:
    attach_media_bytes(asset, _png_bytes(color), filename="source.png")
    approve_media_asset(asset)
    publish_media_asset(asset)
    return asset


@pytest.mark.django_db
def test_candidate_ingestion_is_unpublished_idempotent_and_dry_runnable(finland):
    candidate = MediaCandidate(
        source_kind=MediaSourceKind.WIKIMEDIA_COMMONS,
        external_id="commons-1",
        title="Candidate",
        source_name="Wikimedia Commons",
        source_url="https://commons.wikimedia.org/wiki/File:Candidate.jpg",
        source_media_url="https://upload.wikimedia.org/candidate.jpg",
        creator="Creator",
        licence_id="CC0",
        rights_statement="CC0",
        attribution_text="Creator · CC0",
        retrieved_at=datetime(2026, 9, 21, tzinfo=UTC),
    )

    dry = upsert_media_candidates(
        (candidate,),
        role=MediaRole.STORY_COVER,
        kind=MediaKind.ARTWORK,
        country=finland,
        dry_run=True,
    )
    assert dry.created == 1
    assert not MediaAsset.objects.exists()

    applied = upsert_media_candidates(
        (candidate,),
        role=MediaRole.STORY_COVER,
        kind=MediaKind.ARTWORK,
        country=finland,
    )
    assert applied.created == 1
    asset = MediaAsset.objects.get()
    assert asset.status == MediaStatus.NEEDS_REVIEW
    assert asset.published_at is None

    repeated = upsert_media_candidates(
        (candidate,),
        role=MediaRole.STORY_COVER,
        kind=MediaKind.ARTWORK,
        country=finland,
    )
    assert repeated.unchanged == 1
    assert MediaAsset.objects.count() == 1


@pytest.mark.django_db
def test_unclear_rights_candidate_cannot_be_approved(media_root):
    candidate = MediaCandidate(
        source_kind=MediaSourceKind.EUROPEANA,
        external_id="eu-unclear",
        title="Unclear",
        source_name="Archive",
        source_url="https://www.europeana.eu/item/1/unclear",
        source_media_url="https://example.org/image.jpg",
    )
    upsert_media_candidates(
        (candidate,),
        role=MediaRole.HISTORICAL_TIMELINE,
        kind=MediaKind.ARCHIVAL_PHOTO,
    )
    asset = MediaAsset.objects.get()
    asset.alt_text = "Historical archive image"
    asset.valid_from = date(1950, 1, 1)
    asset.date_precision = DatePrecision.DECADE
    asset.save()
    attach_media_bytes(asset, _png_bytes((1, 2, 3)), filename="archive.png")

    with pytest.raises(MediaPublicationError, match="licence or rights"):
        approve_media_asset(asset)

    asset.refresh_from_db()
    assert asset.status == MediaStatus.NEEDS_REVIEW


@pytest.mark.django_db
def test_attached_bytes_are_hashed_stored_outside_database_and_deduplicated(media_root):
    first = _sourced_asset(title="First", role=MediaRole.STORY_COVER)
    payload = _png_bytes((20, 30, 40))
    attach_media_bytes(first, payload, filename="first.png")

    assert len(first.content_hash) == 64
    assert first.storage_file.name.startswith("sourced/")
    assert default_storage.exists(first.storage_file.name)

    second = _sourced_asset(title="Second", role=MediaRole.STORY_COVER)
    with pytest.raises(DuplicateMediaContentError) as exc:
        attach_media_bytes(second, payload, filename="second.png")
    assert exc.value.existing_asset_id == first.pk


@pytest.mark.django_db
def test_sourced_media_requires_review_then_explicit_publish(media_root):
    asset = _sourced_asset(title="Reviewed", role=MediaRole.HISTORICAL_TIMELINE)
    attach_media_bytes(asset, _png_bytes((30, 40, 50)), filename="reviewed.png")

    approve_media_asset(asset)
    assert asset.status == MediaStatus.APPROVED
    assert asset.reviewed_at is not None
    assert asset.published_at is None

    publish_media_asset(asset)
    assert asset.status == MediaStatus.PUBLISHED
    assert asset.published_at is not None


@pytest.mark.django_db
def test_ai_historical_illustration_requires_authenticity_metadata(media_root):
    asset = MediaAsset.objects.create(
        kind=MediaKind.GENERATED_ILLUSTRATION,
        source_kind=MediaSourceKind.GENERATED,
        role=MediaRole.HISTORICAL_TIMELINE,
        title="Generated reconstruction",
        alt_text="Editorial illustration of a historical street scene",
        generated_by_ai=True,
        valid_from=date(1950, 1, 1),
        valid_to=date(1959, 12, 31),
        date_precision=DatePrecision.DECADE,
    )
    attach_media_bytes(asset, _png_bytes((40, 50, 60)), filename="generated.png")

    with pytest.raises(MediaPublicationError, match="authenticity metadata"):
        approve_media_asset(asset)

    asset.ai_label = "AI-generated editorial illustration · not an archival photograph"
    asset.generation_provider = "example-provider"
    asset.generation_model = "example-model"
    asset.prompt_version = "media-prompt:v1"
    asset.prompt_hash = "a" * 64
    asset.generated_at = datetime(2026, 9, 21, tzinfo=UTC)
    asset.save()
    approve_media_asset(asset)
    publish_media_asset(asset)

    assert asset.status == MediaStatus.PUBLISHED
    assert asset.ai_label.startswith("AI-generated")


@pytest.mark.django_db
def test_selector_prefers_relevant_real_media_over_ai_even_with_coarser_date(
    media_root,
    finland,
):
    sourced = _publish_sourced(
        _sourced_asset(
            title="Real archive",
            role=MediaRole.HISTORICAL_TIMELINE,
            country=finland,
        ),
        color=(50, 60, 70),
    )

    ai = MediaAsset.objects.create(
        kind=MediaKind.GENERATED_ILLUSTRATION,
        source_kind=MediaSourceKind.GENERATED,
        role=MediaRole.HISTORICAL_TIMELINE,
        country=finland,
        title="Exact AI reconstruction",
        alt_text="Generated editorial reconstruction",
        valid_from=date(1995, 6, 1),
        valid_to=date(1995, 6, 1),
        date_precision=DatePrecision.EXACT_DAY,
        generated_by_ai=True,
        ai_label="AI-generated editorial illustration · not an archival photograph",
        generation_provider="example-provider",
        generation_model="example-model",
        prompt_version="media-prompt:v1",
        prompt_hash="b" * 64,
        generated_at=datetime(2026, 9, 21, tzinfo=UTC),
    )
    attach_media_bytes(ai, _png_bytes((60, 70, 80)), filename="ai.png")
    approve_media_asset(ai)
    publish_media_asset(ai)

    selected = select_published_media(
        role=MediaRole.HISTORICAL_TIMELINE,
        country=finland,
        target_date=date(1995, 6, 1),
    )

    assert selected is not None
    assert selected.asset.pk == sourced.pk
    assert selected.authenticity_class == "sourced_media"
    assert selected.temporal_match_quality == "decade"


@pytest.mark.django_db
def test_missing_or_nonphotographic_country_media_renders_no_placeholder(media_root, finland):
    artwork = _sourced_asset(
        title="Country artwork",
        role=MediaRole.COUNTRY_HERO,
        country=finland,
    )
    artwork.kind = MediaKind.ARTWORK
    artwork.save(update_fields=("kind",))
    _publish_sourced(artwork, color=(44, 55, 66))

    assert (
        select_media_for_display(
            role=MediaRole.COUNTRY_HERO,
            country=finland,
        )
        is None
    )

    photo = _sourced_asset(
        title="Premium destination photograph",
        role=MediaRole.COUNTRY_HERO,
        country=finland,
    )
    photo.kind = MediaKind.CONTEMPORARY_PHOTO
    photo.save(update_fields=("kind",))
    _publish_sourced(photo, color=(77, 88, 99))

    selection = select_media_for_display(
        role=MediaRole.COUNTRY_HERO,
        country=finland,
    )

    assert selection is not None
    assert selection.fallback_level == 0
    assert selection.authenticity_class == "sourced_media"
    assert selection.image.label == "Premium destination photograph"


@pytest.mark.django_db
def test_responsive_derivative_is_hashed_but_never_auto_published(media_root):
    source = _publish_sourced(
        _sourced_asset(title="Source", role=MediaRole.STORY_COVER),
        color=(70, 80, 90),
    )
    source.width = 32
    source.height = 24
    source.focal_x = Decimal("0.250")
    source.focal_y = Decimal("0.625")
    source.save(update_fields=("width", "height", "focal_x", "focal_y"))

    derivative = create_responsive_derivative(source, width=16)

    assert derivative.derivative_of_id == source.pk
    assert derivative.variant_width == 16
    assert derivative.width == 16
    assert derivative.height == 12
    assert derivative.focal_x == Decimal("0.250")
    assert derivative.focal_y == Decimal("0.625")
    assert len(derivative.content_hash) == 64
    assert derivative.status == MediaStatus.NEEDS_REVIEW
    assert derivative.published_at is None


@pytest.mark.django_db
def test_selector_matches_equivalent_aspect_ratios(finland):
    matching = MediaAsset.objects.create(
        kind=MediaKind.CONTEMPORARY_PHOTO,
        source_kind=MediaSourceKind.MANUAL,
        role=MediaRole.LOCAL_DETAIL,
        country=finland,
        title="Matching ratio",
        storage_file="sourced/matching.webp",
        width=1600,
        height=900,
        aspect_ratio="1600 / 900",
        status=MediaStatus.PUBLISHED,
    )
    MediaAsset.objects.create(
        kind=MediaKind.CONTEMPORARY_PHOTO,
        source_kind=MediaSourceKind.MANUAL,
        role=MediaRole.LOCAL_DETAIL,
        country=finland,
        title="Newer non-matching ratio",
        storage_file="sourced/non-matching.webp",
        width=1600,
        height=1000,
        aspect_ratio="1600 / 1000",
        status=MediaStatus.PUBLISHED,
    )

    selected = select_published_media(
        role=MediaRole.LOCAL_DETAIL,
        country=finland,
        aspect_ratio="16 / 9",
    )

    assert selected is not None
    assert selected.asset.pk == matching.pk


@pytest.mark.django_db
def test_batch_selector_uses_one_query_and_preserves_role_authenticity_policy(finland):
    hero_generated = MediaAsset.objects.create(
        kind=MediaKind.GENERATED_ILLUSTRATION,
        source_kind=MediaSourceKind.GENERATED,
        role=MediaRole.COUNTRY_HERO,
        country=finland,
        title="Generated hero",
        storage_file="generated/hero.webp",
        width=1600,
        height=900,
        generated_by_ai=True,
        status=MediaStatus.PUBLISHED,
    )
    hero_sourced = MediaAsset.objects.create(
        kind=MediaKind.CONTEMPORARY_PHOTO,
        source_kind=MediaSourceKind.MANUAL,
        role=MediaRole.COUNTRY_HERO,
        country=finland,
        title="Sourced hero",
        storage_file="sourced/hero.webp",
        width=1600,
        height=900,
        status=MediaStatus.PUBLISHED,
    )
    everyday_generated = MediaAsset.objects.create(
        kind=MediaKind.GENERATED_ILLUSTRATION,
        source_kind=MediaSourceKind.GENERATED,
        role=MediaRole.EVERYDAY_VALUE,
        country=finland,
        title="Generated cafe",
        storage_file="generated/cafe.webp",
        width=1200,
        height=1500,
        generated_by_ai=True,
        status=MediaStatus.PUBLISHED,
    )
    everyday_sourced = MediaAsset.objects.create(
        kind=MediaKind.CONTEMPORARY_PHOTO,
        source_kind=MediaSourceKind.MANUAL,
        role=MediaRole.EVERYDAY_VALUE,
        country=finland,
        title="Sourced cafe",
        storage_file="sourced/cafe.webp",
        width=1200,
        height=1500,
        status=MediaStatus.PUBLISHED,
    )

    with CaptureQueriesContext(connection) as captured:
        selected = select_published_media_for_roles(
            roles=(MediaRole.COUNTRY_HERO, MediaRole.EVERYDAY_VALUE),
            country=finland,
        )

    assert len(captured) == 1
    assert selected[MediaRole.COUNTRY_HERO].asset.pk == hero_sourced.pk
    assert selected[MediaRole.EVERYDAY_VALUE].asset.pk == everyday_sourced.pk
    assert hero_generated.pk != hero_sourced.pk
    assert everyday_generated.pk != everyday_sourced.pk


@pytest.mark.django_db
def test_historical_selector_prefers_dated_ai_over_undated_neutral_sourced_media(media_root):
    neutral = MediaAsset.objects.create(
        kind=MediaKind.ARTWORK,
        source_kind=MediaSourceKind.WIKIMEDIA_COMMONS,
        role=MediaRole.STORY_COVER,
        title="Neutral sourced artwork",
        alt_text="Neutral sourced artwork",
        source_name="Wikimedia Commons",
        source_url="https://commons.wikimedia.org/wiki/File:Neutral.png",
        creator="Creator",
        licence_id="CC0",
        rights_statement="CC0",
        attribution_text="Creator · CC0",
    )
    attach_media_bytes(neutral, _png_bytes((81, 82, 83)), filename="neutral.png")
    approve_media_asset(neutral)
    publish_media_asset(neutral)

    ai = MediaAsset.objects.create(
        kind=MediaKind.GENERATED_ILLUSTRATION,
        source_kind=MediaSourceKind.GENERATED,
        role=MediaRole.STORY_COVER,
        title="Dated generated illustration",
        alt_text="Dated generated editorial illustration",
        valid_from=date(1995, 1, 1),
        valid_to=date(1995, 12, 31),
        date_precision=DatePrecision.YEAR,
        generated_by_ai=True,
        ai_label="AI-generated editorial illustration",
        generation_provider="example-provider",
        generation_model="example-model",
        prompt_version="media-prompt:v1",
        prompt_hash="c" * 64,
        generated_at=datetime(2026, 9, 21, tzinfo=UTC),
    )
    attach_media_bytes(ai, _png_bytes((84, 85, 86)), filename="ai.png")
    approve_media_asset(ai)
    publish_media_asset(ai)

    selected = select_published_media(
        role=MediaRole.STORY_COVER,
        target_date=date(1995, 6, 1),
    )

    assert selected is not None
    assert selected.asset.pk == ai.pk
