from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from apps.media.models import DatePrecision, MediaKind, MediaRole, MediaSourceKind


@dataclass(frozen=True, slots=True)
class CuratedMediaSpec:
    slug: str
    country_code: str
    city: str
    role: str
    kind: str
    source_kind: str
    external_id: str
    title: str
    alt_text: str
    caption: str
    source_name: str
    source_url: str
    source_media_url: str
    creator: str
    licence_id: str
    licence_url: str
    rights_statement: str
    attribution_text: str
    expected_width: int
    expected_height: int
    currency_code: str = ""
    valid_from: date | None = None
    valid_to: date | None = None
    date_precision: str = DatePrecision.UNKNOWN


FINLAND_HELSINKI_TRAM_HERO = CuratedMediaSpec(
    slug="finland-helsinki-tram-2026",
    country_code="FI",
    city="Helsinki",
    role=MediaRole.COUNTRY_HERO,
    kind=MediaKind.CONTEMPORARY_PHOTO,
    source_kind=MediaSourceKind.WIKIMEDIA_COMMONS,
    external_id="commons:Helsinki_tram_line_4_Aleksanterinkatu_2026-05-24",
    title="Helsinki tram on Aleksanterinkatu, May 2026",
    alt_text=(
        "A Helsinki tram on line 4 travelling along Aleksanterinkatu in central Helsinki "
        "on a May afternoon."
    ),
    caption="Helsinki tram on Aleksanterinkatu, photographed 24 May 2026.",
    source_name="Wikimedia Commons",
    source_url=(
        "https://commons.wikimedia.org/wiki/"
        "File:Helsinki_tram_on_line_4_on_Aleksanterinkatu_in_May_2026.jpg"
    ),
    source_media_url=(
        "https://upload.wikimedia.org/wikipedia/commons/6/60/"
        "Helsinki_tram_on_line_4_on_Aleksanterinkatu_in_May_2026.jpg"
    ),
    creator="JIP",
    licence_id="CC BY-SA 4.0",
    licence_url="https://creativecommons.org/licenses/by-sa/4.0/",
    rights_statement="Creative Commons Attribution-ShareAlike 4.0 International",
    attribution_text="JIP · CC BY-SA 4.0",
    expected_width=4608,
    expected_height=3456,
)



JPY_AKIHABARA_1995_THEN = CuratedMediaSpec(
    slug="jpy-akihabara-1995",
    country_code="",
    currency_code="JPY",
    city="Tokyo",
    role=MediaRole.COMPARISON_THEN,
    kind=MediaKind.ARCHIVAL_PHOTO,
    source_kind=MediaSourceKind.WIKIMEDIA_COMMONS,
    external_id="commons:Akihabara_station_south_street_1995_Danny_Choo",
    title="Akihabara Station south street, identified as 1995",
    alt_text=(
        "A sourced archival view of the street outside Akihabara Station in Tokyo, "
        "identified by the source as 1995."
    ),
    caption=(
        "Akihabara Station south street, Tokyo; the source identifies the scene as 1995."
    ),
    source_name="Wikimedia Commons",
    source_url=(
        "https://commons.wikimedia.org/wiki/"
        "File:Akihabara_station_south_street,_1995,_(by_Danny_Choo).jpg"
    ),
    source_media_url=(
        "https://upload.wikimedia.org/wikipedia/commons/0/07/"
        "Akihabara_station_south_street%2C_1995%2C_%28by_Danny_Choo%29.jpg"
    ),
    creator="Danny Choo",
    licence_id="CC BY-SA 2.0",
    licence_url="https://creativecommons.org/licenses/by-sa/2.0/",
    rights_statement="Creative Commons Attribution-ShareAlike 2.0 Generic",
    attribution_text="Danny Choo · CC BY-SA 2.0",
    expected_width=930,
    expected_height=622,
    valid_from=date(1995, 1, 1),
    valid_to=date(1995, 12, 31),
    date_precision=DatePrecision.YEAR,
)


CURATED_MEDIA: dict[str, CuratedMediaSpec] = {
    FINLAND_HELSINKI_TRAM_HERO.slug: FINLAND_HELSINKI_TRAM_HERO,
    JPY_AKIHABARA_1995_THEN.slug: JPY_AKIHABARA_1995_THEN,
}


def get_curated_media_spec(slug: str) -> CuratedMediaSpec:
    try:
        return CURATED_MEDIA[slug]
    except KeyError as exc:
        allowed = ", ".join(sorted(CURATED_MEDIA))
        raise ValueError(f"Unknown curated media slug. Available: {allowed}.") from exc
