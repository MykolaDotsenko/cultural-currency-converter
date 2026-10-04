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


class SavedPlace(models.Model):
    """Canonical account-owned destination shortcut.

    The current primary currency is intentionally not persisted. Re-entry
    resolves it from CountryCurrency at read time so a future currency change
    cannot leave stale financial context attached to the saved identity.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="saved_places",
    )
    country = models.ForeignKey(
        Country,
        on_delete=models.PROTECT,
        related_name="+",
    )
    city = models.ForeignKey(
        City,
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
                fields=("user", "country"),
                condition=Q(city__isnull=True),
                name="unique_saved_place_country",
            ),
            models.UniqueConstraint(
                fields=("user", "city"),
                condition=Q(city__isnull=False),
                name="unique_saved_place_city",
            ),
        ]
        indexes = [
            models.Index(
                fields=("user", "-updated_at"),
                name="travel_place_user_upd_idx",
            )
        ]

    def clean(self) -> None:
        super().clean()
        if self.city_id and self.city.country_id != self.country_id:
            raise ValidationError({"city": "Saved city must belong to the saved country."})

    @property
    def token(self) -> str:
        return f"{self.country.iso2}:{self.city.slug}" if self.city_id else self.country.iso2

    def __str__(self) -> str:
        label = f"{self.city.name}, {self.country.name}" if self.city_id else self.country.name
        return f"{self.user_id}: {label}"


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


class SavedComparison(models.Model):
    """Owner-scoped canonical inputs for a reusable destination comparison.

    No FX quote, local-price result, ranking or computed comparison output is
    persisted here. Re-checks always return through the canonical comparison
    form/application path.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="saved_comparisons",
    )
    fingerprint = models.CharField(max_length=64)
    source_currency = models.ForeignKey(
        Currency,
        on_delete=models.PROTECT,
        related_name="+",
    )
    source_amount = models.DecimalField(max_digits=40, decimal_places=12)
    left_country = models.ForeignKey(
        Country,
        on_delete=models.PROTECT,
        related_name="+",
    )
    left_city = models.ForeignKey(
        City,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    right_country = models.ForeignKey(
        Country,
        on_delete=models.PROTECT,
        related_name="+",
    )
    right_city = models.ForeignKey(
        City,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    duration_days = models.PositiveSmallIntegerField()
    travelers = models.PositiveSmallIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("user", "fingerprint"),
                name="unique_saved_comparison",
            ),
            models.CheckConstraint(
                condition=Q(source_amount__gte=0),
                name="saved_cmp_amount_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(source_amount__lte=1_000_000_000),
                name="saved_cmp_amount_max",
            ),
            models.CheckConstraint(
                condition=~(
                    Q(left_country=models.F("right_country"))
                    & Q(left_city__isnull=True, right_city__isnull=True)
                ),
                name="saved_cmp_country_scopes_differ",
            ),
            models.CheckConstraint(
                condition=~(
                    Q(left_city=models.F("right_city"))
                    & Q(left_city__isnull=False, right_city__isnull=False)
                ),
                name="saved_cmp_city_scopes_differ",
            ),
            models.CheckConstraint(
                condition=Q(duration_days__gte=1, duration_days__lte=365),
                name="saved_cmp_duration_range",
            ),
            models.CheckConstraint(
                condition=Q(travelers__gte=1, travelers__lte=20),
                name="saved_cmp_travelers_range",
            ),
        ]
        indexes = [
            models.Index(
                fields=("user", "-updated_at"),
                name="travel_cmp_user_upd_idx",
            )
        ]

    def clean(self) -> None:
        super().clean()
        if self.left_city_id and self.left_city.country_id != self.left_country_id:
            raise ValidationError({"left_city": "Destination A city must belong to its country."})
        if self.right_city_id and self.right_city.country_id != self.right_country_id:
            raise ValidationError({"right_city": "Destination B city must belong to its country."})
        if (
            self.left_country_id == self.right_country_id
            and self.left_city_id == self.right_city_id
        ):
            raise ValidationError("Saved comparison destinations must be different scopes.")

    @property
    def left_token(self) -> str:
        return (
            f"{self.left_country.iso2}:{self.left_city.slug}"
            if self.left_city_id
            else self.left_country.iso2
        )

    @property
    def right_token(self) -> str:
        return (
            f"{self.right_country.iso2}:{self.right_city.slug}"
            if self.right_city_id
            else self.right_country.iso2
        )

    def __str__(self) -> str:
        return (
            f"{self.user_id}: {self.source_amount} {self.source_currency.code} · "
            f"{self.left_token} ↔ {self.right_token}"
        )


