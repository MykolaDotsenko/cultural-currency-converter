from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from apps.countries.models import Country, Currency
from apps.culture.models import StoryMoment
from apps.culture.provenance import is_valid_provenance_url
from apps.culture.services import (
    currency_era_links,
    currency_history_links,
    select_currency_history_moments,
    select_story_moments,
)


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


@dataclass(frozen=True, slots=True)
class StoryChapter:
    kind: str
    label: str
    title: str
    body: str
    source_refs: tuple[StorySourceRef, ...]
    temporal_scope: str
    relevance: int


@dataclass(frozen=True, slots=True)
class StoryComposition:
    chapters: tuple[StoryChapter, ...]
    status: str
    selected_date: date
    historical: bool


@dataclass(frozen=True, slots=True)
class CurrencyHistoryRequest:
    country_code: str
    currency_code: str
    selected_date: date
    historical: bool


@dataclass(frozen=True, slots=True)
class CurrencyHistoryEra:
    currency_code: str
    currency_name: str
    label: str
    temporal_scope: str
    selected: bool
    active_on_selected_date: bool
    source_refs: tuple[StorySourceRef, ...]


@dataclass(frozen=True, slots=True)
class CurrencyHistoryMoment:
    label: str
    title: str
    body: str
    temporal_scope: str
    source_refs: tuple[StorySourceRef, ...]


@dataclass(frozen=True, slots=True)
class CurrencyHistoryComposition:
    country_code: str
    country_name: str
    selected_currency_code: str
    selected_currency_name: str
    selected_date: date
    historical: bool
    eras: tuple[CurrencyHistoryEra, ...]
    moments: tuple[CurrencyHistoryMoment, ...]
    active_primary_currency_code: str
    active_primary_currency_name: str
    selected_relationship_active: bool
    status: str


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


def compose_currency_history(request: CurrencyHistoryRequest) -> CurrencyHistoryComposition:
    country = Country.objects.filter(iso2=request.country_code.upper()).first()
    currency = Currency.objects.filter(code=request.currency_code.upper()).first()
    if country is None or currency is None:
        raise ValueError("Currency history requires known country and currency metadata.")

    links = currency_history_links(
        country_code=country.iso2,
        selected_currency_code=currency.code,
        selected_date=request.selected_date,
    )

    eras: list[CurrencyHistoryEra] = []
    active_primary_currency_code = ""
    active_primary_currency_name = ""
    selected_relationship_active = False

    for link in links:
        active_on_selected_date = _relationship_active_on(link, request.selected_date)
        selected = link.currency.code == currency.code
        if link.is_primary and active_on_selected_date:
            active_primary_currency_code = link.currency.code
            active_primary_currency_name = link.currency.name
        if selected and active_on_selected_date:
            selected_relationship_active = True

        if selected and active_on_selected_date:
            label = "Selected currency · primary on this date" if link.is_primary else "Selected currency"
        elif active_on_selected_date and link.is_primary:
            label = "Primary currency on this date"
        elif selected:
            label = "Selected historical currency"
        elif link.is_primary:
            label = "Previous primary currency"
        else:
            label = "Recorded currency relationship"

        source_refs: tuple[StorySourceRef, ...] = ()
        if is_valid_provenance_url(link.source):
            source_refs = (
                StorySourceRef(
                    label=f"{link.country.name} currency relationship source",
                    url=link.source,
                ),
            )

        eras.append(
            CurrencyHistoryEra(
                currency_code=link.currency.code,
                currency_name=link.currency.name,
                label=label,
                temporal_scope=_temporal_scope(link.valid_from, link.valid_to),
                selected=selected,
                active_on_selected_date=active_on_selected_date,
                source_refs=source_refs,
            )
        )

    moment_currency_codes = tuple(
        dict.fromkeys([*(era.currency_code for era in eras), currency.code])
    )
    moments = tuple(
        _currency_history_moment(moment)
        for moment in select_currency_history_moments(
            country_code=country.iso2,
            currency_codes=moment_currency_codes,
            selected_date=request.selected_date,
        )
    )

    if eras and moments:
        status = "full"
    elif eras or moments:
        status = "partial"
    else:
        status = "unavailable"

    return CurrencyHistoryComposition(
        country_code=country.iso2,
        country_name=country.name,
        selected_currency_code=currency.code,
        selected_currency_name=currency.name,
        selected_date=request.selected_date,
        historical=request.historical,
        eras=tuple(eras),
        moments=moments,
        active_primary_currency_code=active_primary_currency_code,
        active_primary_currency_name=active_primary_currency_name,
        selected_relationship_active=selected_relationship_active,
        status=status,
    )


def _relationship_active_on(link, selected_date: date) -> bool:
    return (
        (link.valid_from is None or link.valid_from <= selected_date)
        and (link.valid_to is None or link.valid_to >= selected_date)
    )


def _currency_history_moment(moment: StoryMoment) -> CurrencyHistoryMoment:
    return CurrencyHistoryMoment(
        label=moment.get_category_display(),
        title=moment.title,
        body=moment.summary,
        temporal_scope=_temporal_scope(moment.start_date, moment.end_date),
        source_refs=(StorySourceRef(label=moment.source_name, url=moment.source_url),),
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
        relevance=100,
    )


def _moment_chapter(moment: StoryMoment) -> StoryChapter:
    return StoryChapter(
        kind="historical_moment",
        label="Sourced money history",
        title=moment.title,
        body=moment.summary,
        source_refs=(StorySourceRef(label=moment.source_name, url=moment.source_url),),
        temporal_scope=_temporal_scope(moment.start_date, moment.end_date),
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


def _temporal_scope(start: date | None, end: date | None) -> str:
    if start and end:
        return start.isoformat() if start == end else f"{start.isoformat()}–{end.isoformat()}"
    if start:
        return f"{start.isoformat()} onward"
    if end:
        return f"through {end.isoformat()}"
    return "undated sourced context"
