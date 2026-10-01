from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone

from apps.countries.models import City, Country, CountryCurrency
from apps.culture.models import (
    CulturalProfile,
    StoryDatePrecision,
    StoryMoment,
    StoryMomentCategory,
    StoryMomentStatus,
    TypicalPrice,
)
from apps.culture.price_quality import PRICE_CONTEXT_MAX_AGE
from apps.culture.provenance import (
    ProvenanceUrlError,
    is_valid_provenance_url,
    validate_provenance_url,
)

_CAUSAL_RE = re.compile(
    r"\b(?:because|caused|causes|led to|leads to|resulted in|due to|as a result)\b",
    re.IGNORECASE,
)
_TEMPORAL_CATEGORIES = frozenset(
    {
        StoryMomentCategory.CURRENCY_INTRODUCTION,
        StoryMomentCategory.CURRENCY_RETIREMENT,
        StoryMomentCategory.REDENOMINATION,
        StoryMomentCategory.MONETARY_UNION,
        StoryMomentCategory.CASH_CHANGEOVER,
    }
)


class StoryPublicationError(ValueError):
    pass


def _validate_https_url(value: str) -> None:
    try:
        validate_provenance_url(value)
    except ProvenanceUrlError as exc:
        raise StoryPublicationError(
            "Story source URL must be an absolute credential-free HTTPS URL."
        ) from exc


def _validate_publishable(moment: StoryMoment) -> None:
    if not moment.title.strip() or not moment.summary.strip():
        raise StoryPublicationError("Story moments require title and summary.")
    if not moment.source_name.strip() or not moment.source_url.strip():
        raise StoryPublicationError("Story moments require source name and URL.")
    _validate_https_url(moment.source_url)
    if moment.verified_at is None:
        raise StoryPublicationError("Story moments require explicit editorial verification.")
    if not moment.countries.exists() and not moment.currencies.exists():
        raise StoryPublicationError(
            "Story moments require at least one country or currency relationship."
        )
    if moment.category in _TEMPORAL_CATEGORIES and moment.start_date is None:
        raise StoryPublicationError("Temporal story moments require start_date.")
    if (
        moment.category in _TEMPORAL_CATEGORIES
        and moment.date_precision == StoryDatePrecision.UNKNOWN
    ):
        raise StoryPublicationError("Temporal story moments require date precision.")
    if _CAUSAL_RE.search(moment.summary) and (
        not moment.supports_causality or not moment.causal_support_note.strip()
    ):
        raise StoryPublicationError(
            "Causal story wording requires explicit source support and an editorial note."
        )
    try:
        moment.full_clean()
    except ValidationError as exc:
        raise StoryPublicationError(str(exc)) from exc


def approve_story_moment(
    moment: StoryMoment,
    *,
    reviewed_at: datetime | None = None,
) -> StoryMoment:
    if moment.status in {
        StoryMomentStatus.PUBLISHED,
        StoryMomentStatus.RETIRED,
        StoryMomentStatus.REJECTED,
    }:
        raise StoryPublicationError(f"Cannot approve story in {moment.status} state.")
    previous_reviewed_at = moment.reviewed_at
    moment.reviewed_at = reviewed_at or timezone.now()
    try:
        _validate_publishable(moment)
    except Exception:
        moment.reviewed_at = previous_reviewed_at
        raise
    moment.status = StoryMomentStatus.APPROVED
    moment.save(update_fields=("status", "reviewed_at", "updated_at"))
    return moment


def publish_story_moment(
    moment: StoryMoment,
    *,
    published_at: datetime | None = None,
) -> StoryMoment:
    if moment.status != StoryMomentStatus.APPROVED:
        raise StoryPublicationError("Only approved story moments can be published.")
    _validate_publishable(moment)
    moment.status = StoryMomentStatus.PUBLISHED
    moment.published_at = published_at or timezone.now()
    moment.save(update_fields=("status", "published_at", "updated_at"))
    return moment


def retire_story_moment(moment: StoryMoment) -> StoryMoment:
    if moment.status != StoryMomentStatus.PUBLISHED:
        raise StoryPublicationError("Only published story moments can be retired.")
    moment.status = StoryMomentStatus.RETIRED
    moment.save(update_fields=("status", "updated_at"))
    return moment


