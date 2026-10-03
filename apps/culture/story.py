from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from django.utils.formats import date_format

from apps.culture.models import StoryDatePrecision, StoryMoment
from apps.culture.provenance import is_valid_provenance_url
from apps.culture.services import currency_era_links, select_story_moments


@dataclass(frozen=True, slots=True)
class StoryRequest:
    source_country: str
    source_currency: str
    destination_country: str
    destination_currency: str
    selected_date: date
    historical: bool


@dataclass(frozen=True, slots=True)
class StorySourceRef:
    label: str
    url: str
    source_kind: str = ""
    external_id: str = ""
    published_label: str = ""
    retrieved_label: str = ""
    verified_label: str = ""


@dataclass(frozen=True, slots=True)
class StoryChapter:
    kind: str
    label: str
    title: str
    body: str
    source_refs: tuple[StorySourceRef, ...]
    temporal_scope: str
    temporal_precision: str
    causal_support: bool
    causal_support_note: str
    target_date: date | None
    relevance: int


@dataclass(frozen=True, slots=True)
class StoryComposition:
    chapters: tuple[StoryChapter, ...]
    status: str
    selected_date: date
    historical: bool

    @property
    def currency_era_chapters(self) -> tuple[StoryChapter, ...]:
        return tuple(chapter for chapter in self.chapters if chapter.kind.endswith("_currency_era"))

    @property
    def historical_moment_chapters(self) -> tuple[StoryChapter, ...]:
        return tuple(chapter for chapter in self.chapters if chapter.kind == "historical_moment")


def compose_story(request: StoryRequest) -> StoryComposition:
    country_codes = tuple(
        code for code in (request.source_country, request.destination_country) if code
    )
    currency_codes = tuple(
        code for code in (request.source_currency, request.destination_currency) if code
    )

    era_links = currency_era_links(
        country_codes=country_codes,
        currency_codes=currency_codes,
        selected_date=request.selected_date,
    )
    moments = select_story_moments(
        country_codes=country_codes,
        currency_codes=currency_codes,
        selected_date=request.selected_date,
        historical=request.historical,
    )

    chapters: list[StoryChapter] = []
    side_pairs = (
        ("source", request.source_country, request.source_currency),
        ("destination", request.destination_country, request.destination_currency),
    )
    for side, country_code, currency_code in side_pairs:
        if not country_code or not currency_code:
            continue
        link = next(
            (
                candidate
                for candidate in era_links
                if candidate.country.iso2 == country_code
                and candidate.currency.code == currency_code
            ),
            None,
        )
        if link is None:
            continue
        chapters.append(_currency_era_chapter(link, side=side))

    for moment in moments:
        chapters.append(_moment_chapter(moment))

    if not chapters:
        status = "unavailable"
    elif len(chapters) == 1:
        status = "partial"
    else:
        status = "full"

    return StoryComposition(
        chapters=tuple(chapters),
        status=status,
        selected_date=request.selected_date,
        historical=request.historical,
    )


def _currency_era_chapter(link, *, side: str) -> StoryChapter:
    date_text = _range_text(link.valid_from, link.valid_to)
    role_text = (
        "primary currency relationship" if link.is_primary else "recorded currency relationship"
    )
    body = (
        f"{link.country.name} records {link.currency.name} ({link.currency.code}) as a "
        f"{role_text}{date_text}."
    )
    source_refs: tuple[StorySourceRef, ...] = ()
    if is_valid_provenance_url(link.source):
        source_refs = (StorySourceRef(label="Currency relationship source", url=link.source),)

    return StoryChapter(
        kind=f"{side}_currency_era",
        label=f"{side.title()} currency era",
        title=f"{link.country.name} · {link.currency.code}",
        body=body,
        source_refs=source_refs,
        temporal_scope=_temporal_scope(link.valid_from, link.valid_to),
        temporal_precision="Canonical currency period",
        causal_support=False,
        causal_support_note="",
        target_date=link.valid_from,
        relevance=100,
    )


def _moment_chapter(moment: StoryMoment) -> StoryChapter:
    return StoryChapter(
        kind="historical_moment",
        label="Sourced money history",
        title=moment.title,
        body=moment.summary,
        source_refs=(
            StorySourceRef(
                label=moment.source_name,
                url=moment.source_url,
                source_kind=moment.get_source_kind_display(),
                external_id=moment.external_id,
                published_label=(
                    date_format(moment.source_published_at, "j M Y")
                    if moment.source_published_at is not None
                    else ""
                ),
                retrieved_label=(
                    date_format(moment.source_retrieved_at, "j M Y")
                    if moment.source_retrieved_at is not None
                    else ""
                ),
                verified_label=(
                    date_format(moment.verified_at, "j M Y")
                    if moment.verified_at is not None
                    else ""
                ),
            ),
        ),
        temporal_scope=_temporal_scope(
            moment.start_date,
            moment.end_date,
            precision=moment.date_precision,
        ),
        temporal_precision=_precision_label(moment.date_precision),
        causal_support=moment.supports_causality,
        causal_support_note=moment.causal_support_note.strip(),
        target_date=moment.start_date or moment.end_date,
        relevance=moment.relevance_weight,
    )


def _range_text(start: date | None, end: date | None) -> str:
    if start and end:
        if start == end:
            return f" on {start.isoformat()}"
        return f" from {start.isoformat()} through {end.isoformat()}"
    if start:
        return f" from {start.isoformat()} onward"
    if end:
        return f" through {end.isoformat()}"
    return ""


def _precision_label(precision: str) -> str:
    labels = {
        StoryDatePrecision.EXACT_DAY: "Exact day",
        StoryDatePrecision.MONTH: "Month precision",
        StoryDatePrecision.YEAR: "Year precision",
        StoryDatePrecision.RANGE: "Reviewed range",
        StoryDatePrecision.ERA: "Reviewed era",
        StoryDatePrecision.UNKNOWN: "Precision not specified",
    }
    return labels.get(precision, "Precision not specified")


def _format_temporal_date(value: date, *, precision: str) -> str:
    if precision == StoryDatePrecision.YEAR:
        return str(value.year)
    if precision == StoryDatePrecision.MONTH:
        return value.strftime("%B %Y")
    if precision == StoryDatePrecision.ERA:
        return str(value.year)
    return value.isoformat()


def _temporal_scope(
    start: date | None,
    end: date | None,
    *,
    precision: str = StoryDatePrecision.EXACT_DAY,
) -> str:
    if start and end:
        start_text = _format_temporal_date(start, precision=precision)
        end_text = _format_temporal_date(end, precision=precision)
        return start_text if start == end else f"{start_text}–{end_text}"
    if start:
        return f"{_format_temporal_date(start, precision=precision)} onward"
    if end:
        return f"through {_format_temporal_date(end, precision=precision)}"
    return "undated sourced context"
