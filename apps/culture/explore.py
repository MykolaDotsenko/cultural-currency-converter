from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.utils import timezone

from apps.countries.models import City, CountryCurrency
from apps.culture.models import CulturalProfile, TypicalPrice
from apps.culture.provenance import is_valid_provenance_url
from apps.culture.services import (
    PRICE_CONTEXT_MAX_AGE,
    DestinationContext,
    build_destination_context,
)


@dataclass(frozen=True, slots=True)
class ExploreDestination:
    """Provider-free discovery summary for one reviewed destination scope."""

    country_code: str
    country_name: str
    currency_code: str
    city_slug: str = ""
    city_name: str = ""
    city_price_anchor_count: int = 0
    national_price_anchor_count: int = 0
    payment_available: bool = False
    latest_price_observed_at: date | None = None
    payment_verified_at: date | None = None

    @property
    def scope_label(self) -> str:
        if self.city_name:
            return f"{self.city_name}, {self.country_name}"
        return self.country_name

    @property
    def is_city_scope(self) -> bool:
        return bool(self.city_slug)


def _summary_from_context(
    context: DestinationContext,
    *,
    currency_code: str,
) -> ExploreDestination | None:
    if context.city_slug:
        city_prices = tuple(
            price for price in context.prices if price.city_slug == context.city_slug
        )
        if not city_prices:
            # A canonical city must have explicit city evidence before Explore
            # presents it as city-level money intelligence. National fallback
            # alone must not create a city card.
            return None
        national_prices = tuple(
            price for price in context.prices if not price.city_slug and not price.city
        )
    else:
        city_prices = ()
        national_prices = tuple(
            price for price in context.prices if not price.city_slug and not price.city
        )
        if not national_prices and context.payment is None:
            return None

    visible_prices = (*city_prices, *national_prices)
    latest_price_observed_at = (
        max(price.observed_at for price in visible_prices) if visible_prices else None
    )
    payment_verified_at = (
        context.payment.verified_at.date() if context.payment is not None else None
    )

    return ExploreDestination(
        country_code=context.country_code,
        country_name=context.country_name,
        currency_code=currency_code,
        city_slug=context.city_slug,
        city_name=context.city_name,
        city_price_anchor_count=len(city_prices),
        national_price_anchor_count=len(national_prices),
        payment_available=context.payment is not None,
        latest_price_observed_at=latest_price_observed_at,
        payment_verified_at=payment_verified_at,
    )


def build_explore_destinations(
    *,
    as_of: date | None = None,
    limit: int = 12,
) -> tuple[ExploreDestination, ...]:
    """Return alphabetic reviewed current destination scopes for Explore.

    Discovery stays downstream of the existing destination-context contract:
    it makes no FX or AI request, invents no comparability score and does not
    publish a city unless current canonical city evidence survives the same
    provenance/freshness rules used by the converter.
    """

    if not 1 <= limit <= 24:
        raise ValueError("Explore destination limit must be between 1 and 24.")

    selected_date = as_of or timezone.localdate()
    cutoff = selected_date - PRICE_CONTEXT_MAX_AGE

    fresh_price_rows = tuple(
        TypicalPrice.objects.filter(
            is_published=True,
            verified_at__isnull=False,
            observed_at__gte=cutoff,
            observed_at__lte=selected_date,
        )
        .exclude(source_name="")
        .exclude(source_url="")
        .values_list("country_id", "city_ref_id", "city", "currency_id", "source_url")
    )
    valid_price_rows = tuple(row for row in fresh_price_rows if is_valid_provenance_url(row[4]))
    valid_profile_country_ids = {
        country_id
        for country_id, source_url in (
            CulturalProfile.objects.filter(
                is_published=True,
                verified_at__isnull=False,
            )
            .exclude(source_name="")
            .exclude(source_url="")
            .values_list("country_id", "source_url")
        )
        if is_valid_provenance_url(source_url)
    }

    candidate_country_ids = valid_profile_country_ids | {
        country_id
        for country_id, _city_ref_id, _city, _currency_id, _source_url in valid_price_rows
    }
    if not candidate_country_ids:
        return ()

    current_links = tuple(
        CountryCurrency.objects.current(selected_date)
        .primary()
        .filter(country_id__in=candidate_country_ids)
        .select_related("country", "currency")
        .order_by("country__name", "country__iso2")
    )
    current_by_country_id = {link.country_id: link for link in current_links}

    national_country_ids = {
        country_id
        for country_id, city_ref_id, legacy_city, currency_id, _source_url in valid_price_rows
        if city_ref_id is None
        and not legacy_city
        and (link := current_by_country_id.get(country_id)) is not None
        and link.currency_id == currency_id
    }
    city_ids = {
        city_ref_id
        for country_id, city_ref_id, _legacy_city, currency_id, _source_url in valid_price_rows
        if city_ref_id is not None
        and (link := current_by_country_id.get(country_id)) is not None
        and link.currency_id == currency_id
    }

    cities_by_id = {
        city.pk: city
        for city in (
            City.objects.filter(
                pk__in=city_ids,
                is_active=True,
                country_id__in=current_by_country_id,
            )
            .select_related("country")
            .order_by("country__name", "name", "slug")
        )
    }

    candidates: list[tuple[str, int, str, CountryCurrency, City | None]] = []
    for link in current_links:
        if link.country_id in national_country_ids or link.country_id in valid_profile_country_ids:
            candidates.append(
                (
                    link.country.name.casefold(),
                    0,
                    "",
                    link,
                    None,
                )
            )

    for city in cities_by_id.values():
        link = current_by_country_id.get(city.country_id)
        if link is None:
            continue
        candidates.append(
            (
                link.country.name.casefold(),
                1,
                city.name.casefold(),
                link,
                city,
            )
        )

    candidates.sort(key=lambda candidate: candidate[:3])

    results: list[ExploreDestination] = []
    for _country_sort, _scope_sort, _city_sort, link, city in candidates:
        if len(results) >= limit:
            break
        context = build_destination_context(
            country_code=link.country.iso2,
            city_slug=city.slug if city is not None else "",
            converted_amount=Decimal("1"),
            quote_currency=link.currency.code,
            as_of=selected_date,
            price_limit=6,
        )
        if context is None:
            continue
        summary = _summary_from_context(context, currency_code=link.currency.code)
        if summary is not None:
            results.append(summary)

    return tuple(results)
