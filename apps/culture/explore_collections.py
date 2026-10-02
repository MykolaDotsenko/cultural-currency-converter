from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from django.utils import timezone

from apps.countries.models import CountryCurrency
from apps.culture.city_profile import build_city_money_profile
from apps.culture.explore import ExploreDestination, build_explore_destinations
from apps.culture.models import CulturalProfile, StoryMoment
from apps.culture.provenance import is_valid_provenance_url
from apps.culture.services import build_destination_context


class ExploreCollectionKind(StrEnum):
    CITY_MONEY_PROFILES = "city_money_profiles"
    CURRENCY_STORIES = "currency_stories"
    CASH_CARD_BEHAVIOUR = "cash_card_behaviour"
    SHARED_CURRENCY_COUNTRIES = "shared_currency_countries"
    RECENTLY_REVIEWED_DESTINATIONS = "recently_reviewed_destinations"


@dataclass(frozen=True, slots=True)
class ExploreCollectionEvidence:
    source_name: str
    source_url: str
    evidence_date: date | None = None


@dataclass(frozen=True, slots=True)
class ExploreCollectionItem:
    """One neutral discovery item backed by explicit reviewed evidence."""

    key: str
    title: str
    summary: str
    country_codes: tuple[str, ...]
    currency_codes: tuple[str, ...]
    evidence: tuple[ExploreCollectionEvidence, ...]
    reviewed_on: date | None = None
    city_slug: str = ""

    @property
    def has_provenance(self) -> bool:
        return bool(self.evidence) and all(
            is_valid_provenance_url(item.source_url) for item in self.evidence
        )


@dataclass(frozen=True, slots=True)
class ExploreCollection:
    kind: ExploreCollectionKind
    slug: str
    title: str
    description: str
    items: tuple[ExploreCollectionItem, ...]


_COLLECTION_ORDER: tuple[ExploreCollectionKind, ...] = (
    ExploreCollectionKind.CITY_MONEY_PROFILES,
    ExploreCollectionKind.CURRENCY_STORIES,
    ExploreCollectionKind.CASH_CARD_BEHAVIOUR,
    ExploreCollectionKind.SHARED_CURRENCY_COUNTRIES,
    ExploreCollectionKind.RECENTLY_REVIEWED_DESTINATIONS,
)


def _dedupe_evidence(
    values: tuple[ExploreCollectionEvidence, ...],
) -> tuple[ExploreCollectionEvidence, ...]:
    seen: set[str] = set()
    result: list[ExploreCollectionEvidence] = []
    for value in values:
        if value.source_url in seen or not is_valid_provenance_url(value.source_url):
            continue
        seen.add(value.source_url)
        result.append(value)
    return tuple(result)


def _city_profile_items(
    *,
    destinations: tuple[ExploreDestination, ...],
    as_of: date,
    limit: int,
) -> tuple[ExploreCollectionItem, ...]:
    items: list[ExploreCollectionItem] = []
    for destination in destinations:
        if not destination.is_city_scope:
            continue
        profile = build_city_money_profile(
            country_code=destination.country_code,
            city_slug=destination.city_slug,
            as_of=as_of,
        )
        if profile is None:
            continue
        direct_prices = tuple(
            price for price in profile.prices if price.city_slug == profile.city_slug
        )
        evidence = _dedupe_evidence(
            tuple(
                ExploreCollectionEvidence(
                    source_name=price.source_name,
                    source_url=price.source_url,
                    evidence_date=price.observed_at,
                )
                for price in direct_prices
            )
        )
        if not evidence:
            continue
        reviewed_on = max(item.evidence_date for item in evidence if item.evidence_date is not None)
        items.append(
            ExploreCollectionItem(
                key=f"city:{profile.country_code}:{profile.city_slug}",
                title=profile.scope_label,
                summary=(
                    f"{profile.direct_price_count} direct reviewed city money "
                    f"anchor{'s' if profile.direct_price_count != 1 else ''}; "
                    f"current currency {profile.currency_code}."
                ),
                country_codes=(profile.country_code,),
                currency_codes=(profile.currency_code,),
                city_slug=profile.city_slug,
                reviewed_on=reviewed_on,
                evidence=evidence,
            )
        )
    items.sort(key=lambda item: (item.title.casefold(), item.key))
    return tuple(items[:limit])


