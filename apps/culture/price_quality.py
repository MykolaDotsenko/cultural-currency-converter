from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from django.db import models

from apps.culture.provenance import is_valid_provenance_url

PRICE_CONTEXT_MAX_AGE = timedelta(days=730)


class TypicalPriceUnit(models.TextChoices):
    SERVING = "serving", "Serving"
    MEAL = "meal", "Meal"
    RIDE = "ride", "Ride"
    BASKET = "basket", "Basket"
    ITEM = "item", "Item"


_CANONICAL_UNIT_BY_CATEGORY = {
    "coffee": TypicalPriceUnit.SERVING,
    "casual_meal": TypicalPriceUnit.MEAL,
    "transit": TypicalPriceUnit.RIDE,
    "groceries": TypicalPriceUnit.BASKET,
    "other": TypicalPriceUnit.ITEM,
}


class TypicalPriceQualityCode(StrEnum):
    CANONICAL_CITY_REQUIRED = "canonical_city_required"
    CITY_COUNTRY_MISMATCH = "city_country_mismatch"
    CITY_INACTIVE = "city_inactive"
    CATEGORY_UNIT_MISMATCH = "category_unit_mismatch"
    AMOUNT_LOW_NON_POSITIVE = "amount_low_non_positive"
    AMOUNT_RANGE_INVALID = "amount_range_invalid"
    CURRENT_CURRENCY_MISMATCH = "current_currency_mismatch"
    SOURCE_NAME_MISSING = "source_name_missing"
    PROVENANCE_INVALID = "provenance_invalid"
    OBSERVATION_FUTURE = "observation_future"
    OBSERVATION_STALE = "observation_stale"
    VERIFICATION_MISSING = "verification_missing"


@dataclass(frozen=True, slots=True)
class TypicalPriceQualityIssue:
    code: TypicalPriceQualityCode
    field: str
    message: str


@dataclass(frozen=True, slots=True)
class TypicalPriceQualityInput:
    category: str
    unit: str
    amount_low: Decimal | None
    amount_high: Decimal | None
    country_code: str
    currency_code: str
    current_primary_currency_code: str
    city_text: str
    city_slug: str
    city_country_code: str
    city_active: bool
    source_name: str
    source_url: str
    observed_at: date | None
    verified_at: datetime | None
    is_published: bool


def canonical_unit_for_category(category: str) -> str | None:
    unit = _CANONICAL_UNIT_BY_CATEGORY.get(category)
    return unit.value if unit is not None else None


def normalize_price_label(value: str) -> str:
    return " ".join(value.split())


def normalized_duplicate_identity(
    *,
    country_code: str,
    city_slug: str,
    category: str,
    unit: str,
    label: str,
    observed_at: date,
) -> tuple[str, str, str, str, str, date]:
    return (
        country_code.strip().upper(),
        city_slug.strip().lower(),
        category.strip(),
        unit.strip(),
        normalize_price_label(label).casefold(),
        observed_at,
    )


def evaluate_typical_price_quality(
    value: TypicalPriceQualityInput,
    *,
    today: date,
) -> tuple[TypicalPriceQualityIssue, ...]:
    issues: list[TypicalPriceQualityIssue] = []

    expected_unit = canonical_unit_for_category(value.category)
    if expected_unit is None or value.unit != expected_unit:
        issues.append(
            TypicalPriceQualityIssue(
                code=TypicalPriceQualityCode.CATEGORY_UNIT_MISMATCH,
                field="unit",
                message="Typical-price unit must match the normalized category unit.",
            )
        )

    if value.amount_low is None or value.amount_low <= 0:
        issues.append(
            TypicalPriceQualityIssue(
                code=TypicalPriceQualityCode.AMOUNT_LOW_NON_POSITIVE,
                field="amount_low",
                message="Typical price must be positive.",
            )
        )
    if (
        value.amount_low is not None
        and value.amount_high is not None
        and value.amount_high < value.amount_low
    ):
        issues.append(
            TypicalPriceQualityIssue(
                code=TypicalPriceQualityCode.AMOUNT_RANGE_INVALID,
                field="amount_high",
                message="High price cannot be below low price.",
            )
        )

    city_text = normalize_price_label(value.city_text)
    if value.is_published and city_text and not value.city_slug:
        issues.append(
            TypicalPriceQualityIssue(
                code=TypicalPriceQualityCode.CANONICAL_CITY_REQUIRED,
                field="city_ref",
                message="Published city-scoped prices require a canonical City reference.",
            )
        )
    if value.city_slug and value.city_country_code != value.country_code:
        issues.append(
            TypicalPriceQualityIssue(
                code=TypicalPriceQualityCode.CITY_COUNTRY_MISMATCH,
                field="city_ref",
                message="Typical-price city must belong to the selected country.",
            )
        )
    if value.is_published and value.city_slug and not value.city_active:
        issues.append(
            TypicalPriceQualityIssue(
                code=TypicalPriceQualityCode.CITY_INACTIVE,
                field="city_ref",
                message="Published city-scoped prices require an active canonical City.",
            )
        )

    if not value.is_published:
        return tuple(issues)

    if (
        not value.current_primary_currency_code
        or value.currency_code != value.current_primary_currency_code
    ):
        issues.append(
            TypicalPriceQualityIssue(
                code=TypicalPriceQualityCode.CURRENT_CURRENCY_MISMATCH,
                field="currency",
                message=(
                    "Published typical prices must use the country's current primary currency."
                ),
            )
        )

    if not value.source_name.strip():
        issues.append(
            TypicalPriceQualityIssue(
                code=TypicalPriceQualityCode.SOURCE_NAME_MISSING,
                field="source_name",
                message="Published typical prices require a source name.",
            )
        )
    if not value.source_url.strip() or not is_valid_provenance_url(value.source_url):
        issues.append(
            TypicalPriceQualityIssue(
                code=TypicalPriceQualityCode.PROVENANCE_INVALID,
                field="source_url",
                message=(
                    "Published typical prices require an absolute credential-free HTTPS source URL."
                ),
            )
        )
    if value.verified_at is None:
        issues.append(
            TypicalPriceQualityIssue(
                code=TypicalPriceQualityCode.VERIFICATION_MISSING,
                field="verified_at",
                message="Published typical prices require explicit verification.",
            )
        )

    if value.observed_at is None:
        return tuple(issues)
    if value.observed_at > today:
        issues.append(
            TypicalPriceQualityIssue(
                code=TypicalPriceQualityCode.OBSERVATION_FUTURE,
                field="observed_at",
                message="Typical-price observation date cannot be in the future.",
            )
        )
    elif value.observed_at < today - PRICE_CONTEXT_MAX_AGE:
        issues.append(
            TypicalPriceQualityIssue(
                code=TypicalPriceQualityCode.OBSERVATION_STALE,
                field="observed_at",
                message="Published typical-price observation is outside the freshness window.",
            )
        )

    return tuple(issues)
