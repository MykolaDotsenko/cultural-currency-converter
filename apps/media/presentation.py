from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal

from django.db.models import Q
from django.utils.formats import date_format

from apps.common.presentation.media_view_models import ImageViewModel
from apps.countries.models import Country, Currency
from apps.media.models import DatePrecision, MediaAsset, MediaStatus
from apps.media.services import select_published_media, select_published_media_for_roles


@dataclass(frozen=True, slots=True)
class DisplayMediaSelection:
    image: ImageViewModel
    selection_reason: str
    temporal_match_quality: str
    authenticity_class: str
    fallback_level: int = 0


def _format_focal_percent(value: Decimal) -> str:
    text = format(value * Decimal("100"), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return f"{text}%"


def _focal_position(asset: MediaAsset) -> str:
    if asset.focal_x is None and asset.focal_y is None:
        return ""

    focal_x = asset.focal_x if asset.focal_x is not None else Decimal("0.5")
    focal_y = asset.focal_y if asset.focal_y is not None else Decimal("0.5")
    return f"{_format_focal_percent(focal_x)} {_format_focal_percent(focal_y)}"


def _temporal_label(asset: MediaAsset) -> str:
    if asset.valid_from is None and asset.valid_to is None:
        return ""

    def format_date(value: date) -> str:
        if asset.date_precision == DatePrecision.YEAR:
            return str(value.year)
        if asset.date_precision == DatePrecision.MONTH:
            return value.strftime("%B %Y")
        if asset.date_precision == DatePrecision.DECADE:
            return f"{value.year // 10 * 10}s"
        if asset.date_precision == DatePrecision.ERA:
            return str(value.year)
        return value.isoformat()

    if asset.valid_from and asset.valid_to:
        start_text = format_date(asset.valid_from)
        end_text = format_date(asset.valid_to)
        scope = start_text if start_text == end_text else f"{start_text}–{end_text}"
    elif asset.valid_from:
        scope = f"{format_date(asset.valid_from)} onward"
    else:
        scope = f"through {format_date(asset.valid_to)}"

    precision = asset.get_date_precision_display()
    return f"{scope} · {precision}"


def _evidence_label(asset: MediaAsset) -> str:
    if asset.generated_by_ai:
        return "AI-generated editorial illustration"
    labels = {
        "archival_photo": "Archival sourced evidence",
        "heritage_object": "Sourced heritage object",
        "artwork": "Sourced artwork",
        "map": "Sourced map",
        "contemporary_photo": "Sourced contemporary photograph",
    }
    return labels.get(asset.kind, "Sourced managed media")


def _temporal_match_label(quality: str) -> str:
    labels = {
        "exact": "Exact-date reviewed match",
        "month": "Month-level reviewed match",
        "year": "Year-level reviewed match",
        "decade": "Decade-level reviewed match",
        "range": "Reviewed period match",
        "era": "Reviewed era match",
        "unknown": "Historical date match not specified",
        "not_requested": "",
    }
    return labels.get(quality, "")


def _with_selection_provenance(
    image: ImageViewModel,
    *,
    temporal_match_quality: str,
    authenticity_class: str,
) -> ImageViewModel:
    evidence_label = image.evidence_label
    if authenticity_class == "ai_generated_illustration":
        evidence_label = "AI-generated editorial illustration"
    elif authenticity_class == "sourced_media" and not evidence_label:
        evidence_label = "Sourced managed media"
    return replace(
        image,
        evidence_label=evidence_label,
        temporal_match_label=_temporal_match_label(temporal_match_quality),
    )


def _responsive_srcsets(assets: tuple[MediaAsset, ...]) -> dict[int, str]:
    source_ids: set[int] = set()
    for asset in assets:
        if asset.pk is None:
            continue
        source_ids.add(asset.derivative_of_id or asset.pk)
    if not source_ids:
        return {}

    variants = (
        MediaAsset.objects.filter(status=MediaStatus.PUBLISHED)
        .filter(Q(pk__in=source_ids) | Q(derivative_of_id__in=source_ids))
        .exclude(storage_file="")
        .order_by("variant_width", "-published_at", "-pk")
    )

    derivatives: dict[int, dict[int, str]] = {source_id: {} for source_id in source_ids}
    roots: dict[int, tuple[int, str]] = {}
    for variant in variants:
        source_id = variant.derivative_of_id or variant.pk
        if source_id not in derivatives:
            continue

        width = variant.variant_width or variant.width
        if not width:
            continue

        if variant.derivative_of_id:
            if width not in derivatives[source_id]:
                derivatives[source_id][width] = variant.storage_file.url
        elif source_id not in roots:
            roots[source_id] = (width, variant.storage_file.url)

    families: dict[int, dict[int, str]] = {}
    for source_id in source_ids:
        family = derivatives[source_id]
        if family:
            families[source_id] = family
        elif source_id in roots:
            width, url = roots[source_id]
            families[source_id] = {width: url}

    return {
        source_id: ", ".join(f"{url} {width}w" for width, url in sorted(sources.items()))
        for source_id, sources in families.items()
        if len(sources) >= 2
    }


def _responsive_srcset(asset: MediaAsset) -> str:
    if asset.pk is None:
        return ""
    source_id = asset.derivative_of_id or asset.pk
    return _responsive_srcsets((asset,)).get(source_id, "")


def _build_media_asset_image_view_model(
    asset: MediaAsset,
    *,
    responsive_srcset: str,
) -> ImageViewModel:
    if not asset.is_published or not asset.storage_file:
        raise ValueError("Only published managed media can be rendered.")

    return ImageViewModel(
        src=asset.storage_file.url,
        ratio=asset.aspect_ratio or f"{asset.width} / {asset.height}",
        alt="" if asset.is_decorative else asset.alt_text,
        decorative=asset.is_decorative,
        kind=asset.kind,
        label=asset.title,
        width=asset.width or 1,
        height=asset.height or 1,
        focal_position=_focal_position(asset),
        srcset=responsive_srcset,
        sizes="100vw" if responsive_srcset else "",
        caption=asset.caption,
        attribution_text=asset.attribution_text,
        source_url=asset.source_url,
        licence_id=asset.licence_id,
        licence_url=asset.licence_url,
        change_note=(
            ""
            if asset.generated_by_ai
            else (
                "Resized and optimized for web."
                if asset.derivative_of_id
                else "Managed copy normalized for web."
            )
        ),
        authenticity_label=asset.ai_label if asset.generated_by_ai else "",
        temporal_label=_temporal_label(asset),
        source_name=asset.source_name,
        creator=asset.creator,
        rights_statement=asset.rights_statement,
        original_source_url=asset.source_media_url,
        retrieved_label=(
            date_format(asset.source_retrieved_at, "j M Y")
            if asset.source_retrieved_at is not None
            else ""
        ),
        evidence_label=_evidence_label(asset),
    )


def build_media_asset_image_view_model(asset: MediaAsset) -> ImageViewModel:
    return _build_media_asset_image_view_model(
        asset,
        responsive_srcset=_responsive_srcset(asset),
    )


def select_media_for_display_roles(
    *,
    roles: tuple[str, ...],
    country: Country | None = None,
    currency: Currency | None = None,
    target_date: date | None = None,
    aspect_ratios: dict[str, str] | None = None,
) -> dict[str, DisplayMediaSelection]:
    stored_by_role = select_published_media_for_roles(
        roles=roles,
        country=country,
        currency=currency,
        target_date=target_date,
        aspect_ratios=aspect_ratios,
    )
    if not stored_by_role:
        return {}

    assets = tuple(selection.asset for selection in stored_by_role.values())
    srcsets = _responsive_srcsets(assets)
    displayed: dict[str, DisplayMediaSelection] = {}
    for role, stored in stored_by_role.items():
        asset = stored.asset
        if asset.pk is None:
            continue
        source_id = asset.derivative_of_id or asset.pk
        try:
            image = _build_media_asset_image_view_model(
                asset,
                responsive_srcset=srcsets.get(source_id, ""),
            )
        except ValueError:
            continue
        image = _with_selection_provenance(
            image,
            temporal_match_quality=stored.temporal_match_quality,
            authenticity_class=stored.authenticity_class,
        )
        displayed[role] = DisplayMediaSelection(
            image=image,
            selection_reason=stored.selection_reason,
            temporal_match_quality=stored.temporal_match_quality,
            authenticity_class=stored.authenticity_class,
            fallback_level=stored.fallback_level,
        )
    return displayed


def select_media_for_display(
    *,
    role: str,
    country: Country | None = None,
    currency: Currency | None = None,
    target_date: date | None = None,
    aspect_ratio: str | None = None,
) -> DisplayMediaSelection | None:
    """Return reviewed managed media, or no image when nothing meets the bar."""

    stored = select_published_media(
        role=role,
        country=country,
        currency=currency,
        target_date=target_date,
        aspect_ratio=aspect_ratio,
    )
    if stored is None:
        return None

    image = _with_selection_provenance(
        build_media_asset_image_view_model(stored.asset),
        temporal_match_quality=stored.temporal_match_quality,
        authenticity_class=stored.authenticity_class,
    )
    return DisplayMediaSelection(
        image=image,
        selection_reason=stored.selection_reason,
        temporal_match_quality=stored.temporal_match_quality,
        authenticity_class=stored.authenticity_class,
        fallback_level=stored.fallback_level,
    )
