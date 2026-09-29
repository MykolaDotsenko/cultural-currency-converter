from __future__ import annotations

import io
import tempfile
from pathlib import Path

import pytest
from django.contrib import admin
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings
from PIL import Image

from apps.media.admin import MediaAssetAdmin
from apps.media.models import (
    MediaAsset,
    MediaKind,
    MediaRole,
    MediaSourceKind,
    MediaStatus,
)
from apps.media.presentation import build_media_asset_image_view_model, select_media_for_display
from apps.media.services import (
    approve_media_asset,
    attach_media_bytes,
    publish_media_asset,
)


def _png(*, size=(32, 24), color=(30, 60, 90)) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", size, color).save(output, format="PNG")
    return output.getvalue()


@pytest.fixture
def media_root():
    with tempfile.TemporaryDirectory() as directory:
        with override_settings(MEDIA_ROOT=Path(directory)):
            yield Path(directory)


def _sourced_asset(*, role=MediaRole.STORY_COVER, country=None) -> MediaAsset:
    return MediaAsset.objects.create(
        kind=MediaKind.ARTWORK,
        source_kind=MediaSourceKind.WIKIMEDIA_COMMONS,
        role=role,
        country=country,
        title="Reviewed media",
        alt_text="Reviewed editorial media",
        source_name="Wikimedia Commons",
        source_url="https://commons.wikimedia.org/wiki/File:Reviewed.png",
        source_media_url="https://upload.wikimedia.org/reviewed.png",
        creator="Creator",
        licence_id="CC0",
        licence_url="https://creativecommons.org/publicdomain/zero/1.0/",
        rights_statement="CC0",
        attribution_text="Creator · CC0",
    )


def _publish(asset: MediaAsset, payload: bytes) -> MediaAsset:
    attach_media_bytes(asset, payload, filename="source.png")
    approve_media_asset(asset)
    publish_media_asset(asset)
    return asset


@pytest.mark.django_db
def test_attach_media_file_command_covers_success_and_guardrails(media_root, tmp_path):
    source_path = tmp_path / "source.png"
    source_path.write_bytes(_png())
    asset = _sourced_asset()

    output = io.StringIO()
    call_command(
        "attach_media_file",
        asset_id=asset.pk,
        path=str(source_path),
        stdout=output,
    )
    asset.refresh_from_db()

    assert asset.status == MediaStatus.NEEDS_REVIEW
    assert "ATTACHED:" in output.getvalue()
    assert asset.content_hash in output.getvalue()

    with pytest.raises(CommandError, match="does not exist"):
        call_command("attach_media_file", asset_id=999999, path=str(source_path))

    with pytest.raises(CommandError, match="does not exist or is not a file"):
        call_command(
            "attach_media_file",
            asset_id=asset.pk,
            path=str(tmp_path / "missing.png"),
        )

    broken = _sourced_asset()
    broken_path = tmp_path / "broken.png"
    broken_path.write_bytes(b"not an image")
    with pytest.raises(CommandError, match="decodable"):
        call_command(
            "attach_media_file",
            asset_id=broken.pk,
            path=str(broken_path),
        )


@pytest.mark.django_db
def test_build_media_derivative_command_covers_success_and_errors(media_root):
    source = _publish(_sourced_asset(), _png(size=(64, 48), color=(1, 2, 3)))

    output = io.StringIO()
    call_command(
        "build_media_derivative",
        asset_id=source.pk,
        width=32,
        stdout=output,
    )

    derivative = MediaAsset.objects.exclude(pk=source.pk).get()
    assert derivative.derivative_of_id == source.pk
    assert derivative.status == MediaStatus.NEEDS_REVIEW
    assert "CREATED:" in output.getvalue()

    with pytest.raises(CommandError, match="does not exist"):
        call_command("build_media_derivative", asset_id=999999, width=16)

    with pytest.raises(CommandError, match="smaller"):
        call_command(
            "build_media_derivative",
            asset_id=source.pk,
            width=source.width,
        )


@pytest.mark.django_db
def test_build_media_derivative_command_creates_explicit_width_batch(media_root):
    source = _publish(_sourced_asset(), _png(size=(64, 48), color=(21, 22, 23)))
    output = io.StringIO()

    call_command(
        "build_media_derivative",
        "--asset-id",
        str(source.pk),
        "--width",
        "16",
        "--width",
        "32",
        stdout=output,
    )

    derivatives = list(MediaAsset.objects.filter(derivative_of=source).order_by("variant_width"))
    assert [asset.variant_width for asset in derivatives] == [16, 32]
    assert all(asset.status == MediaStatus.NEEDS_REVIEW for asset in derivatives)
    assert output.getvalue().count("CREATED:") == 2
    assert "CREATED BATCH:" in output.getvalue()


