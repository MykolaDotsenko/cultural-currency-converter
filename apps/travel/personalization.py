from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from django.contrib.auth import get_user_model
from django.db import transaction

from apps.countries.models import City, Country, CountryCurrency, Currency
from apps.culture.models import TypicalPriceCategory
from apps.exchange.comparison_snapshot import SavedComparisonInput
from apps.travel.models import SavedComparison, SavedComparisonBudgetItem, SavedCurrency, SavedPlace

MAX_SYNC_PLACES = 24
MAX_SYNC_CURRENCIES = 24
MAX_ACCOUNT_PLACES = 100
MAX_ACCOUNT_CURRENCIES = 50
MAX_ACCOUNT_COMPARISONS = 50

_COUNTRY_RE = re.compile(r"^[A-Z]{2}$")
_CITY_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_PLACE_KEYS = {"countryCode", "citySlug"}
_COMPARISON_CATEGORIES = {
    TypicalPriceCategory.COFFEE,
    TypicalPriceCategory.CASUAL_MEAL,
    TypicalPriceCategory.TRANSIT,
}


class SavedPlaceSyncError(ValueError):
    pass


class SavedCurrencySyncError(ValueError):
    pass


class SavedComparisonPersistenceError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SavedPlaceSpec:
    country: Country
    city: City | None

    @property
    def key(self) -> tuple[int, int | None]:
        return self.country.pk, self.city.pk if self.city else None


@dataclass(frozen=True, slots=True)
class SavedPlaceSyncResult:
    places: tuple[SavedPlace, ...]
    created_count: int


@dataclass(frozen=True, slots=True)
class SavedCurrencySyncResult:
    currencies: tuple[SavedCurrency, ...]
    created_count: int


@dataclass(frozen=True, slots=True)
class SavedComparisonPersistResult:
    comparison: SavedComparison
    created: bool


def _normalize_country_code(value: Any) -> str:
    if not isinstance(value, str):
        raise SavedPlaceSyncError("countryCode must be a two-letter country code.")
    code = value.strip().upper()
    if not _COUNTRY_RE.fullmatch(code):
        raise SavedPlaceSyncError("countryCode must be a two-letter country code.")
    return code


def _normalize_city_slug(value: Any) -> str:
    if value == "":
        return ""
    if not isinstance(value, str):
        raise SavedPlaceSyncError("citySlug must be empty or a canonical city slug.")
    slug = value.strip().lower()
    if len(slug) > 120 or not _CITY_SLUG_RE.fullmatch(slug):
        raise SavedPlaceSyncError("citySlug must be empty or a canonical city slug.")
    return slug


def _resolve_place_specs(raw_items: Any) -> list[SavedPlaceSpec]:
    if not isinstance(raw_items, list):
        raise SavedPlaceSyncError("places must be a list.")
    if len(raw_items) > MAX_SYNC_PLACES:
        raise SavedPlaceSyncError(f"At most {MAX_SYNC_PLACES} places may be synced per request.")

    normalized: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for index, item in enumerate(raw_items):
        if not isinstance(item, dict) or set(item) != _PLACE_KEYS:
            raise SavedPlaceSyncError(
                f"Place {index + 1} must contain only countryCode and citySlug."
            )
        identity = (
            _normalize_country_code(item["countryCode"]),
            _normalize_city_slug(item["citySlug"]),
        )
        if identity not in seen:
            seen.add(identity)
            normalized.append(identity)

    country_codes = {country_code for country_code, _city_slug in normalized}
    countries = Country.objects.filter(
        iso2__in=country_codes,
        is_active=True,
    ).in_bulk(field_name="iso2")
    missing_countries = sorted(country_codes - set(countries))
    if missing_countries:
        raise SavedPlaceSyncError(
            f"Unknown or inactive country code: {', '.join(missing_countries)}."
        )

    city_pairs = {(country_code, city_slug) for country_code, city_slug in normalized if city_slug}
    cities = {
        (city.country.iso2, city.slug): city
        for city in City.objects.filter(
            country__iso2__in={country for country, _slug in city_pairs},
            slug__in={slug for _country, slug in city_pairs},
            is_active=True,
            country__is_active=True,
        ).select_related("country")
    }
    missing_cities = sorted(city_pairs - set(cities))
    if missing_cities:
        country_code, city_slug = missing_cities[0]
        raise SavedPlaceSyncError(f"Unknown or inactive city scope: {country_code}:{city_slug}.")

    return [
        SavedPlaceSpec(
            country=countries[country_code],
            city=cities.get((country_code, city_slug)) if city_slug else None,
        )
        for country_code, city_slug in normalized
    ]


