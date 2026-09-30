from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.countries.models import City, Country, Currency


class FavouritePair(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="favourite_pairs",
    )
    source_currency = models.ForeignKey(
        Currency,
        on_delete=models.PROTECT,
        related_name="+",
    )
    destination_currency = models.ForeignKey(
        Currency,
        on_delete=models.PROTECT,
        related_name="+",
    )
    source_country = models.ForeignKey(
        Country,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    destination_country = models.ForeignKey(
        Country,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("user", "source_currency", "destination_currency"),
                condition=Q(
                    source_country__isnull=True,
                    destination_country__isnull=True,
                ),
                name="unique_fav_no_countries",
            ),
            models.UniqueConstraint(
                fields=(
                    "user",
                    "source_currency",
                    "destination_currency",
                    "destination_country",
                ),
                condition=Q(
                    source_country__isnull=True,
                    destination_country__isnull=False,
                ),
                name="unique_fav_destination_country",
            ),
            models.UniqueConstraint(
                fields=(
                    "user",
                    "source_currency",
                    "destination_currency",
                    "source_country",
                ),
                condition=Q(
                    source_country__isnull=False,
                    destination_country__isnull=True,
                ),
                name="unique_fav_source_country",
            ),
            models.UniqueConstraint(
                fields=(
                    "user",
                    "source_currency",
                    "destination_currency",
                    "source_country",
                    "destination_country",
                ),
                condition=Q(
                    source_country__isnull=False,
                    destination_country__isnull=False,
                ),
                name="unique_fav_both_countries",
            ),
        ]
        indexes = [
            models.Index(
                fields=("user", "-updated_at"),
                name="travel_fav_user_updated_idx",
            )
        ]

    def __str__(self) -> str:
        return f"{self.user_id}: {self.source_currency.code} → {self.destination_currency.code}"


class RecentConversion(models.Model):
    class RateMode(models.TextChoices):
        LATEST = "latest", "Latest available"
        HISTORICAL = "historical", "Historical"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="recent_conversions",
    )
    fingerprint = models.CharField(max_length=64)
    source_currency = models.ForeignKey(
        Currency,
        on_delete=models.PROTECT,
        related_name="+",
    )
    destination_currency = models.ForeignKey(
        Currency,
        on_delete=models.PROTECT,
        related_name="+",
    )
    source_country = models.ForeignKey(
        Country,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    destination_country = models.ForeignKey(
        Country,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    input_amount = models.CharField(max_length=64)
    output_amount = models.CharField(max_length=64)
    rate_mode = models.CharField(max_length=10, choices=RateMode.choices)
    requested_date = models.DateField(null=True, blank=True)
    effective_date = models.DateField()
    converted_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-converted_at", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("user", "fingerprint"),
                name="unique_user_recent_conversion",
            ),
            models.CheckConstraint(
                condition=(
                    Q(rate_mode="historical", requested_date__isnull=False)
                    | Q(rate_mode="latest", requested_date__isnull=True)
                ),
                name="recent_requested_date_matches_mode",
            ),
        ]
        indexes = [
            models.Index(
                fields=("user", "-converted_at"),
                name="travel_recent_user_time_idx",
            )
        ]

    def __str__(self) -> str:
        return (
            f"{self.user_id}: {self.input_amount} {self.source_currency.code}"
            f" → {self.output_amount} {self.destination_currency.code}"
        )


class SavedScenarioKind(models.TextChoices):
    TRIP = "trip", "Trip"
    BUDGET = "budget", "Budget"
    SHOPPING = "shopping", "Shopping"


