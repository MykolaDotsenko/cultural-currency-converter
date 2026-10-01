from __future__ import annotations

from datetime import date
from typing import Any

from django.core.exceptions import ValidationError
from django.core.validators import MaxLengthValidator, MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.culture.price_quality import (
    TypicalPriceQualityInput,
    TypicalPriceUnit,
    canonical_unit_for_category,
    evaluate_typical_price_quality,
    normalize_price_label,
    normalized_duplicate_identity,
)
from apps.culture.provenance import ProvenanceUrlError, validate_provenance_url


class StoryMomentCategory(models.TextChoices):
    CURRENCY_INTRODUCTION = "currency_introduction", "Currency introduction"
    CURRENCY_RETIREMENT = "currency_retirement", "Currency retirement"
    REDENOMINATION = "redenomination", "Redenomination"
    MONETARY_UNION = "monetary_union", "Monetary union"
    CASH_CHANGEOVER = "cash_changeover", "Cash changeover"
    CENTRAL_BANK = "central_bank", "Central bank"
    CULTURAL_MONEY_FACT = "cultural_money_fact", "Cultural money fact"
    SOURCED_ECONOMIC_CONTEXT = "sourced_economic_context", "Sourced economic context"


class StorySourceKind(models.TextChoices):
    OFFICIAL = "official", "Official public source"
    INSTITUTION = "institution", "Institution / archive"
    WIKIDATA = "wikidata", "Wikidata"
    MANUAL = "manual", "Manual curated source"


class StoryMomentStatus(models.TextChoices):
    CANDIDATE = "candidate", "Candidate"
    NEEDS_REVIEW = "needs_review", "Needs review"
    APPROVED = "approved", "Approved"
    PUBLISHED = "published", "Published"
    RETIRED = "retired", "Retired"
    REJECTED = "rejected", "Rejected"


class StoryDatePrecision(models.TextChoices):
    EXACT_DAY = "exact_day", "Exact day"
    MONTH = "month", "Month"
    YEAR = "year", "Year"
    RANGE = "range", "Range"
    ERA = "era", "Era"
    UNKNOWN = "unknown", "Unknown"


class StoryMomentQuerySet(models.QuerySet):
    def published(self) -> StoryMomentQuerySet:
        return self.filter(status=StoryMomentStatus.PUBLISHED)

    def relevant_on(self, selected_date: date, *, historical: bool) -> StoryMomentQuerySet:
        if not historical:
            return self
        return self.filter(start_date__isnull=False, start_date__lte=selected_date).filter(
            Q(end_date__isnull=True) | Q(end_date__gte=selected_date)
        )