class SavedComparisonBudgetItem(models.Model):
    comparison = models.ForeignKey(
        SavedComparison,
        on_delete=models.CASCADE,
        related_name="budget_items",
    )
    category = models.CharField(max_length=24)
    units_per_person_per_day = models.DecimalField(max_digits=8, decimal_places=2)

    class Meta:
        ordering = ("category", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("comparison", "category"),
                name="unique_saved_cmp_category",
            ),
            models.CheckConstraint(
                condition=Q(units_per_person_per_day__gt=0) & Q(units_per_person_per_day__lte=100),
                name="saved_cmp_units_range",
            ),
            models.CheckConstraint(
                condition=Q(category__in=("coffee", "casual_meal", "transit")),
                name="saved_cmp_category_allowed",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.comparison_id}: {self.category} x {self.units_per_person_per_day}"


class SavedScenarioKind(models.TextChoices):
    TRIP = "trip", "Trip"
    BUDGET = "budget", "Budget"
    SHOPPING = "shopping", "Shopping"


class SavedScenarioBudgetBasis(models.TextChoices):
    REFERENCE_CONVERSION = "reference_conversion", "Reference conversion"
    PAYMENT_ESTIMATE = "payment_estimate", "Payment-adjusted estimate"


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
    budget_basis = models.CharField(
        max_length=24,
        choices=SavedScenarioBudgetBasis.choices,
        default=SavedScenarioBudgetBasis.REFERENCE_CONVERSION,
    )
    planning_destination_amount = models.DecimalField(
        max_digits=40,
        decimal_places=12,
        null=True,
        blank=True,
    )
    fx_markup_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
    )
    source_fixed_fee = models.DecimalField(
        max_digits=40,
        decimal_places=12,
        null=True,
        blank=True,
    )
    destination_fixed_fee = models.DecimalField(
        max_digits=40,
        decimal_places=12,
        null=True,
        blank=True,
    )
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
                condition=Q(kind__in=SavedScenarioKind.values),
                name="scenario_kind_valid",
            ),
            models.CheckConstraint(
                condition=Q(source_amount__gte=0),
                name="scenario_source_amount_non_negative",
            ),
            models.CheckConstraint(
                condition=Q(budget_basis__in=SavedScenarioBudgetBasis.values),
                name="scenario_budget_basis_valid",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        budget_basis=SavedScenarioBudgetBasis.REFERENCE_CONVERSION,
                        planning_destination_amount__isnull=True,
                        fx_markup_percent__isnull=True,
                        source_fixed_fee__isnull=True,
                        destination_fixed_fee__isnull=True,
                    )
                    | Q(
                        kind=SavedScenarioKind.BUDGET,
                        budget_basis=SavedScenarioBudgetBasis.PAYMENT_ESTIMATE,
                        planning_destination_amount__isnull=False,
                        planning_destination_amount__gte=0,
                        fx_markup_percent__isnull=False,
                        fx_markup_percent__gte=0,
                        fx_markup_percent__lte=25,
                        source_fixed_fee__isnull=False,
                        source_fixed_fee__gte=0,
                        destination_fixed_fee__isnull=False,
                        destination_fixed_fee__gte=0,
                    )
                ),
                name="scenario_budget_basis_payload_valid",
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
                condition=Q(travel_end_date__isnull=True)
                | (
                    Q(travel_start_date__isnull=False)
                    & Q(travel_end_date__gte=models.F("travel_start_date"))
                ),
                name="scenario_travel_dates_ordered",
            ),
            models.CheckConstraint(
                condition=Q(destination_city__isnull=True) | Q(destination_country__isnull=False),
                name="scenario_city_requires_country",
            ),
            models.CheckConstraint(
                condition=Q(kind=SavedScenarioKind.SHOPPING) | Q(destination_country__isnull=False),
                name="scenario_travel_kinds_require_destination",
            ),
        ]
        indexes = [
            models.Index(
                fields=("user", "-updated_at"),
                name="travel_scn_user_upd_idx",
            ),
            models.Index(
                fields=("user", "kind", "-updated_at"),
                name="travel_scenario_user_kind_idx",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.travel_end_date and not self.travel_start_date:
            raise ValidationError(
                {"travel_start_date": "Travel start date is required when an end date is set."}
            )
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


class ScenarioNotificationType(models.TextChoices):
    PRE_TRIP = "pre_trip", "Pre-trip reminder"
    CONTEXT_FRESHNESS = "context_freshness", "Context/offline freshness"
    RATE_ALERT = "rate_alert", "Scenario rate alert"


class ScenarioNotificationCadence(models.TextChoices):
    ONCE = "once", "Once when due"
    DAILY = "daily", "At most daily"
    WEEKLY = "weekly", "At most weekly"


class ScenarioNotificationDeliveryChannel(models.TextChoices):
    IN_APP = "in_app", "In-app"


class ScenarioNotificationPreference(models.Model):
    """Explicit owner-scoped notification preference for one saved scenario.

    This model stores notification intent/configuration only. It is not a
    delivery log and creating a row does not send or schedule anything by
    itself.
    """

    scenario = models.ForeignKey(
        SavedScenario,
        on_delete=models.CASCADE,
        related_name="notification_preferences",
    )
    notification_type = models.CharField(
        max_length=24,
        choices=ScenarioNotificationType.choices,
    )
    enabled = models.BooleanField(default=False)
    timezone = models.CharField(max_length=64)
    cadence = models.CharField(
        max_length=16,
        choices=ScenarioNotificationCadence.choices,
    )
    delivery_channel = models.CharField(
        max_length=16,
        choices=ScenarioNotificationDeliveryChannel.choices,
        default=ScenarioNotificationDeliveryChannel.IN_APP,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("notification_type", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("scenario", "notification_type"),
                name="unique_scenario_notification_type",
            ),
            models.CheckConstraint(
                condition=Q(notification_type__in=ScenarioNotificationType.values),
                name="scenario_notification_type_valid",
            ),
            models.CheckConstraint(
                condition=Q(cadence__in=ScenarioNotificationCadence.values),
                name="scenario_notification_cadence_valid",
            ),
            models.CheckConstraint(
                condition=Q(delivery_channel__in=ScenarioNotificationDeliveryChannel.values),
                name="scenario_notification_channel_valid",
            ),
            models.CheckConstraint(
                condition=~Q(timezone=""),
                name="scenario_notification_timezone_nonempty",
            ),
        ]
        indexes = [
            models.Index(
                fields=("scenario", "enabled", "notification_type"),
                name="travel_scn_notify_idx",
            )
        ]

    def __str__(self) -> str:
        state = "on" if self.enabled else "off"
        return f"{self.scenario_id}: {self.notification_type} [{state}]"


class SavedScenarioShoppingAssumptions(models.Model):
    """One normalized explicit-input payload for a saved Shopping scenario."""

    scenario = models.OneToOneField(
        SavedScenario,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="shopping_assumptions",
    )
    item_price = models.DecimalField(max_digits=40, decimal_places=12)
    shipping = models.DecimalField(max_digits=40, decimal_places=12, default=0)
    known_fees = models.DecimalField(max_digits=40, decimal_places=12, default=0)
    fx_markup_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(item_price__gt=0),
                name="scenario_shop_item_positive",
            ),
            models.CheckConstraint(
                condition=Q(shipping__gte=0),
                name="scenario_shop_shipping_nonneg",
            ),
            models.CheckConstraint(
                condition=Q(known_fees__gte=0),
                name="scenario_shop_fees_nonneg",
            ),
            models.CheckConstraint(
                condition=Q(fx_markup_percent__gte=0, fx_markup_percent__lte=25),
                name="scenario_shop_markup_range",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.scenario_id and self.scenario.kind != SavedScenarioKind.SHOPPING:
            raise ValidationError({"scenario": "Shopping assumptions require a Shopping scenario."})

    def __str__(self) -> str:
        return f"{self.scenario_id}: shopping assumptions"


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
                condition=Q(units_per_person_per_day__gt=0) & Q(units_per_person_per_day__lte=100),
                name="scenario_budget_units_range",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.scenario_id}: {self.category} x {self.units_per_person_per_day}"


class SavedScenarioSpendSource(models.TextChoices):
    MANUAL = "manual", "Manual entry"
    CAMERA = "camera", "Camera-confirmed"


class SavedScenarioSpendEntry(models.Model):
    """Confirmed destination-currency spend attached to one saved budget scenario.

    Entries are intentionally minimal and immutable after creation. Corrections
    are explicit delete-and-add operations; no merchant, receipt image or free-
    text purchase description is retained by this model.
    """

    scenario = models.ForeignKey(
        SavedScenario,
        on_delete=models.CASCADE,
        related_name="spend_entries",
    )
    submission_key = models.UUIDField(editable=False)
    amount = models.DecimalField(max_digits=40, decimal_places=12)
    source = models.CharField(
        max_length=16,
        choices=SavedScenarioSpendSource.choices,
        default=SavedScenarioSpendSource.MANUAL,
    )
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-recorded_at", "-id")
        constraints = [
            models.CheckConstraint(
                condition=Q(amount__gt=0, amount__lte=1000000000),
                name="scenario_spend_amount_range",
            ),
            models.CheckConstraint(
                condition=Q(source__in=SavedScenarioSpendSource.values),
                name="scenario_spend_source_valid",
            ),
            models.UniqueConstraint(
                fields=("scenario", "submission_key"),
                name="unique_scenario_spend_submission",
            ),
        ]
        indexes = [
            models.Index(
                fields=("scenario", "-recorded_at"),
                name="travel_scenario_spend_idx",
            )
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.pk is not None:
            raise ValidationError("Saved scenario spend entries are immutable.")
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.scenario_id}: {self.amount} [{self.source}]"


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
                condition=Q(kind__in=SavedScenarioObservationKind.values),
                name="scenario_observation_kind_valid",
            ),
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
            models.UniqueConstraint(
                fields=("scenario",),
                condition=Q(kind=SavedScenarioObservationKind.INITIAL),
                name="unique_scenario_initial_observation",
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
