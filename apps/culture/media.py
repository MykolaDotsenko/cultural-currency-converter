from __future__ import annotations

import logging
from dataclasses import dataclass

from django.db import DatabaseError

from apps.common.presentation.media_view_models import ImageViewModel
from apps.countries.models import Country
from apps.media.models import MediaRole
from apps.media.presentation import select_media_for_display_roles

logger = logging.getLogger("cultural_currency.culture")


@dataclass(frozen=True, slots=True)
class DestinationMedia:
    hero: ImageViewModel | None = None
    everyday_value: ImageViewModel | None = None
    payment_culture: ImageViewModel | None = None
    local_detail: ImageViewModel | None = None


_DESTINATION_MEDIA_ROLES = (
    MediaRole.COUNTRY_HERO,
    MediaRole.EVERYDAY_VALUE,
    MediaRole.PAYMENT_CULTURE,
    MediaRole.LOCAL_DETAIL,
)


def select_destination_media(country_code: str) -> DestinationMedia:
    """Return optional reviewed destination media without making conversion depend on it."""

    normalized = country_code.upper().strip()
    if not normalized:
        return DestinationMedia()

    try:
        country = Country.objects.filter(iso2=normalized).first()
        if country is None:
            return DestinationMedia()

        selections = select_media_for_display_roles(
            roles=_DESTINATION_MEDIA_ROLES,
            country=country,
            aspect_ratios={
                MediaRole.COUNTRY_HERO: "16 / 9",
                MediaRole.EVERYDAY_VALUE: "4 / 5",
                MediaRole.PAYMENT_CULTURE: "4 / 5",
                MediaRole.LOCAL_DETAIL: "3 / 2",
            },
        )
    except (DatabaseError, ValueError) as exc:
        logger.warning(
            "Destination media lookup failed",
            extra={
                "culture.country": normalized,
                "error_code": exc.__class__.__name__,
            },
        )
        return DestinationMedia()

    def image(role: str) -> ImageViewModel | None:
        selection = selections.get(role)
        return selection.image if selection is not None else None

    return DestinationMedia(
        hero=image(MediaRole.COUNTRY_HERO),
        everyday_value=image(MediaRole.EVERYDAY_VALUE),
        payment_culture=image(MediaRole.PAYMENT_CULTURE),
        local_detail=image(MediaRole.LOCAL_DETAIL),
    )


def select_destination_hero_image(country_code: str) -> ImageViewModel | None:
    """Compatibility wrapper for callers that only need destination hero photography."""

    return select_destination_media(country_code).hero