class StoryMoment(models.Model):
    category = models.CharField(max_length=32, choices=StoryMomentCategory.choices)
    title = models.CharField(max_length=240)
    summary = models.TextField(validators=[MaxLengthValidator(2000)])
    countries = models.ManyToManyField(
        "countries.Country",
        blank=True,
        related_name="story_moments",
    )
    currencies = models.ManyToManyField(
        "countries.Currency",
        blank=True,
        related_name="story_moments",
    )

    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    date_precision = models.CharField(
        max_length=16,
        choices=StoryDatePrecision.choices,
        default=StoryDatePrecision.UNKNOWN,
    )

    source_kind = models.CharField(max_length=24, choices=StorySourceKind.choices)
    source_name = models.CharField(max_length=200)
    source_url = models.URLField(max_length=700)
    external_id = models.CharField(max_length=120, blank=True)
    source_published_at = models.DateField(null=True, blank=True)
    source_retrieved_at = models.DateTimeField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)

    relevance_weight = models.PositiveSmallIntegerField(
        default=50,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    supports_causality = models.BooleanField(default=False)
    causal_support_note = models.TextField(blank=True)

    status = models.CharField(
        max_length=20,
        choices=StoryMomentStatus.choices,
        default=StoryMomentStatus.CANDIDATE,
        db_index=True,
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = StoryMomentQuerySet.as_manager()

    class Meta:
        ordering = ("-relevance_weight", "-start_date", "title")
        constraints = [
            models.CheckConstraint(
                condition=Q(start_date__isnull=True)
                | Q(end_date__isnull=True)
                | Q(end_date__gte=models.F("start_date")),
                name="story_moment_valid_date_range",
            ),
            models.UniqueConstraint(
                fields=("source_kind", "external_id"),
                condition=~Q(external_id=""),
                name="story_unique_external_identity",
            ),
        ]

    _IMMUTABLE_EDITORIAL_FIELDS = (
        "category",
        "title",
        "summary",
        "start_date",
        "end_date",
        "date_precision",
        "source_kind",
        "source_name",
        "source_url",
        "external_id",
        "source_published_at",
        "source_retrieved_at",
        "verified_at",
        "relevance_weight",
        "supports_causality",
        "causal_support_note",
    )

    def clean(self) -> None:
        super().clean()
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": "Story end_date cannot precede start_date."})
        if self.start_date and self.date_precision == StoryDatePrecision.UNKNOWN:
            raise ValidationError(
                {"date_precision": "Dated story moments require explicit temporal precision."}
            )
        if not self.start_date and self.end_date:
            raise ValidationError({"start_date": "end_date requires start_date."})

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.pk:
            current = (
                StoryMoment.objects.filter(pk=self.pk)
                .values("status", *self._IMMUTABLE_EDITORIAL_FIELDS)
                .first()
            )
            if current and current["status"] in {
                StoryMomentStatus.PUBLISHED,
                StoryMomentStatus.RETIRED,
            }:
                changed = [
                    field_name
                    for field_name in self._IMMUTABLE_EDITORIAL_FIELDS
                    if current[field_name] != getattr(self, field_name)
                ]
                if changed:
                    raise ValidationError(
                        "Published or retired story content is immutable; create a new reviewed "
                        "story version instead."
                    )
                if current["status"] == StoryMomentStatus.PUBLISHED and self.status not in {
                    StoryMomentStatus.PUBLISHED,
                    StoryMomentStatus.RETIRED,
                }:
                    raise ValidationError("Published stories may only transition to retired.")
                if (
                    current["status"] == StoryMomentStatus.RETIRED
                    and self.status != StoryMomentStatus.RETIRED
                ):
                    raise ValidationError("Retired stories are immutable.")
        super().save(*args, **kwargs)

    @property
    def is_published(self) -> bool:
        return self.status == StoryMomentStatus.PUBLISHED

    def __str__(self) -> str:
        return f"{self.title} [{self.category}]"


class CulturalProfile(models.Model):
    country = models.OneToOneField(
        "countries.Country",
        on_delete=models.CASCADE,
        related_name="cultural_profile",
    )
    summary = models.TextField(blank=True, validators=[MaxLengthValidator(1200)])
    payment_customs = models.TextField(blank=True, validators=[MaxLengthValidator(1200)])
    cash_usage = models.TextField(blank=True, validators=[MaxLengthValidator(1200)])
    tipping = models.TextField(blank=True, validators=[MaxLengthValidator(1200)])
    atm_notes = models.TextField(blank=True, validators=[MaxLengthValidator(1200)])
    dcc_warning = models.TextField(blank=True, validators=[MaxLengthValidator(1200)])
    source_name = models.CharField(max_length=200, blank=True)
    source_url = models.URLField(max_length=700, blank=True)
    source_notes = models.TextField(blank=True, validators=[MaxLengthValidator(2000)])
    verified_at = models.DateTimeField(null=True, blank=True)
    is_published = models.BooleanField(default=False, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("country__name",)

    def clean(self) -> None:
        super().clean()
        if not self.is_published:
            return
        if not self.source_name.strip() or not self.source_url.strip() or self.verified_at is None:
            raise ValidationError(
                "Published cultural profiles require source name, HTTPS source URL and verification."
            )
        try:
            validate_provenance_url(self.source_url)
        except ProvenanceUrlError as exc:
            raise ValidationError({"source_url": str(exc)}) from exc
        if not any(
            value.strip()
            for value in (
                self.summary,
                self.payment_customs,
                self.cash_usage,
                self.tipping,
                self.atm_notes,
                self.dcc_warning,
            )
        ):
            raise ValidationError(
                "Published cultural profiles require at least one guidance field."
            )

    def __str__(self) -> str:
        return f"{self.country.name} payment context"


class TypicalPriceCategory(models.TextChoices):
    COFFEE = "coffee", "Coffee"
    CASUAL_MEAL = "casual_meal", "Casual meal"
    TRANSIT = "transit", "Transit"
    GROCERIES = "groceries", "Groceries"
    OTHER = "other", "Other"


class TypicalPriceConfidence(models.TextChoices):
    LOW = "low", "Low"
    MEDIUM = "medium", "Medium"
    HIGH = "high", "High"


class TypicalPriceSourceClass(models.TextChoices):
    AUTHORITATIVE = "authoritative", "Authoritative"
    CURATED_FACTUAL = "curated_factual", "Curated factual"
    APPROXIMATE_CONTEXTUAL = "approximate_contextual", "Approximate contextual"


class TypicalPrice(models.Model):
    country = models.ForeignKey(
        "countries.Country",
        on_delete=models.CASCADE,
        related_name="typical_prices",
    )
    city = models.CharField(max_length=120, blank=True)
    city_ref = models.ForeignKey(
        "countries.City",
        on_delete=models.PROTECT,
        related_name="typical_prices",
        null=True,
        blank=True,
    )
    category = models.CharField(max_length=24, choices=TypicalPriceCategory.choices)
    unit = models.CharField(max_length=16, choices=TypicalPriceUnit.choices)
    label = models.CharField(max_length=160)
    amount_low = models.DecimalField(max_digits=12, decimal_places=2)
    amount_high = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    currency = models.ForeignKey(
        "countries.Currency",
        on_delete=models.PROTECT,
        related_name="typical_prices",
    )
    source_name = models.CharField(max_length=200)
    source_url = models.URLField(max_length=700)
    observed_at = models.DateField()
    verified_at = models.DateTimeField(null=True, blank=True)
    source_class = models.CharField(
        max_length=24,
        choices=TypicalPriceSourceClass.choices,
        default=TypicalPriceSourceClass.APPROXIMATE_CONTEXTUAL,
    )
    confidence = models.CharField(
        max_length=12,
        choices=TypicalPriceConfidence.choices,
        default=TypicalPriceConfidence.MEDIUM,
    )
    notes = models.TextField(blank=True, validators=[MaxLengthValidator(1200)])
    display_order = models.PositiveSmallIntegerField(default=100)
    is_published = models.BooleanField(default=False, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("display_order", "city", "label", "pk")
        constraints = [
            models.CheckConstraint(
                condition=Q(amount_low__gt=0),
                name="typical_price_low_positive",
            ),
            models.CheckConstraint(
                condition=Q(amount_high__isnull=True) | Q(amount_high__gte=models.F("amount_low")),
                name="typical_price_range_ordered",
            ),
            models.UniqueConstraint(
                fields=("country", "city", "category", "label", "observed_at"),
                name="typical_price_observation_identity",
            ),
            models.CheckConstraint(
                condition=(
                    Q(category=TypicalPriceCategory.COFFEE, unit=TypicalPriceUnit.SERVING)
                    | Q(category=TypicalPriceCategory.CASUAL_MEAL, unit=TypicalPriceUnit.MEAL)
                    | Q(category=TypicalPriceCategory.TRANSIT, unit=TypicalPriceUnit.RIDE)
                    | Q(category=TypicalPriceCategory.GROCERIES, unit=TypicalPriceUnit.BASKET)
                    | Q(category=TypicalPriceCategory.OTHER, unit=TypicalPriceUnit.ITEM)
                ),
                name="typical_price_category_unit",
            ),
            models.CheckConstraint(
                condition=Q(is_published=False) | Q(city="") | Q(city_ref__isnull=False),
                name="typical_price_published_city_is_canonical",
            ),
            models.UniqueConstraint(
                fields=("country", "city_ref", "category", "unit", "label", "observed_at"),
                condition=Q(city_ref__isnull=False),
                name="typical_price_city_observation_identity",
            ),
            models.UniqueConstraint(
                fields=("country", "category", "unit", "label", "observed_at"),
                condition=Q(city_ref__isnull=True, city=""),
                name="typical_price_national_observation_identity",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        from apps.countries.models import CountryCurrency

        country_code = self.country.iso2 if self.country_id is not None else ""
        currency_code = self.currency.code if self.currency_id is not None else ""
        city_slug = ""
        city_country_code = ""
        city_active = False
        if self.city_ref_id is not None:
            city_slug = self.city_ref.slug
            city_country_code = self.city_ref.country.iso2
            city_active = self.city_ref.is_active

        current_primary_currency_code = ""
        if self.country_id is not None:
            current_link = (
                CountryCurrency.objects.current()
                .primary()
                .filter(country_id=self.country_id)
                .select_related("currency")
                .first()
            )
            if current_link is not None:
                current_primary_currency_code = current_link.currency.code

        issues = evaluate_typical_price_quality(
            TypicalPriceQualityInput(
                category=self.category,
                unit=self.unit,
                amount_low=self.amount_low,
                amount_high=self.amount_high,
                country_code=country_code,
                currency_code=currency_code,
                current_primary_currency_code=current_primary_currency_code,
                city_text=self.city,
                city_slug=city_slug,
                city_country_code=city_country_code,
                city_active=city_active,
                source_name=self.source_name,
                source_url=self.source_url,
                observed_at=self.observed_at,
                verified_at=self.verified_at,
                is_published=self.is_published,
            ),
            today=timezone.localdate(),
        )
        errors: dict[str, list[str]] = {}
        for issue in issues:
            errors.setdefault(issue.field, []).append(issue.message)

        if (
            self.country_id is not None
            and self.observed_at is not None
            and self.category
            and self.unit
            and self.label
        ):
            identity = normalized_duplicate_identity(
                country_code=country_code,
                city_slug=city_slug,
                category=self.category,
                unit=self.unit,
                label=self.label,
                observed_at=self.observed_at,
            )
            candidates = TypicalPrice.objects.filter(
                country_id=self.country_id,
                category=self.category,
                unit=self.unit,
                observed_at=self.observed_at,
            )
            if self.pk is not None:
                candidates = candidates.exclude(pk=self.pk)
            candidates = (
                candidates.filter(city_ref_id=self.city_ref_id)
                if self.city_ref_id is not None
                else candidates.filter(city_ref__isnull=True, city="")
            )
            for candidate in candidates.only(
                "country_id",
                "city_ref_id",
                "city",
                "category",
                "unit",
                "label",
                "observed_at",
            ).select_related("country", "city_ref"):
                candidate_identity = normalized_duplicate_identity(
                    country_code=candidate.country.iso2,
                    city_slug=candidate.city_ref.slug if candidate.city_ref_id is not None else "",
                    category=candidate.category,
                    unit=candidate.unit,
                    label=candidate.label,
                    observed_at=candidate.observed_at,
                )
                if candidate_identity == identity:
                    errors.setdefault("__all__", []).append(
                        "Duplicate typical-price observation for the same canonical scope, "
                        "category, unit, label and observation date."
                    )
                    break

        if errors:
            raise ValidationError(errors)

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.label = normalize_price_label(self.label)
        self.source_name = normalize_price_label(self.source_name)
        canonical_unit = canonical_unit_for_category(self.category)
        if canonical_unit is not None and not self.unit:
            self.unit = canonical_unit
        if self.city_ref_id is not None:
            self.city = normalize_price_label(self.city_ref.name)
        super().save(*args, **kwargs)

    @property
    def scope_label(self) -> str:
        if self.city_ref_id is not None:
            return self.city_ref.name
        return self.city or f"{self.country.name} · national estimate"

    def __str__(self) -> str:
        return f"{self.country.iso2} · {self.label}"
