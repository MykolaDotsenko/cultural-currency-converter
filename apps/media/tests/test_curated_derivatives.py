from __future__ import annotations

import io
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings
from PIL import Image

from apps.countries.models import Country
from apps.media.curated import CURATED_MEDIA, CuratedMediaSpec
from apps.media.models import (
    DatePrecision,
    MediaAsset,
    MediaKind,
    MediaRole,
    MediaSourceKind,
    MediaStatus,
)
from apps.media.presentation import build_media_asset_image_view_model
from apps.media.services import approve_media_asset, attach_media_bytes, publish_media_asset


def _png(*, size=(64, 48), color=(40, 70, 100)) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", size, color).save(output, format="PNG")
    return output.getvalue()


@pytest.fixture
def media_root():
    with tempfile.TemporaryDirectory() as directory:
        with override_settings(MEDIA_ROOT=Path(directory)):
            yield Path(directory)


@pytest.fixture
def curated_destination(monkeypatch):
    spec = CuratedMediaSpec(
        slug="test-reviewed-finland-responsive",
        country_code="FI",
        currency_code="",
        city="Helsinki",
        valid_from=date(2026, 5, 24),
        valid_to=date(2026, 5, 24),
        date_precision=DatePrecision.EXACT_DAY,
        role=MediaRole.COUNTRY_HERO,
        kind=MediaKind.CONTEMPORARY_PHOTO,
        source_kind=MediaSourceKind.WIKIMEDIA_COMMONS,
        external_id="commons:test-reviewed-finland-responsive",
        title="Reviewed Helsinki source",
        alt_text="A reviewed Helsinki destination photograph.",
        caption="Reviewed Helsinki destination photograph.",
        source_name="Wikimedia Commons",
        source_url="https://commons.wikimedia.org/wiki/File:Reviewed_Helsinki.png",
        source_media_url="https://upload.wikimedia.org/wikipedia/commons/a/ab/Reviewed_Helsinki.png",
        creator="Creator",
        licence_id="CC BY-SA 4.0",
        licence_url="https://creativecommons.org/licenses/by-sa/4.0/",
        rights_statement="Creative Commons Attribution-ShareAlike 4.0 International",
        attribution_text="Creator · CC BY-SA 4.0",
        expected_width=64,
        expected_height=48,
        focal_x=Decimal("0.250"),
        focal_y=Decimal("0.625"),
        responsive_widths=(16, 32),
    )
    monkeypatch.setitem(CURATED_MEDIA, spec.slug, spec)
    return spec


@pytest.fixture
def reviewed_source(db, media_root, curated_destination):
    finland = Country.objects.create(iso2="FI", iso3="FIN", name="Finland")
    source = MediaAsset.objects.create(
        kind=curated_destination.kind,
        source_kind=curated_destination.source_kind,
        role=curated_destination.role,
        country=finland,
        city=curated_destination.city,
        valid_from=curated_destination.valid_from,
        valid_to=curated_destination.valid_to,
        date_precision=curated_destination.date_precision,
        title=curated_destination.title,
        alt_text=curated_destination.alt_text,
        caption=curated_destination.caption,
        focal_x=curated_destination.focal_x,
        focal_y=curated_destination.focal_y,
        source_name=curated_destination.source_name,
        source_url=curated_destination.source_url,
        source_media_url=curated_destination.source_media_url,
        external_id=curated_destination.external_id,
        creator=curated_destination.creator,
        licence_id=curated_destination.licence_id,
        licence_url=curated_destination.licence_url,
        rights_statement=curated_destination.rights_statement,
        attribution_text=curated_destination.attribution_text,
    )
    attach_media_bytes(source, _png(), filename="reviewed.png")
    approve_media_asset(source)
    return source


@pytest.mark.django_db
def test_curated_derivative_build_dry_run_has_no_file_or_database_writes(
    reviewed_source,
    curated_destination,
) -> None:
    output = io.StringIO()

    call_command(
        "build_curated_media_derivatives",
        "--slug",
        curated_destination.slug,
        "--dry-run",
        stdout=output,
    )

    assert not MediaAsset.objects.filter(derivative_of=reviewed_source).exists()
    assert "missing=(16, 32)" in output.getvalue()


@pytest.mark.django_db
def test_curated_derivative_build_is_idempotent_and_preserves_review_contract(
    reviewed_source,
    curated_destination,
) -> None:
    first = io.StringIO()
    call_command(
        "build_curated_media_derivatives",
        "--slug",
        curated_destination.slug,
        stdout=first,
    )

    derivatives = list(
        MediaAsset.objects.filter(derivative_of=reviewed_source).order_by("variant_width")
    )
    assert [asset.variant_width for asset in derivatives] == [16, 32]
    assert all(asset.status == MediaStatus.NEEDS_REVIEW for asset in derivatives)
    assert all(asset.focal_x == Decimal("0.250") for asset in derivatives)
    assert all(asset.focal_y == Decimal("0.625") for asset in derivatives)
    assert all(asset.source_url == curated_destination.source_url for asset in derivatives)
    assert all(asset.licence_id == curated_destination.licence_id for asset in derivatives)
    assert first.getvalue().count("CREATED:") == 2
    assert "were not auto-published" in first.getvalue()

    for derivative in derivatives:
        approve_media_asset(derivative)
        publish_media_asset(derivative)

    responsive_image = build_media_asset_image_view_model(derivatives[0])
    assert f"{derivatives[0].storage_file.url} 16w" in responsive_image.srcset
    assert f"{derivatives[1].storage_file.url} 32w" in responsive_image.srcset
    assert responsive_image.focal_position == "25% 62.5%"

    coverage = io.StringIO()
    call_command(
        "report_curated_media_coverage",
        "--slug",
        curated_destination.slug,
        "--strict",
        stdout=coverage,
    )
    assert f"READY: slug={curated_destination.slug}" in coverage.getvalue()
    assert "ready=1 total=1 not_ready=0" in coverage.getvalue()

    second = io.StringIO()
    call_command(
        "build_curated_media_derivatives",
        "--slug",
        curated_destination.slug,
        stdout=second,
    )

    assert MediaAsset.objects.filter(derivative_of=reviewed_source).count() == 2
    assert "UNCHANGED:" in second.getvalue()


