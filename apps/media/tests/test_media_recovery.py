"""Managed media recovery validates actual bytes without mutating objects."""

from __future__ import annotations

import hashlib
from io import StringIO

import pytest
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from apps.media.models import MediaAsset, MediaKind, MediaRole, MediaSourceKind, MediaStatus


def _asset(payload: bytes, *, status: str = MediaStatus.PUBLISHED) -> MediaAsset:
    asset = MediaAsset.objects.create(
        title="Disposable recovery media",
        kind=MediaKind.ARTWORK,
        role=MediaRole.STORY_COVER,
        source_kind=MediaSourceKind.MANUAL,
        status=status,
        content_hash=hashlib.sha256(payload).hexdigest(),
    )
    asset.storage_file.save("test.png", ContentFile(payload), save=True)
    return asset


@pytest.mark.django_db
def test_published_media_recovery_matches_bytes(tmp_path) -> None:
    with override_settings(MEDIA_ROOT=tmp_path):
        asset = _asset(b"this-is-a-test-only-media-payload")
        out = StringIO()
        call_command("verify_media_recovery", asset_id=asset.pk, stdout=out)
        assert "VERIFIED" in out.getvalue()
        assert MediaAsset.objects.get(pk=asset.pk).status == MediaStatus.PUBLISHED


@pytest.mark.django_db
def test_media_recovery_rejects_checksum_mismatch(tmp_path) -> None:
    with override_settings(MEDIA_ROOT=tmp_path):
        asset = _asset(b"source-media-bytes")
        asset.content_hash = "a" * 64
        asset.save(update_fields=["content_hash"])
        with pytest.raises(CommandError, match="checksum mismatch"):
            call_command("verify_media_recovery", asset_id=asset.pk)


@pytest.mark.django_db
def test_media_recovery_requires_published_reviewed_asset(tmp_path) -> None:
    with override_settings(MEDIA_ROOT=tmp_path):
        asset = _asset(b"candidate", status=MediaStatus.CANDIDATE)
        with pytest.raises(CommandError, match="Only published"):
            call_command("verify_media_recovery", asset_id=asset.pk)


@pytest.mark.django_db
def test_media_recovery_missing_storage_fails_closed() -> None:
    asset = MediaAsset.objects.create(
        title="Unstored media",
        kind=MediaKind.ARTWORK,
        role=MediaRole.STORY_COVER,
        source_kind=MediaSourceKind.MANUAL,
        status=MediaStatus.PUBLISHED,
        content_hash="b" * 64,
    )
    with pytest.raises(CommandError, match="no storage reference"):
        call_command("verify_media_recovery", asset_id=asset.pk)


@pytest.mark.django_db
def test_media_recovery_never_prints_storage_exception_details(tmp_path, monkeypatch) -> None:
    with override_settings(MEDIA_ROOT=tmp_path):
        asset = _asset(b"private-object")
        storage = asset.storage_file.storage

        def fail(*args, **kwargs):
            raise OSError("token=DO_NOT_EXPOSE private-storage.internal")

        monkeypatch.setattr(storage, "open", fail)
        with pytest.raises(CommandError, match="bytes are unavailable") as err:
            call_command("verify_media_recovery", asset_id=asset.pk)
        assert "DO_NOT_EXPOSE" not in str(err.value)
        assert "private-storage" not in str(err.value)


@pytest.mark.django_db
def test_media_recovery_rejects_missing_asset() -> None:
    with pytest.raises(CommandError, match="does not exist"):
        call_command("verify_media_recovery", asset_id=999999)