def _story_items(*, limit: int) -> tuple[ExploreCollectionItem, ...]:
    queryset = (
        StoryMoment.objects.published()
        .filter(verified_at__isnull=False)
        .exclude(source_name="")
        .exclude(source_url="")
        .prefetch_related("countries", "currencies")
        .order_by("title", "pk")
    )
    items: list[ExploreCollectionItem] = []
    for moment in queryset:
        if not is_valid_provenance_url(moment.source_url):
            continue
        countries = tuple(sorted(country.iso2 for country in moment.countries.all()))
        currencies = tuple(sorted(currency.code for currency in moment.currencies.all()))
        if not countries and not currencies:
            continue
        items.append(
            ExploreCollectionItem(
                key=f"story:{moment.pk}",
                title=moment.title,
                summary=moment.summary,
                country_codes=countries,
                currency_codes=currencies,
                reviewed_on=moment.verified_at.date(),
                evidence=(
                    ExploreCollectionEvidence(
                        source_name=moment.source_name,
                        source_url=moment.source_url,
                        evidence_date=moment.source_published_at or moment.verified_at.date(),
                    ),
                ),
            )
        )
        if len(items) >= limit:
            break
    return tuple(items)


def _payment_items(*, as_of: date, limit: int) -> tuple[ExploreCollectionItem, ...]:
    links = {
        link.country_id: link
        for link in (
            CountryCurrency.objects.current(as_of).primary().select_related("country", "currency")
        )
    }
    profiles = (
        CulturalProfile.objects.filter(
            country_id__in=links,
            country__is_active=True,
            is_published=True,
            verified_at__isnull=False,
        )
        .exclude(source_name="")
        .exclude(source_url="")
        .select_related("country")
        .order_by("country__name", "country__iso2")
    )
    items: list[ExploreCollectionItem] = []
    for profile in profiles:
        if not is_valid_provenance_url(profile.source_url):
            continue
        if not any(
            value.strip()
            for value in (
                profile.payment_customs,
                profile.cash_usage,
                profile.atm_notes,
                profile.tipping,
                profile.dcc_warning,
            )
        ):
            continue
        link = links[profile.country_id]
        items.append(
            ExploreCollectionItem(
                key=f"payment:{profile.country.iso2}",
                title=profile.country.name,
                summary=profile.summary.strip() or "Reviewed cash and card guidance.",
                country_codes=(profile.country.iso2,),
                currency_codes=(link.currency.code,),
                reviewed_on=profile.verified_at.date(),
                evidence=(
                    ExploreCollectionEvidence(
                        source_name=profile.source_name,
                        source_url=profile.source_url,
                        evidence_date=profile.verified_at.date(),
                    ),
                ),
            )
        )
        if len(items) >= limit:
            break
    return tuple(items)


def _shared_currency_items(*, as_of: date, limit: int) -> tuple[ExploreCollectionItem, ...]:
    links = tuple(
        CountryCurrency.objects.current(as_of)
        .primary()
        .select_related("country", "currency")
        .order_by("currency__code", "country__name", "country__iso2")
    )
    grouped: dict[int, list[CountryCurrency]] = {}
    for link in links:
        if not is_valid_provenance_url(link.source):
            continue
        grouped.setdefault(link.currency_id, []).append(link)

    items: list[ExploreCollectionItem] = []
    for currency_id in sorted(
        grouped,
        key=lambda key: (grouped[key][0].currency.code, key),
    ):
        group = grouped[currency_id]
        if len(group) < 2:
            continue
        currency = group[0].currency
        countries = tuple(link.country.iso2 for link in group)
        country_names = tuple(link.country.name for link in group)
        evidence = _dedupe_evidence(
            tuple(
                ExploreCollectionEvidence(
                    source_name=f"{link.country.name} current-currency source",
                    source_url=link.source,
                )
                for link in group
            )
        )
        if not evidence:
            continue
        items.append(
            ExploreCollectionItem(
                key=f"shared-currency:{currency.code}",
                title=f"{currency.name} · {currency.code}",
                summary=f"Current primary currency in {', '.join(country_names)}.",
                country_codes=countries,
                currency_codes=(currency.code,),
                evidence=evidence,
            )
        )
        if len(items) >= limit:
            break
    return tuple(items)


def _destination_evidence(
    destination: ExploreDestination,
    *,
    as_of: date,
) -> tuple[ExploreCollectionEvidence, ...]:
    context = build_destination_context(
        country_code=destination.country_code,
        city_slug=destination.city_slug,
        converted_amount=Decimal("1"),
        quote_currency=destination.currency_code,
        as_of=as_of,
        price_limit=6,
    )
    if context is None:
        return ()

    values: list[ExploreCollectionEvidence] = []
    for price in context.prices:
        if destination.is_city_scope and price.city_slug not in {"", destination.city_slug}:
            continue
        if not destination.is_city_scope and price.city_slug:
            continue
        values.append(
            ExploreCollectionEvidence(
                source_name=price.source_name,
                source_url=price.source_url,
                evidence_date=price.observed_at,
            )
        )
    if context.payment is not None:
        values.append(
            ExploreCollectionEvidence(
                source_name=context.payment.source_name,
                source_url=context.payment.source_url,
                evidence_date=context.payment.verified_at.date(),
            )
        )
    return _dedupe_evidence(tuple(values))


