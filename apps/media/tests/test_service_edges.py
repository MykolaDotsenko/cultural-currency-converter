from __future__ import annotations

import io
from datetime import date
import tempfile
from pathlib import Path

import pytest
from django.test import override_settings
from PIL import Image

from apps.media.models import (
    DatePrecision,
    MediaAsset,
    MediaKind,
    MediaRole,
    MediaSourceKind,
    MediaStatus,
)
from apps.media.services import (
    MediaPublicationError,
    approve_media_asset,
    attach_media_bytes,
    publish_media_asset,
    reject_media_asset,
    retire_media_asset,
    select_published_media,
    upsert_media_candidates,
)
from apps.media.sources.base import MediaCandidate


def _png() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (12, 8), (12, 34, 56)).save(output, "PNG")
    return output.getvalue()


@pytest.fixture
def media_root():
    with tempfile.TemporaryDirectory() as directory:
        with override_settings(MEDIA_ROOT=Path(directory)):
            yield


def _valid_sourced_asset() -> MediaAsset:
    return MediaAsset.objects.create(
        kind=MediaKind.ARTWORK,
        source_kind=MediaSourceKind.WIKIMEDIA_COMMONS,
        role=MediaRole.STORY_COVER,
        title="Valid sourced art",
        alt_text="A sourced editorial artwork",
        source_name="Wikimedia Commons",
        source_url="https://commons.wikimedia.org/wiki/File:Valid.png",
        source_media_url="https://upload.wikimedia.org/valid.png",
        creator="Creator",
        licence_id="CC0",
        licence_url="https://creativecommons.org/publicdomain/zero/1.0/",
        rights_statement="CC0",
        attribution_text="Creator · CC0",
    )


@pytest.mark.django_db
def test_publish_rejects_unapproved_asset(media_root):
    asset = _valid_sourced_asset()
    attach_media_bytes(asset, _png(), filename="valid.png")

    with pytest.raises(MediaPublicationError, match="approved"):
        publish_media_asset(asset)


@pytest.mark.django_db
def test_published_asset_can_be_retired_but_not_reapproved(media_root):
    asset = _valid_sourced_asset()
    attach_media_bytes(asset, _png(), filename="valid.png")
    approve_media_asset(asset)
    publish_media_asset(asset)
    retire_media_asset(asset)

    assert asset.status == MediaStatus.RETIRED
    with pytest.raises(MediaPublicationError, match="Cannot approve"):
        approve_media_asset(asset)


@pytest.mark.django_db
def test_selector_returns_none_when_only_nonpublished_media_exists():
    MediaAsset.objects.create(
        kind=MediaKind.ARTWORK,
        source_kind=MediaSourceKind.MANUAL,
        role=MediaRole.STORY_COVER,
        title="Draft",
        status=MediaStatus.APPROVED,
    )

    assert select_published_media(role=MediaRole.STORY_COVER) is None


@pytest.mark.django_db
def test_archival_media_requires_temporal_scope_and_precision(media_root):
    asset = _valid_sourced_asset()
    asset.kind = MediaKind.ARCHIVAL_PHOTO
    asset.save(update_fields=("kind",))
    attach_media_bytes(asset, _png(), filename="valid.png")

    with pytest.raises(MediaPublicationError, match="temporal precision"):
        approve_media_asset(asset)

    asset.date_precision = DatePrecision.YEAR
    asset.save(update_fields=("date_precision",))
    with pytest.raises(MediaPublicationError, match="temporal scope"):
        approve_media_asset(asset)


@pytest.mark.django_db
def test_historical_candidate_ingestion_requires_scope_at_service_boundary():
    candidate = MediaCandidate(
        source_kind=MediaSourceKind.WIKIMEDIA_COMMONS,
        external_id="historical",
        title="Historical",
        source_name="Wikimedia Commons",
        source_url="https://commons.wikimedia.org/wiki/File:Historical.jpg",
    )

    with pytest.raises(ValueError, match="temporal precision"):
        upsert_media_candidates(
            (candidate,),
            role=MediaRole.HISTORICAL_TIMELINE,
            kind=MediaKind.ARCHIVAL_PHOTO,
            valid_from=date(1950, 1, 1),
        )

    with pytest.raises(ValueError, match="temporal scope"):
        upsert_media_candidates(
            (candidate,),
            role=MediaRole.HISTORICAL_TIMELINE,
            kind=MediaKind.ARCHIVAL_PHOTO,
            date_precision=DatePrecision.YEAR,
        )


@pytest.mark.django_db
def test_comparison_candidate_ingestion_requires_currency_at_service_boundary():
    candidate = MediaCandidate(
        source_kind=MediaSourceKind.WIKIMEDIA_COMMONS,
        external_id="comparison",
        title="Comparison",
        source_name="Wikimedia Commons",
        source_url="https://commons.wikimedia.org/wiki/File:Comparison.jpg",
    )

    with pytest.raises(ValueError, match="currency scope"):
        upsert_media_candidates(
            (candidate,),
            role=MediaRole.COMPARISON_THEN,
            kind=MediaKind.ARCHIVAL_PHOTO,
            valid_from=date(1998, 1, 1),
            valid_to=date(1998, 12, 31),
            date_precision=DatePrecision.YEAR,
        )