def reject_story_moment(moment: StoryMoment) -> StoryMoment:
    if moment.status in {StoryMomentStatus.PUBLISHED, StoryMomentStatus.RETIRED}:
        raise StoryPublicationError("Published or retired stories cannot be rejected in place.")
    moment.status = StoryMomentStatus.REJECTED
    moment.reviewed_at = timezone.now()
    moment.save(update_fields=("status", "reviewed_at", "updated_at"))
    return moment


def select_story_moments(
    *,
    country_codes: tuple[str, ...],
    currency_codes: tuple[str, ...],
    selected_date: date,
    historical: bool,
    limit: int = 4,
) -> tuple[StoryMoment, ...]:
    if not 1 <= limit <= 8:
        raise ValueError("Story moment selection limit must be between 1 and 8.")

    filters = Q()
    if country_codes:
        filters |= Q(countries__iso2__in=country_codes)
    if currency_codes:
        filters |= Q(currencies__code__in=currency_codes)
    if not filters:
        return ()

    queryset = (
        StoryMoment.objects.published()
        .relevant_on(selected_date, historical=historical)
        .filter(filters, verified_at__isnull=False)
        .exclude(source_name="")
        .exclude(source_url="")
        .prefetch_related("countries", "currencies")
        .distinct()
    )
    candidate_limit = min(limit * 2, 16)
    return tuple(
        moment
        for moment in queryset[:candidate_limit]
        if is_valid_provenance_url(moment.source_url)
    )[:limit]


def currency_era_links(
    *,
    country_codes: tuple[str, ...],
    currency_codes: tuple[str, ...],
    selected_date: date,
) -> tuple[CountryCurrency, ...]:
    if not country_codes or not currency_codes:
        return ()
    return tuple(
        CountryCurrency.objects.on_date(selected_date)
        .filter(
            country__iso2__in=country_codes,
            currency__code__in=currency_codes,
        )
        .select_related("country", "currency")
        .order_by("country__name", "-is_primary", "-valid_from")
    )


@dataclass(frozen=True, slots=True)
class PurchaseEquivalent:
    minimum_count: Decimal
    maximum_count: Decimal
    status: str


@dataclass(frozen=True, slots=True)
class PaymentContext:
    summary: str
    payment_customs: str
    cash_usage: str
    tipping: str
    atm_notes: str
    dcc_warning: str
    source_name: str
    source_url: str
    verified_at: datetime


@dataclass(frozen=True, slots=True)
class TypicalPriceContext:
    label: str
    category: str
    city: str
    country_name: str
    currency_code: str
    currency_minor_units: int
    amount_low: Decimal
    amount_high: Decimal | None
    observed_at: date
    source_class: str
    confidence: str
    source_name: str
    source_url: str
    equivalent: PurchaseEquivalent
    city_slug: str = ""

    @property
    def scope_label(self) -> str:
        return self.city or f"{self.country_name} · national estimate"


@dataclass(frozen=True, slots=True)
class DestinationContext:
    country_code: str
    country_name: str
    as_of: date
    payment: PaymentContext | None
    prices: tuple[TypicalPriceContext, ...]
    city_slug: str = ""
    city_name: str = ""

    @property
    def has_content(self) -> bool:
        return self.payment is not None or bool(self.prices)


def calculate_purchase_equivalent(
    converted_amount: Decimal,
    price_low: Decimal,
    price_high: Decimal | None = None,
) -> PurchaseEquivalent:
    if converted_amount < 0:
        raise ValueError("Converted amount cannot be negative.")
    if price_low <= 0:
        raise ValueError("Typical price lower bound must be positive.")
    if price_high is not None and price_high < price_low:
        raise ValueError("Typical price upper bound cannot be below the lower bound.")

    effective_high = price_high or price_low
    minimum_count = converted_amount / effective_high
    maximum_count = converted_amount / price_low

    if converted_amount == 0:
        status = "zero"
    elif maximum_count < 1:
        status = "below_one"
    elif minimum_count < 1:
        status = "up_to"
    elif price_high is None or minimum_count == maximum_count:
        status = "single"
    else:
        status = "range"

    return PurchaseEquivalent(
        minimum_count=minimum_count,
        maximum_count=maximum_count,
        status=status,
    )


