from __future__ import annotations

from decimal import Decimal

from django.template.loader import render_to_string

from apps.common.presentation.media_view_models import ImageViewModel
from apps.media.models import MediaAsset, MediaKind, MediaRole, MediaSourceKind, MediaStatus
from apps.media.presentation import build_media_asset_image_view_model


def test_generated_media_authenticity_label_is_visible_not_alt_only():
    image = ImageViewModel(
        src="/media/generated/example.webp",
        ratio="4 / 3",
        alt="Editorial illustration of a historical scene",
        decorative=False,
        kind="generated_illustration",
        label="Historical illustration",
        width=1200,
        height=900,
        caption="Illustration based on sourced historical context.",
        authenticity_label="AI-generated editorial illustration · not an archival photograph",
    )

    html = render_to_string("components/media/image_frame.html", {"image": image})

    assert "AI-generated editorial illustration" in html
    assert "qa-media__authenticity" in html
    assert html.count("AI-generated editorial illustration") == 1


def test_sourced_media_attribution_links_to_canonical_source():
    image = ImageViewModel(
        src="/media/sourced/example.webp",
        ratio="4 / 3",
        alt="Archive photograph",
        decorative=False,
        kind="archival_photo",
        label="Archive photograph",
        width=1200,
        height=900,
        attribution_text="Example Archive · CC BY-SA 4.0",
        source_url="https://commons.wikimedia.org/wiki/File:Example.jpg",
    )

    html = render_to_string("components/media/image_frame.html", {"image": image})

    assert "Example Archive · CC BY-SA 4.0" in html
    assert 'href="https://commons.wikimedia.org/wiki/File:Example.jpg"' in html


def test_managed_media_focal_point_reaches_image_view_model():
    asset = MediaAsset(
        kind=MediaKind.CONTEMPORARY_PHOTO,
        source_kind=MediaSourceKind.WIKIMEDIA_COMMONS,
        role=MediaRole.COUNTRY_HERO,
        title="Helsinki tram",
        alt_text="A Helsinki tram on a central city street.",
        storage_file="sourced/helsinki.webp",
        width=1600,
        height=1200,
        focal_x=Decimal("0.250"),
        focal_y=Decimal("0.625"),
        status=MediaStatus.PUBLISHED,
    )

    image = build_media_asset_image_view_model(asset)

    assert image.focal_position == "25% 62.5%"


def test_partial_managed_media_focal_point_defaults_missing_axis_to_center():
    asset = MediaAsset(
        kind=MediaKind.CONTEMPORARY_PHOTO,
        source_kind=MediaSourceKind.WIKIMEDIA_COMMONS,
        role=MediaRole.COUNTRY_HERO,
        title="Helsinki tram",
        alt_text="A Helsinki tram on a central city street.",
        storage_file="sourced/helsinki.webp",
        width=1600,
        height=1200,
        focal_x=Decimal("0.125"),
        focal_y=None,
        status=MediaStatus.PUBLISHED,
    )

    image = build_media_asset_image_view_model(asset)

    assert image.focal_position == "12.5% 50%"