@pytest.mark.django_db
def test_candidate_ingestion_rejects_inverted_temporal_scope():
    candidate = MediaCandidate(
        source_kind=MediaSourceKind.WIKIMEDIA_COMMONS,
        external_id="bad-range",
        title="Bad range",
        source_name="Wikimedia Commons",
        source_url="https://commons.wikimedia.org/wiki/File:Bad_range.jpg",
    )

    with pytest.raises(ValueError, match="start must not be after"):
        upsert_media_candidates(
            (candidate,),
            role=MediaRole.HISTORICAL_TIMELINE,
            kind=MediaKind.ARCHIVAL_PHOTO,
            valid_from=date(2000, 1, 1),
            valid_to=date(1999, 12, 31),
            date_precision=DatePrecision.RANGE,
        )


@pytest.mark.django_db
def test_candidate_ingestion_rejects_non_https_source_url():
    candidate = MediaCandidate(
        source_kind=MediaSourceKind.WIKIMEDIA_COMMONS,
        external_id="bad",
        title="Bad",
        source_name="Source",
        source_url="http://example.test/file",
    )

    with pytest.raises(MediaPublicationError, match="HTTPS"):
        upsert_media_candidates(
            (candidate,),
            role=MediaRole.STORY_COVER,
            kind=MediaKind.ARTWORK,
        )


@pytest.mark.django_db
def test_protected_published_candidate_is_not_downgraded(media_root):
    asset = _valid_sourced_asset()
    asset.external_id = "protected"
    asset.save(update_fields=("external_id",))
    attach_media_bytes(asset, _png(), filename="valid.png")
    approve_media_asset(asset)
    publish_media_asset(asset)

    candidate = MediaCandidate(
        source_kind=MediaSourceKind.WIKIMEDIA_COMMONS,
        external_id="protected",
        title="Upstream changed title",
        source_name="Wikimedia Commons",
        source_url="https://commons.wikimedia.org/wiki/File:Valid.png",
    )
    summary = upsert_media_candidates(
        (candidate,),
        role=MediaRole.STORY_COVER,
        kind=MediaKind.ARTWORK,
    )

    asset.refresh_from_db()
    assert summary.skipped_protected == 1
    assert asset.status == MediaStatus.PUBLISHED
    assert asset.title == "Valid sourced art"


@pytest.mark.django_db
def test_unknown_role_and_generated_ingestion_kind_are_rejected():
    with pytest.raises(ValueError, match="role"):
        select_published_media(role="not-a-role")

    with pytest.raises(ValueError, match="non-generated"):
        upsert_media_candidates(
            (),
            role=MediaRole.STORY_COVER,
            kind=MediaKind.GENERATED_ILLUSTRATION,
        )


@pytest.mark.django_db
def test_failed_approval_does_not_leave_in_memory_review_marker(media_root):
    asset = _valid_sourced_asset()
    asset.rights_statement = ""
    asset.licence_id = ""
    attach_media_bytes(asset, _png(), filename="valid.png")

    assert asset.reviewed_at is None
    with pytest.raises(MediaPublicationError):
        approve_media_asset(asset)
    assert asset.reviewed_at is None


@pytest.mark.django_db
def test_reject_marks_unpublished_candidate_reviewed():
    asset = _valid_sourced_asset()

    reject_media_asset(asset)

    assert asset.status == MediaStatus.REJECTED
    assert asset.reviewed_at is not None


@pytest.mark.django_db
def test_reject_cannot_rewrite_published_asset(media_root):
    asset = _valid_sourced_asset()
    attach_media_bytes(asset, _png(), filename="valid.png")
    approve_media_asset(asset)
    publish_media_asset(asset)

    with pytest.raises(MediaPublicationError, match="cannot be rejected"):
        reject_media_asset(asset)


@pytest.mark.django_db
def test_ai_approval_requires_real_sha256_prompt_hash(media_root):
    asset = MediaAsset.objects.create(
        kind=MediaKind.GENERATED_ILLUSTRATION,
        source_kind=MediaSourceKind.GENERATED,
        role=MediaRole.STORY_COVER,
        title="Generated",
        alt_text="Generated editorial illustration",
        generated_by_ai=True,
        ai_label="AI-generated editorial illustration",
        generation_provider="provider",
        generation_model="model",
        prompt_version="v1",
        prompt_hash="z" * 64,
    )
    attach_media_bytes(asset, _png(), filename="generated.png")

    with pytest.raises(MediaPublicationError, match="prompt_hash"):
        approve_media_asset(asset)


@pytest.mark.django_db
def test_ai_approval_requires_explicit_ai_generated_label(media_root):
    asset = MediaAsset.objects.create(
        kind=MediaKind.GENERATED_ILLUSTRATION,
        source_kind=MediaSourceKind.GENERATED,
        role=MediaRole.STORY_COVER,
        title="Generated",
        alt_text="Generated editorial illustration",
        generated_by_ai=True,
        ai_label="Editorial illustration",
        generation_provider="provider",
        generation_model="model",
        prompt_version="v1",
        prompt_hash="a" * 64,
    )
    attach_media_bytes(asset, _png(), filename="generated.png")

    with pytest.raises(MediaPublicationError, match="explicitly"):
        approve_media_asset(asset)