def sync_user_saved_places(user, raw_items: Any) -> SavedPlaceSyncResult:
    if not user.is_authenticated:
        raise SavedPlaceSyncError("Authentication is required.")

    specs = _resolve_place_specs(raw_items)
    user_model = get_user_model()

    with transaction.atomic():
        user_model.objects.select_for_update().get(pk=user.pk)
        existing = SavedPlace.objects.filter(user=user)
        existing_keys = set(existing.values_list("country_id", "city_id"))
        missing_count = sum(spec.key not in existing_keys for spec in specs)
        if existing.count() + missing_count > MAX_ACCOUNT_PLACES:
            raise SavedPlaceSyncError(
                f"An account may store at most {MAX_ACCOUNT_PLACES} saved places."
            )

        created_count = 0
        for spec in specs:
            place, created = SavedPlace.objects.get_or_create(
                user=user,
                country=spec.country,
                city=spec.city,
            )
            if created:
                place.full_clean()
            created_count += int(created)

    canonical = tuple(
        SavedPlace.objects.filter(user=user)
        .select_related("country", "city")
        .order_by("-updated_at", "-id")
    )
    return SavedPlaceSyncResult(places=canonical, created_count=created_count)


def sync_user_saved_currencies(user, raw_items: Any) -> SavedCurrencySyncResult:
    if not user.is_authenticated:
        raise SavedCurrencySyncError("Authentication is required.")
    if not isinstance(raw_items, list):
        raise SavedCurrencySyncError("currencies must be a list.")
    if len(raw_items) > MAX_SYNC_CURRENCIES:
        raise SavedCurrencySyncError(
            f"At most {MAX_SYNC_CURRENCIES} currencies may be synced per request."
        )

    codes: list[str] = []
    seen: set[str] = set()
    for index, value in enumerate(raw_items):
        if not isinstance(value, str):
            raise SavedCurrencySyncError(f"Currency {index + 1} must be an ISO currency code.")
        code = value.strip().upper()
        if not re.fullmatch(r"[A-Z]{3}", code):
            raise SavedCurrencySyncError(f"Currency {index + 1} must be a three-letter code.")
        if code not in seen:
            seen.add(code)
            codes.append(code)

    currencies = Currency.objects.filter(code__in=codes, is_active=True).in_bulk(field_name="code")
    missing = sorted(set(codes) - set(currencies))
    if missing:
        raise SavedCurrencySyncError(
            f"Unknown or inactive currency code: {', '.join(missing)}."
        )

    user_model = get_user_model()
    with transaction.atomic():
        user_model.objects.select_for_update().get(pk=user.pk)
        existing = SavedCurrency.objects.filter(user=user)
        existing_codes = set(existing.values_list("currency_id", flat=True))
        missing_count = sum(currencies[code].pk not in existing_codes for code in codes)
        if existing.count() + missing_count > MAX_ACCOUNT_CURRENCIES:
            raise SavedCurrencySyncError(
                f"An account may store at most {MAX_ACCOUNT_CURRENCIES} saved currencies."
            )

        created_count = 0
        for code in codes:
            _, created = SavedCurrency.objects.get_or_create(
                user=user,
                currency=currencies[code],
            )
            created_count += int(created)

    canonical = tuple(
        SavedCurrency.objects.filter(user=user)
        .select_related("currency")
        .order_by("-updated_at", "-id")
    )
    return SavedCurrencySyncResult(currencies=canonical, created_count=created_count)


def _destination_parts(token: str) -> tuple[str, str]:
    country_code, separator, city_slug = token.partition(":")
    if not _COUNTRY_RE.fullmatch(country_code):
        raise SavedComparisonPersistenceError("Saved comparison country identity is invalid.")
    if separator and (
        not city_slug or len(city_slug) > 120 or not _CITY_SLUG_RE.fullmatch(city_slug)
    ):
        raise SavedComparisonPersistenceError("Saved comparison city identity is invalid.")
    return country_code, city_slug


def _resolve_destination(token: str) -> tuple[Country, City | None]:
    country_code, city_slug = _destination_parts(token)
    try:
        country = Country.objects.get(iso2=country_code, is_active=True)
    except Country.DoesNotExist as exc:
        raise SavedComparisonPersistenceError(
            f"Saved comparison destination {country_code} is no longer available."
        ) from exc

    city = None
    if city_slug:
        try:
            city = City.objects.get(
                country=country,
                slug=city_slug,
                is_active=True,
            )
        except City.DoesNotExist as exc:
            raise SavedComparisonPersistenceError(
                f"Saved comparison destination {token} is no longer available."
            ) from exc

    if not CountryCurrency.objects.current().primary().filter(country=country).exists():
        raise SavedComparisonPersistenceError(
            f"Saved comparison destination {country_code} has no current primary currency."
        )
    return country, city