def build_destination_context(
    *,
    country_code: str,
    converted_amount: Decimal,
    quote_currency: str,
    as_of: date | None = None,
    price_limit: int = 3,
    city_slug: str = "",
) -> DestinationContext | None:
    if not country_code:
        return None
    if not 1 <= price_limit <= 6:
        raise ValueError("Destination price limit must be between 1 and 6.")

    country = Country.objects.filter(iso2=country_code.upper(), is_active=True).first()
    if country is None:
        return None

    selected_date = as_of or timezone.localdate()
    normalized_city_slug = city_slug.strip().lower()
    city = None
    if normalized_city_slug:
        city = City.objects.filter(
            country=country,
            slug=normalized_city_slug,
            is_active=True,
        ).first()
        if city is None:
            raise ValueError("Destination city is not available for the selected country.")

    profile = (
        CulturalProfile.objects.filter(
            country=country,
            is_published=True,
            verified_at__isnull=False,
        )
        .exclude(source_name="")
        .exclude(source_url="")
        .first()
    )
    payment = None
    if (
        profile is not None
        and profile.source_name.strip()
        and is_valid_provenance_url(profile.source_url)
    ):
        payment = PaymentContext(
            summary=profile.summary,
            payment_customs=profile.payment_customs,
            cash_usage=profile.cash_usage,
            tipping=profile.tipping,
            atm_notes=profile.atm_notes,
            dcc_warning=profile.dcc_warning,
            source_name=profile.source_name,
            source_url=profile.source_url,
            verified_at=profile.verified_at,
        )

    cutoff = selected_date - PRICE_CONTEXT_MAX_AGE
    price_candidate_limit = min(price_limit * 4, 24)
    base_prices = (
        TypicalPrice.objects.filter(
            country=country,
            currency__code=quote_currency.upper(),
            is_published=True,
            verified_at__isnull=False,
            observed_at__gte=cutoff,
            observed_at__lte=selected_date,
        )
        .exclude(source_name="")
        .exclude(source_url="")
        .select_related("country", "currency", "city_ref")
    )

    if city is None:
        price_rows = tuple(
            base_prices.order_by("display_order", "city", "label", "pk")[:price_candidate_limit]
        )
    else:
        city_rows = tuple(
            base_prices.filter(city_ref=city).order_by("display_order", "label", "pk")[
                :price_candidate_limit
            ]
        )
        national_rows = tuple(
            base_prices.filter(city_ref__isnull=True, city="").order_by(
                "display_order",
                "label",
                "pk",
            )[:price_candidate_limit]
        )
        selected_rows = []
        selected_categories: set[str] = set()
        for row in (*city_rows, *national_rows):
            if row.category in selected_categories:
                continue
            if not row.source_name.strip() or not is_valid_provenance_url(row.source_url):
                continue
            selected_rows.append(row)
            selected_categories.add(row.category)
            if len(selected_rows) >= price_limit:
                break
        price_rows = tuple(selected_rows)

    prices = tuple(
        TypicalPriceContext(
            label=row.label,
            category=row.category,
            city=row.city_ref.name if row.city_ref_id is not None else row.city,
            country_name=row.country.name,
            currency_code=row.currency.code,
            currency_minor_units=row.currency.minor_units,
            amount_low=row.amount_low,
            amount_high=row.amount_high,
            observed_at=row.observed_at,
            source_class=row.source_class,
            confidence=row.confidence,
            source_name=row.source_name,
            source_url=row.source_url,
            equivalent=calculate_purchase_equivalent(
                converted_amount,
                row.amount_low,
                row.amount_high,
            ),
            city_slug=row.city_ref.slug if row.city_ref_id is not None else "",
        )
        for row in price_rows
        if row.source_name.strip() and is_valid_provenance_url(row.source_url)
    )[:price_limit]

    return DestinationContext(
        country_code=country.iso2,
        country_name=country.name,
        as_of=selected_date,
        payment=payment,
        prices=prices,
        city_slug=city.slug if city is not None else "",
        city_name=city.name if city is not None else "",
    )