class SavedScenario(models.Model):
    """User-owned reusable travel-money planning state.

    Pair-only bookmarks remain FavouritePair. This model exists for scenarios
    that carry explicit planning assumptions and can be re-checked later.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="saved_scenarios",
    )
    kind = models.CharField(max_length=16, choices=SavedScenarioKind.choices)
    title = models.CharField(max_length=120, blank=True)
    source_currency = models.ForeignKey(
        Currency,
        on_delete=models.PROTECT,
        related_name="+",
    )
    destination_currency = models.ForeignKey(
        Currency,
        on_delete=models.PROTECT,
        related_name="+",
    )
    source_country = models.ForeignKey(
        Country,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    destination_country = models.ForeignKey(
        Country,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    destination_city = models.ForeignKey(
        City,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    source_amount = models.DecimalField(max_digits=40, decimal_places=12)
    duration_days = models.PositiveSmallIntegerField(null=True, blank=True)
    travelers = models.PositiveSmallIntegerField(default=1)
    travel_start_date = models.DateField(null=True, blank=True)
    travel_end_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at", "-id")
        constraints = [
            models.CheckConstraint(
                condition=Q(source_amount__gte=0),
                name="scenario_source_amount_non_negative",
            ),
            models.CheckConstraint(
                condition=Q(duration_days__isnull=True)
                | Q(duration_days__gte=1, duration_days__lte=365),
                name="scenario_duration_days_range",
            ),
            models.CheckConstraint(
                condition=Q(travelers__gte=1, travelers__lte=20),
                name="scenario_travelers_range",
            ),
            models.CheckConstraint(
                condition=Q(travel_start_date__isnull=True)
                | Q(travel_end_date__isnull=True)
                | Q(travel_end_date__gte=models.F("travel_start_date")),
                name="scenario_travel_dates_ordered",
            ),
            models.CheckConstraint(
                condition=Q(destination_city__isnull=True)
                | Q(destination_country__isnull=False),
                name="scenario_city_requires_country",
            ),
            models.CheckConstraint(
                condition=Q(kind=SavedScenarioKind.SHOPPING)
                | Q(destination_country__isnull=False),
                name="scenario_travel_kinds_require_destination",
            ),
        ]
        indexes = [
            models.Index(
                fields=("user", "-updated_at"),
                name="travel_scenario_user_updated_idx",
            ),
            models.Index(
                fields=("user", "kind", "-updated_at"),
                name="travel_scenario_user_kind_idx",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if (
            self.travel_start_date
            and self.travel_end_date
            and self.travel_end_date < self.travel_start_date
        ):
            raise ValidationError(
                {"travel_end_date": "Travel end date cannot precede the start date."}
            )
        if self.destination_city_id and self.destination_country_id:
            city_country_id = self.destination_city.country_id
            if city_country_id != self.destination_country_id:
                raise ValidationError(
                    {"destination_city": "Destination city must belong to the destination country."}
                )

    def __str__(self) -> str:
        label = self.title.strip() or self.get_kind_display()
        return f"{self.user_id}: {label} · {self.source_currency.code} → {self.destination_currency.code}"


class SavedScenarioBudgetItem(models.Model):
    scenario = models.ForeignKey(
        SavedScenario,
        on_delete=models.CASCADE,
        related_name="budget_items",
    )
    category = models.CharField(max_length=24)
    units_per_person_per_day = models.DecimalField(max_digits=8, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("category", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("scenario", "category"),
                name="unique_scenario_budget_category",
            ),
            models.CheckConstraint(
                condition=Q(units_per_person_per_day__gt=0)
                & Q(units_per_person_per_day__lte=100),
                name="scenario_budget_units_range",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.scenario_id}: {self.category} × {self.units_per_person_per_day}"


class SavedScenarioObservationKind(models.TextChoices):
    INITIAL = "initial", "Initial save"
    RECHECK = "recheck", "Re-check"


class SavedScenarioObservation(models.Model):
    """Immutable trusted FX observation associated with a saved scenario."""

    scenario = models.ForeignKey(
        SavedScenario,
        on_delete=models.CASCADE,
        related_name="observations",
    )
    kind = models.CharField(
        max_length=16,
        choices=SavedScenarioObservationKind.choices,
    )
    input_amount = models.DecimalField(max_digits=40, decimal_places=12)
    output_amount = models.DecimalField(max_digits=40, decimal_places=12)
    rate = models.DecimalField(max_digits=40, decimal_places=18)
    effective_date = models.DateField()
    fetched_at = models.DateTimeField()
    provider_keys = models.JSONField(default=list)
    stale = models.BooleanField(default=False)
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-recorded_at", "-id")
        constraints = [
            models.CheckConstraint(
                condition=Q(input_amount__gte=0),
                name="scenario_observation_input_non_negative",
            ),
            models.CheckConstraint(
                condition=Q(output_amount__gte=0),
                name="scenario_observation_output_non_negative",
            ),
            models.CheckConstraint(
                condition=Q(rate__gt=0),
                name="scenario_observation_rate_positive",
            ),
        ]
        indexes = [
            models.Index(
                fields=("scenario", "-recorded_at"),
                name="travel_scenario_obs_time_idx",
            )
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.pk is not None:
            raise ValidationError("Saved scenario observations are immutable.")
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return (
            f"{self.scenario_id}: {self.kind} · "
            f"{self.input_amount} → {self.output_amount} @ {self.rate}"
        )