def _decimal_identity(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _comparison_fingerprint(value: SavedComparisonInput) -> str:
    payload = {
        "source_amount": _decimal_identity(value.source_amount),
        "source_currency": value.source_currency_code,
        "left": value.left_destination,
        "right": value.right_destination,
        "duration_days": value.assumptions.duration_days,
        "travelers": value.assumptions.travelers,
        "categories": sorted(
            (
                item.category,
                _decimal_identity(item.units_per_person_per_day),
            )
            for item in value.assumptions.categories
        ),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _assert_comparison_categories(value: SavedComparisonInput) -> None:
    categories = {item.category for item in value.assumptions.categories}
    if not categories or not categories.issubset(_COMPARISON_CATEGORIES):
        raise SavedComparisonPersistenceError(
            "Saved comparison contains unsupported reference-basket categories."
        )


def persist_saved_comparison(user, value: SavedComparisonInput) -> SavedComparisonPersistResult:
    if not user.is_authenticated:
        raise SavedComparisonPersistenceError("Authentication is required.")
    _assert_comparison_categories(value)

    try:
        source_currency = Currency.objects.get(
            code=value.source_currency_code,
            is_active=True,
        )
    except Currency.DoesNotExist as exc:
        raise SavedComparisonPersistenceError(
            "Saved comparison source currency is no longer available."
        ) from exc

    left_country, left_city = _resolve_destination(value.left_destination)
    right_country, right_city = _resolve_destination(value.right_destination)
    if left_country.pk == right_country.pk and (
        (left_city.pk if left_city else None) == (right_city.pk if right_city else None)
    ):
        raise SavedComparisonPersistenceError(
            "Saved comparison destinations must be different scopes."
        )

    fingerprint = _comparison_fingerprint(value)
    user_model = get_user_model()

    with transaction.atomic():
        user_model.objects.select_for_update().get(pk=user.pk)
        existing = (
            SavedComparison.objects.filter(user=user, fingerprint=fingerprint)
            .select_related(
                "source_currency",
                "left_country",
                "left_city",
                "right_country",
                "right_city",
            )
            .prefetch_related("budget_items")
            .first()
        )
        if existing is not None:
            _assert_existing_comparison_matches(existing, value)
            return SavedComparisonPersistResult(comparison=existing, created=False)

        if SavedComparison.objects.filter(user=user).count() >= MAX_ACCOUNT_COMPARISONS:
            raise SavedComparisonPersistenceError(
                f"An account may store at most {MAX_ACCOUNT_COMPARISONS} saved comparisons."
            )

        comparison = SavedComparison(
            user=user,
            fingerprint=fingerprint,
            source_currency=source_currency,
            source_amount=value.source_amount,
            left_country=left_country,
            left_city=left_city,
            right_country=right_country,
            right_city=right_city,
            duration_days=value.assumptions.duration_days,
            travelers=value.assumptions.travelers,
        )
        comparison.full_clean()
        comparison.save()

        for item in value.assumptions.categories:
            row = SavedComparisonBudgetItem(
                comparison=comparison,
                category=item.category,
                units_per_person_per_day=item.units_per_person_per_day,
            )
            row.full_clean()
            row.save()

    return SavedComparisonPersistResult(comparison=comparison, created=True)


def _assert_existing_comparison_matches(
    comparison: SavedComparison,
    value: SavedComparisonInput,
) -> None:
    scalar = (
        comparison.source_currency.code,
        _decimal_identity(comparison.source_amount),
        comparison.left_token,
        comparison.right_token,
        comparison.duration_days,
        comparison.travelers,
    )
    expected_scalar = (
        value.source_currency_code,
        _decimal_identity(value.source_amount),
        value.left_destination,
        value.right_destination,
        value.assumptions.duration_days,
        value.assumptions.travelers,
    )
    existing_items = sorted(
        (item.category, _decimal_identity(item.units_per_person_per_day))
        for item in comparison.budget_items.all()
    )
    expected_items = sorted(
        (item.category, _decimal_identity(item.units_per_person_per_day))
        for item in value.assumptions.categories
    )
    if scalar != expected_scalar or existing_items != expected_items:
        raise SavedComparisonPersistenceError(
            "Saved comparison fingerprint collision or stored-input drift detected."
        )


def comparison_reopen_params(comparison: SavedComparison) -> dict[str, str]:
    params = {
        "amount": _decimal_identity(comparison.source_amount),
        "source_currency": comparison.source_currency.code,
        "left_destination": comparison.left_token,
        "right_destination": comparison.right_token,
        "duration_days": str(comparison.duration_days),
        "travelers": str(comparison.travelers),
    }
    for item in comparison.budget_items.all():
        params[f"units_{item.category}"] = _decimal_identity(item.units_per_person_per_day)
    return params
