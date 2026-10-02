from __future__ import annotations

from decimal import Decimal

import pytest
from django.db import connection
from django.template.loader import render_to_string
from django.test.utils import CaptureQueriesContext

from apps.common.presentation.media_view_models import ImageViewModel
from apps.media.models import MediaAsset, MediaKind, MediaRole, MediaSourceKind, MediaStatus
from apps.media.presentation import (
    build_media_asset_image_view_model,
    select_media_for_display_roles,
)


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


@pytest.mark.django_db
def test_published_media_family_builds_width_descriptor_srcset():
    source = MediaAsset.objects.create(
        kind=MediaKind.CONTEMPORARY_PHOTO,
        source_kind=MediaSourceKind.WIKIMEDIA_COMMONS,
        role=MediaRole.COUNTRY_HERO,
        title="Helsinki source",
        alt_text="A Helsinki tram on a central city street.",
        storage_file="sourced/source.webp",
        width=2400,
        height=1800,
        status=MediaStatus.APPROVED,
    )
    small = MediaAsset.objects.create(
        kind=source.kind,
        source_kind=source.source_kind,
        role=source.role,
        title="Helsinki 800",
        alt_text=source.alt_text,
        storage_file="sourced/helsinki-800.webp",
        width=800,
        height=600,
        derivative_of=source,
        variant_width=800,
        status=MediaStatus.PUBLISHED,
    )
    large = MediaAsset.objects.create(
        kind=source.kind,
        source_kind=source.source_kind,
        role=source.role,
        title="Helsinki 1600",
        alt_text=source.alt_text,
        storage_file="sourced/helsinki-1600.webp",
        width=1600,
        height=1200,
        derivative_of=source,
        variant_width=1600,
        status=MediaStatus.PUBLISHED,
    )

    image = build_media_asset_image_view_model(small)

    assert image.srcset == (f"{small.storage_file.url} 800w, {large.storage_file.url} 1600w")
    assert image.sizes == "100vw"


@pytest.mark.django_db
def test_published_full_size_source_is_excluded_from_derivative_srcset():
    source = MediaAsset.objects.create(
        kind=MediaKind.CONTEMPORARY_PHOTO,
        source_kind=MediaSourceKind.WIKIMEDIA_COMMONS,
        role=MediaRole.COUNTRY_HERO,
        title="Helsinki source",
        alt_text="A Helsinki tram on a central city street.",
        storage_file="sourced/source.webp",
        width=2400,
        height=1800,
        status=MediaStatus.PUBLISHED,
    )
    small = MediaAsset.objects.create(
        kind=source.kind,
        source_kind=source.source_kind,
        role=source.role,
        title="Helsinki 800",
        alt_text=source.alt_text,
        storage_file="sourced/helsinki-800.webp",
        width=800,
        height=600,
        derivative_of=source,
        variant_width=800,
        status=MediaStatus.PUBLISHED,
    )
    large = MediaAsset.objects.create(
        kind=source.kind,
        source_kind=source.source_kind,
        role=source.role,
        title="Helsinki 1600",
        alt_text=source.alt_text,
        storage_file="sourced/helsinki-1600.webp",
        width=1600,
        height=1200,
        derivative_of=source,
        variant_width=1600,
        status=MediaStatus.PUBLISHED,
    )

    image = build_media_asset_image_view_model(small)

    assert image.srcset == (f"{small.storage_file.url} 800w, {large.storage_file.url} 1600w")
    assert source.storage_file.url not in image.srcset


@pytest.mark.django_db
def test_single_published_derivative_does_not_force_a_srcset_candidate():
    source = MediaAsset.objects.create(
        kind=MediaKind.CONTEMPORARY_PHOTO,
        source_kind=MediaSourceKind.WIKIMEDIA_COMMONS,
        role=MediaRole.COUNTRY_HERO,
        title="Helsinki source",
        alt_text="A Helsinki tram on a central city street.",
        storage_file="sourced/source.webp",
        width=2400,
        height=1800,
        status=MediaStatus.APPROVED,
    )
    derivative = MediaAsset.objects.create(
        kind=source.kind,
        source_kind=source.source_kind,
        role=source.role,
        title="Helsinki 1200",
        alt_text=source.alt_text,
        storage_file="sourced/helsinki-1200.webp",
        width=1200,
        height=900,
        derivative_of=source,
        variant_width=1200,
        status=MediaStatus.PUBLISHED,
    )

    image = build_media_asset_image_view_model(derivative)

    assert image.srcset == ""
    assert image.sizes == ""


@pytest.mark.django_db
def test_multi_role_presentation_batches_selection_and_srcset_queries():
    from apps.countries.models import Country

    finland = Country.objects.create(iso2="FI", iso3="FIN", name="Finland")
    hero_source = MediaAsset.objects.create(
        kind=MediaKind.CONTEMPORARY_PHOTO,
        source_kind=MediaSourceKind.MANUAL,
        role=MediaRole.COUNTRY_HERO,
        country=finland,
        title="Hero source",
        alt_text="Helsinki street scene.",
        storage_file="sourced/hero-source.webp",
        width=2400,
        height=1350,
        status=MediaStatus.APPROVED,
    )
    everyday_source = MediaAsset.objects.create(
        kind=MediaKind.CONTEMPORARY_PHOTO,
        source_kind=MediaSourceKind.MANUAL,
        role=MediaRole.EVERYDAY_VALUE,
        country=finland,
        title="Everyday source",
        alt_text="Coffee and pastry in Helsinki.",
        storage_file="sourced/everyday-source.webp",
        width=1800,
        height=2250,
        status=MediaStatus.APPROVED,
    )
    for source, widths in ((hero_source, (800, 1600)), (everyday_source, (600, 1200))):
        for width in widths:
            MediaAsset.objects.create(
                kind=source.kind,
                source_kind=source.source_kind,
                role=source.role,
                country=source.country,
                title=f"{source.title} {width}",
                alt_text=source.alt_text,
                storage_file=f"sourced/{source.role}-{width}.webp",
                width=width,
                height=round((source.height or 1) * width / (source.width or 1)),
                derivative_of=source,
                variant_width=width,
                status=MediaStatus.PUBLISHED,
            )

    with CaptureQueriesContext(connection) as captured:
        selected = select_media_for_display_roles(
            roles=(MediaRole.COUNTRY_HERO, MediaRole.EVERYDAY_VALUE),
            country=finland,
        )

    assert len(captured) == 2
    assert "800w" in selected[MediaRole.COUNTRY_HERO].image.srcset
    assert "1600w" in selected[MediaRole.COUNTRY_HERO].image.srcset
    assert "600w" in selected[MediaRole.EVERYDAY_VALUE].image.srcset
    assert "1200w" in selected[MediaRole.EVERYDAY_VALUE].image.srcset