@pytest.mark.django_db
def test_curated_media_coverage_strict_fails_before_derivatives_are_published(
    reviewed_source,
    curated_destination,
) -> None:
    output = io.StringIO()

    with pytest.raises(CommandError, match="not fully runtime-ready"):
        call_command(
            "report_curated_media_coverage",
            "--slug",
            curated_destination.slug,
            "--strict",
            stdout=output,
        )

    assert f"NOT_READY: slug={curated_destination.slug}" in output.getvalue()
    assert "published=()" in output.getvalue()
    assert "ready=0 total=1 not_ready=1" in output.getvalue()


@pytest.mark.django_db
def test_curated_derivative_build_rejects_drifted_existing_width(
    reviewed_source,
    curated_destination,
) -> None:
    call_command(
        "build_curated_media_derivatives",
        "--slug",
        curated_destination.slug,
    )
    derivative = MediaAsset.objects.get(
        derivative_of=reviewed_source,
        variant_width=16,
    )
    derivative.focal_x = Decimal("0.500")
    derivative.save(update_fields=("focal_x", "updated_at"))

    with pytest.raises(CommandError, match="derivative metadata drift"):
        call_command(
            "build_curated_media_derivatives",
            "--slug",
            curated_destination.slug,
        )


@pytest.mark.django_db
def test_curated_media_coverage_rejects_drifted_published_family(
    reviewed_source,
    curated_destination,
) -> None:
    call_command(
        "build_curated_media_derivatives",
        "--slug",
        curated_destination.slug,
    )
    derivatives = list(
        MediaAsset.objects.filter(derivative_of=reviewed_source).order_by("variant_width")
    )
    for derivative in derivatives:
        approve_media_asset(derivative)
        publish_media_asset(derivative)

    derivatives[0].focal_y = Decimal("0.500")
    derivatives[0].save(update_fields=("focal_y", "updated_at"))

    output = io.StringIO()
    with pytest.raises(CommandError, match="not fully runtime-ready"):
        call_command(
            "report_curated_media_coverage",
            "--slug",
            curated_destination.slug,
            "--strict",
            stdout=output,
        )

    assert "derivative_contract=false" in output.getvalue()
    assert "NOT_READY:" in output.getvalue()


@pytest.mark.django_db
def test_curated_derivative_build_requires_explicitly_reviewed_source(
    db,
    media_root,
    curated_destination,
) -> None:
    finland = Country.objects.create(iso2="FI", iso3="FIN", name="Finland")
    source = MediaAsset.objects.create(
        kind=curated_destination.kind,
        source_kind=curated_destination.source_kind,
        role=curated_destination.role,
        country=finland,
        city=curated_destination.city,
        valid_from=curated_destination.valid_from,
        valid_to=curated_destination.valid_to,
        date_precision=curated_destination.date_precision,
        title=curated_destination.title,
        alt_text=curated_destination.alt_text,
        caption=curated_destination.caption,
        focal_x=curated_destination.focal_x,
        focal_y=curated_destination.focal_y,
        source_name=curated_destination.source_name,
        source_url=curated_destination.source_url,
        source_media_url=curated_destination.source_media_url,
        external_id=curated_destination.external_id,
        creator=curated_destination.creator,
        licence_id=curated_destination.licence_id,
        licence_url=curated_destination.licence_url,
        rights_statement=curated_destination.rights_statement,
        attribution_text=curated_destination.attribution_text,
    )
    attach_media_bytes(source, _png(), filename="unreviewed.png")

    with pytest.raises(CommandError, match="explicitly approved"):
        call_command(
            "build_curated_media_derivatives",
            "--slug",
            curated_destination.slug,
        )

    assert not MediaAsset.objects.filter(derivative_of=source).exists()


@pytest.mark.django_db
def test_curated_derivative_build_fails_closed_on_manifest_source_drift(
    reviewed_source,
    curated_destination,
) -> None:
    reviewed_source.focal_x = Decimal("0.500")
    reviewed_source.save(update_fields=("focal_x", "updated_at"))

    with pytest.raises(CommandError, match="metadata drift"):
        call_command(
            "build_curated_media_derivatives",
            "--slug",
            curated_destination.slug,
        )

    assert not MediaAsset.objects.filter(derivative_of=reviewed_source).exists()