def _recent_destination_items(
    *,
    destinations: tuple[ExploreDestination, ...],
    as_of: date,
    limit: int,
) -> tuple[ExploreCollectionItem, ...]:
    items: list[ExploreCollectionItem] = []
    for destination in destinations:
        evidence = _destination_evidence(destination, as_of=as_of)
        if not evidence:
            continue
        reviewed_on = destination.latest_price_observed_at or destination.payment_verified_at
        if reviewed_on is None:
            continue
        items.append(
            ExploreCollectionItem(
                key=(
                    f"destination:{destination.country_code}:{destination.city_slug}"
                    if destination.city_slug
                    else f"destination:{destination.country_code}"
                ),
                title=destination.scope_label,
                summary=(
                    "Reviewed city money context."
                    if destination.is_city_scope
                    else "Reviewed country money context."
                ),
                country_codes=(destination.country_code,),
                currency_codes=(destination.currency_code,),
                city_slug=destination.city_slug,
                reviewed_on=reviewed_on,
                evidence=evidence,
            )
        )

    items.sort(
        key=lambda item: (
            -(item.reviewed_on.toordinal() if item.reviewed_on is not None else 0),
            item.title.casefold(),
            item.key,
        )
    )
    return tuple(items[:limit])


def build_explore_collections(
    *,
    as_of: date | None = None,
    item_limit: int = 6,
) -> tuple[ExploreCollection, ...]:
    """Compose neutral Explore collections only from reviewed canonical evidence."""

    if not 1 <= item_limit <= 12:
        raise ValueError("Explore collection item limit must be between 1 and 12.")

    selected_date = as_of or timezone.localdate()
    destinations = build_explore_destinations(as_of=selected_date, limit=24)

    items_by_kind: dict[ExploreCollectionKind, tuple[ExploreCollectionItem, ...]] = {
        ExploreCollectionKind.CITY_MONEY_PROFILES: _city_profile_items(
            destinations=destinations,
            as_of=selected_date,
            limit=item_limit,
        ),
        ExploreCollectionKind.CURRENCY_STORIES: _story_items(limit=item_limit),
        ExploreCollectionKind.CASH_CARD_BEHAVIOUR: _payment_items(
            as_of=selected_date,
            limit=item_limit,
        ),
        ExploreCollectionKind.SHARED_CURRENCY_COUNTRIES: _shared_currency_items(
            as_of=selected_date,
            limit=item_limit,
        ),
        ExploreCollectionKind.RECENTLY_REVIEWED_DESTINATIONS: _recent_destination_items(
            destinations=destinations,
            as_of=selected_date,
            limit=item_limit,
        ),
    }
    metadata = {
        ExploreCollectionKind.CITY_MONEY_PROFILES: (
            "city-money-profiles",
            "City money profiles",
            "Reviewed city scopes with direct local money evidence.",
        ),
        ExploreCollectionKind.CURRENCY_STORIES: (
            "currency-stories",
            "Currency stories",
            "Published reviewed stories tied to canonical currencies or countries.",
        ),
        ExploreCollectionKind.CASH_CARD_BEHAVIOUR: (
            "cash-card-behaviour",
            "Cash and card behaviour",
            "Reviewed country payment guidance with explicit provenance.",
        ),
        ExploreCollectionKind.SHARED_CURRENCY_COUNTRIES: (
            "shared-currency-countries",
            "Countries sharing a currency",
            "Current-primary currency relationships shared by multiple countries.",
        ),
        ExploreCollectionKind.RECENTLY_REVIEWED_DESTINATIONS: (
            "recently-reviewed-destinations",
            "Recently reviewed destinations",
            "Destination context ordered by evidence date, never by popularity or value.",
        ),
    }

    collections: list[ExploreCollection] = []
    for kind in _COLLECTION_ORDER:
        items = items_by_kind[kind]
        if not items:
            continue
        slug, title, description = metadata[kind]
        collections.append(
            ExploreCollection(
                kind=kind,
                slug=slug,
                title=title,
                description=description,
                items=items,
            )
        )
    return tuple(collections)