@pytest.mark.django_db
def test_build_media_derivative_command_prevalidates_batch_before_creating(media_root):
    source = _publish(_sourced_asset(), _png(size=(64, 48), color=(31, 32, 33)))

    with pytest.raises(CommandError, match="positive and smaller"):
        call_command(
            "build_media_derivative",
            "--asset-id",
            str(source.pk),
            "--width",
            "16",
            "--width",
            "64",
        )

    assert not MediaAsset.objects.filter(derivative_of=source).exists()

    with pytest.raises(CommandError, match="unique"):
        call_command(
            "build_media_derivative",
            "--asset-id",
            str(source.pk),
            "--width",
            "16",
            "--width",
            "16",
        )

    assert not MediaAsset.objects.filter(derivative_of=source).exists()


@pytest.mark.django_db
def test_admin_transition_actions_use_review_gates(monkeypatch):
    model_admin = MediaAssetAdmin(MediaAsset, admin.site)
    asset = MediaAsset.objects.create(
        kind=MediaKind.ARTWORK,
        source_kind=MediaSourceKind.MANUAL,
        role=MediaRole.STORY_COVER,
        title="Candidate",
    )
    messages_seen: list[tuple[str, int]] = []

    monkeypatch.setattr(
        model_admin,
        "message_user",
        lambda request, message, level: messages_seen.append((message, level)),
    )

    model_admin.reject_selected(object(), [asset])
    asset.refresh_from_db()
    assert asset.status == MediaStatus.REJECTED
    assert any("rejected" in message for message, _level in messages_seen)

    failing = MediaAsset.objects.create(
        kind=MediaKind.ARTWORK,
        source_kind=MediaSourceKind.MANUAL,
        role=MediaRole.STORY_COVER,
        title="Invalid approval",
    )
    model_admin.approve_selected(object(), [failing])
    assert any("Skipped assets:" in message for message, _level in messages_seen)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("method_name", "expected_label"),
    [
        ("publish_selected", "published"),
        ("retire_selected", "retired"),
    ],
)
def test_admin_actions_delegate_to_controlled_transition(monkeypatch, method_name, expected_label):
    model_admin = MediaAssetAdmin(MediaAsset, admin.site)
    recorded = {}

    def fake_transition(request, queryset, transition, label):
        recorded["request"] = request
        recorded["queryset"] = queryset
        recorded["transition"] = transition
        recorded["label"] = label

    monkeypatch.setattr(model_admin, "_run_transition", fake_transition)
    request = object()
    queryset = []
    getattr(model_admin, method_name)(request, queryset)

    assert recorded["request"] is request
    assert recorded["queryset"] is queryset
    assert recorded["label"] == expected_label


@pytest.mark.django_db
def test_managed_published_media_uses_shared_image_view_model(media_root):
    asset = _publish(_sourced_asset(), _png(color=(4, 5, 6)))
    asset.caption = "Editorial caption"
    asset.save(update_fields=("caption",))

    selection = select_media_for_display(role=MediaRole.STORY_COVER)

    assert selection.fallback_level == 0
    assert selection.authenticity_class == "sourced_media"
    assert selection.image.src.startswith("/media/")
    assert selection.image.caption == "Editorial caption"
    assert selection.image.attribution_text == "Creator · CC0"


@pytest.mark.django_db
def test_unpublished_managed_media_cannot_be_rendered():
    asset = _sourced_asset()

    with pytest.raises(ValueError, match="published"):
        build_media_asset_image_view_model(asset)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "role",
    [
        MediaRole.COUNTRY_TEASER,
        MediaRole.COMPARISON_THEN,
        MediaRole.COMPARISON_NOW,
        MediaRole.STORY_COVER,
        MediaRole.STORY_CHAPTER,
        MediaRole.HISTORICAL_TIMELINE,
        MediaRole.SOCIAL_PREVIEW,
        MediaRole.DECORATIVE_BACKGROUND,
    ],
)
def test_missing_media_returns_none_instead_of_decorative_placeholder(role):
    assert select_media_for_display(role=role) is None
