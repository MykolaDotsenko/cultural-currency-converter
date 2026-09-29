from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from apps.media.models import DatePrecision, MediaKind, MediaRole, MediaSourceKind


_HISTORICAL_EVIDENCE_KINDS = {
    MediaKind.ARCHIVAL_PHOTO,
    MediaKind.ARTWORK,
    MediaKind.HERITAGE_OBJECT,
    MediaKind.MAP,
}


@dataclass(frozen=True, slots=True)
class CuratedMediaSpec:
    slug: str
    country_code: str
    currency_code: str
    city: str
    valid_from: date | None
    valid_to: date | None
    date_precision: str
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


FINLAND_HELSINKI_TRAM_HERO = CuratedMediaSpec(
    slug="finland-helsinki-tram-2026",
    country_code="FI",
    currency_code="",
    city="Helsinki",
    valid_from=date(2026, 5, 24),
    valid_to=date(2026, 5, 24),
    date_precision=DatePrecision.EXACT_DAY,
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


JAPAN_SERIES_D_1000_YEN_1984_2007 = CuratedMediaSpec(
    slug="jpy-series-d-1000-yen-1984-2007",
    country_code="",
    currency_code="JPY",
    city="",
    valid_from=date(1984, 11, 1),
    valid_to=date(2007, 4, 2),
    date_precision=DatePrecision.RANGE,
    role=MediaRole.COMPARISON_THEN,
    kind=MediaKind.HERITAGE_OBJECT,
    source_kind=MediaSourceKind.WIKIMEDIA_COMMONS,
    external_id="commons:Series_D_1K_Yen_Bank_of_Japan_note_-_front.jpg",
    title="Series D 1,000-yen Bank of Japan note",
    alt_text=(
        "Front of a Series D 1,000-yen Bank of Japan note featuring "
        "Natsume Soseki."
    ),
    caption=(
        "Series D 1,000-yen note, first issued 1 November 1984; "
        "issue suspended 2 April 2007."
    ),
    source_name="Wikimedia Commons",
    source_url=(
        "https://commons.wikimedia.org/wiki/"
        "File:Series_D_1K_Yen_Bank_of_Japan_note_-_front.jpg"
    ),
    source_media_url=(
        "https://upload.wikimedia.org/wikipedia/commons/5/5c/"
        "Series_D_1K_Yen_Bank_of_Japan_note_-_front.jpg"
    ),
    creator="Eclipse2009",
    licence_id="Public domain (Japan)",
    licence_url="",
    rights_statement=(
        "Public domain in Japan under Article 13 of the Copyright Act; "
        "see the Wikimedia Commons file page for reuse details."
    ),
    attribution_text="Eclipse2009 · public domain in Japan",
    expected_width=900,
    expected_height=456,
)


CURATED_MEDIA: dict[str, CuratedMediaSpec] = {
    FINLAND_HELSINKI_TRAM_HERO.slug: FINLAND_HELSINKI_TRAM_HERO,
    JAPAN_SERIES_D_1000_YEN_1984_2007.slug: JAPAN_SERIES_D_1000_YEN_1984_2007,
}


def _validate_code(value: str, *, length: int, field_name: str) -> None:
    if not value:
        return
    if len(value) != length or not value.isascii() or not value.isalpha() or value != value.upper():
        raise ValueError(f"{field_name} must be an uppercase ASCII code of length {length}.")


def validate_curated_media_spec(spec: CuratedMediaSpec) -> CuratedMediaSpec:
    _validate_code(spec.country_code, length=2, field_name="country_code")
    _validate_code(spec.currency_code, length=3, field_name="currency_code")
    if spec.role not in MediaRole.values:
        raise ValueError("Curated media role is unknown.")
    if spec.kind not in MediaKind.values:
        raise ValueError("Curated media kind is unknown.")
    if spec.source_kind not in MediaSourceKind.values:
        raise ValueError("Curated media source kind is unknown.")
    if spec.date_precision not in DatePrecision.values:
        raise ValueError("Curated media date precision is unknown.")
    if spec.expected_width < 1 or spec.expected_height < 1:
        raise ValueError("Curated media expected dimensions must be positive.")
    if spec.valid_from and spec.valid_to and spec.valid_from > spec.valid_to:
        raise ValueError("Curated media valid_from cannot be after valid_to.")

    if spec.role in {MediaRole.COUNTRY_HERO, MediaRole.COUNTRY_TEASER}:
        if not spec.country_code:
            raise ValueError("Country hero/teaser curated media requires country_code.")
        if spec.currency_code:
            raise ValueError("Country hero/teaser curated media must remain currency-neutral.")

    if spec.role == MediaRole.COMPARISON_THEN:
        if spec.country_code:
            raise ValueError(
                "comparison_then curated media must be countryless; runtime selection is currency-scoped."
            )
        if not spec.currency_code:
            raise ValueError("comparison_then curated media requires currency_code.")
        if spec.kind not in _HISTORICAL_EVIDENCE_KINDS:
            raise ValueError(
                "comparison_then curated media requires a sourced historical evidence kind."
            )
        if spec.source_kind == MediaSourceKind.GENERATED:
            raise ValueError("comparison_then curated media cannot use a generated source.")
        if spec.date_precision == DatePrecision.UNKNOWN:
            raise ValueError("comparison_then curated media requires explicit temporal precision.")
        if spec.valid_from is None and spec.valid_to is None:
            raise ValueError("comparison_then curated media requires a temporal scope.")

    return spec


def get_curated_media_spec(slug: str) -> CuratedMediaSpec:
    try:
        spec = CURATED_MEDIA[slug]
    except KeyError as exc:
        allowed = ", ".join(sorted(CURATED_MEDIA))
        raise ValueError(f"Unknown curated media slug. Available: {allowed}.") from exc
    return validate_curated_media_spec(spec)
