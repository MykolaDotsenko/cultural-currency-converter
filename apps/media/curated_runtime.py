from __future__ import annotations

from apps.media.curated import CuratedMediaSpec
from apps.media.models import MediaAsset, MediaStatus

REVIEWED_SOURCE_STATUSES = frozenset(
    {
        MediaStatus.APPROVED,
        MediaStatus.PUBLISHED,
    }
)


def curated_source_contract_error(
    source: MediaAsset,
    spec: CuratedMediaSpec,
) -> str:
    country_code = source.country.iso2 if source.country_id else ""
    currency_code = source.currency.code if source.currency_id else ""

    expected = (
        None,
        spec.source_kind,
        spec.external_id,
        spec.role,
        spec.kind,
        spec.country_code,
        spec.currency_code,
        spec.city,
        spec.valid_from,
        spec.valid_to,
        spec.date_precision,
        spec.focal_x,
        spec.focal_y,
        spec.source_name,
        spec.source_url,
        spec.source_media_url,
        spec.creator,
        spec.licence_id,
        spec.licence_url,
        spec.rights_statement,
        spec.attribution_text,
        spec.expected_width,
        spec.expected_height,
        False,
    )
    actual = (
        source.derivative_of_id,
        source.source_kind,
        source.external_id,
        source.role,
        source.kind,
        country_code,
        currency_code,
        source.city,
        source.valid_from,
        source.valid_to,
        source.date_precision,
        source.focal_x,
        source.focal_y,
        source.source_name,
        source.source_url,
        source.source_media_url,
        source.creator,
        source.licence_id,
        source.licence_url,
        source.rights_statement,
        source.attribution_text,
        source.width,
        source.height,
        source.generated_by_ai,
    )
    if actual != expected:
        return (
            f"Curated source metadata/provenance drift for {spec.slug}: "
            f"expected={expected!r} actual={actual!r}."
        )
    if not source.storage_file or not source.content_hash:
        return f"Curated source {spec.slug} is missing managed bytes or content identity."
    return ""


def curated_derivative_contract_error(
    derivative: MediaAsset,
    *,
    source: MediaAsset,
    spec: CuratedMediaSpec,
) -> str:
    width = derivative.variant_width
    if width is None or width not in spec.responsive_widths:
        return f"Curated derivative width is outside the reviewed plan for {spec.slug}."
    if derivative.width != width:
        return (
            f"Curated derivative pixel width drift for {spec.slug} at {width}px: "
            f"actual={derivative.width!r}."
        )
    if not source.width or not source.height:
        return f"Curated source {spec.slug} has incomplete intrinsic dimensions."

    expected_height = max(1, round(source.height * width / source.width))
    if derivative.height != expected_height:
        return (
            f"Curated derivative pixel height drift for {spec.slug} at {width}px: "
            f"expected={expected_height} actual={derivative.height!r}."
        )
    if not derivative.storage_file or not derivative.content_hash:
        return f"Curated derivative {spec.slug} at {width}px is missing managed bytes."

    country_code = derivative.country.iso2 if derivative.country_id else ""
    currency_code = derivative.currency.code if derivative.currency_id else ""
    expected = (
        source.pk,
        source.source_kind,
        "",
        source.role,
        source.kind,
        spec.country_code,
        spec.currency_code,
        source.city,
        source.valid_from,
        source.valid_to,
        source.date_precision,
        source.focal_x,
        source.focal_y,
        source.source_name,
        source.source_url,
        source.source_media_url,
        source.creator,
        source.licence_id,
        source.licence_url,
        source.rights_statement,
        source.attribution_text,
        source.generated_by_ai,
    )
    actual = (
        derivative.derivative_of_id,
        derivative.source_kind,
        derivative.external_id,
        derivative.role,
        derivative.kind,
        country_code,
        currency_code,
        derivative.city,
        derivative.valid_from,
        derivative.valid_to,
        derivative.date_precision,
        derivative.focal_x,
        derivative.focal_y,
        derivative.source_name,
        derivative.source_url,
        derivative.source_media_url,
        derivative.creator,
        derivative.licence_id,
        derivative.licence_url,
        derivative.rights_statement,
        derivative.attribution_text,
        derivative.generated_by_ai,
    )
    if actual != expected:
        return f"Curated derivative metadata/provenance drift for {spec.slug} at {width}px."
    if derivative.status in {MediaStatus.REJECTED, MediaStatus.RETIRED}:
        return (
            f"Curated derivative {spec.slug} at {width}px is {derivative.status}; "
            "resolve the reviewed record explicitly."
        )
    return ""
