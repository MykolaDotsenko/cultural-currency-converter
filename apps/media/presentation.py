from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from apps.common.presentation.media_view_models import ImageViewModel
from apps.countries.models import Country, Currency
from apps.media.models import MediaAsset
from apps.media.services import select_published_media


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


def build_media_asset_image_view_model(asset: MediaAsset) -> ImageViewModel:
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
    )


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

    return DisplayMediaSelection(
        image=build_media_asset_image_view_model(stored.asset),
        selection_reason=stored.selection_reason,
        temporal_match_quality=stored.temporal_match_quality,
        authenticity_class=stored.authenticity_class,
        fallback_level=stored.fallback_level,
    )
