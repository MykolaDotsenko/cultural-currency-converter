from __future__ import annotations

from django.conf import settings
from django.db import models


class AccountPreferences(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="account_preferences",
    )
    sync_recent_history = models.BooleanField(default=False)
    home_currency = models.ForeignKey(
        "countries.Currency",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        home = self.home_currency_id or "unset"
        return f"{self.user_id}: recent_history={self.sync_recent_history}, home={home}"


class PaymentFeeProfile(models.Model):
    """Explicit reusable payment assumptions scoped to one exact currency pair."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="payment_fee_profiles",
    )
    name = models.CharField(max_length=80)
    source_currency = models.ForeignKey(
        "countries.Currency",
        on_delete=models.PROTECT,
        related_name="+",
    )
    destination_currency = models.ForeignKey(
        "countries.Currency",
        on_delete=models.PROTECT,
        related_name="+",
    )
    fx_markup_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    source_fixed_fee = models.DecimalField(max_digits=40, decimal_places=12, default=0)
    destination_fixed_fee = models.DecimalField(max_digits=40, decimal_places=12, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("user", "name", "source_currency", "destination_currency"),
                name="unique_user_payment_fee_profile_pair_name",
            ),
            models.CheckConstraint(
                condition=~models.Q(source_currency=models.F("destination_currency")),
                name="payment_fee_profile_currencies_differ",
            ),
            models.CheckConstraint(
                condition=models.Q(fx_markup_percent__gte=0, fx_markup_percent__lte=25),
                name="payment_fee_profile_markup_range",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    source_fixed_fee__gte=0,
                    source_fixed_fee__lte=1_000_000_000,
                ),
                name="payment_fee_profile_source_fee_range",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    destination_fixed_fee__gte=0,
                    destination_fixed_fee__lte=1_000_000_000,
                ),
                name="payment_fee_profile_destination_fee_range",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"{self.user_id}:{self.name} {self.source_currency_id}->{self.destination_currency_id}"
        )


class BudgetPreset(models.Model):
    """Explicit reusable Budget Interpretation assumptions owned by one account."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="budget_presets",
    )
    name = models.CharField(max_length=80)
    duration_days = models.PositiveSmallIntegerField()
    travelers = models.PositiveSmallIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("user", "name"),
                name="unique_user_budget_preset_name",
            ),
            models.CheckConstraint(
                condition=models.Q(duration_days__gte=1, duration_days__lte=365),
                name="budget_preset_duration_range",
            ),
            models.CheckConstraint(
                condition=models.Q(travelers__gte=1, travelers__lte=20),
                name="budget_preset_travelers_range",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user_id}:{self.name} · {self.duration_days}d/{self.travelers}p"


class BudgetPresetItem(models.Model):
    preset = models.ForeignKey(
        BudgetPreset,
        on_delete=models.CASCADE,
        related_name="items",
    )
    category = models.CharField(max_length=24)
    units_per_person_per_day = models.DecimalField(max_digits=5, decimal_places=2)

    class Meta:
        ordering = ("category", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("preset", "category"),
                name="unique_budget_preset_category",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    category__in=("coffee", "casual_meal", "transit", "groceries", "other"),
                ),
                name="budget_preset_category_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    units_per_person_per_day__gt=0,
                    units_per_person_per_day__lte=100,
                ),
                name="budget_preset_units_range",
            ),
        ]

    @property
    def category_label(self) -> str:
        return self.category.replace("_", " ").capitalize()

    def __str__(self) -> str:
        return f"{self.preset_id}: {self.category} x {self.units_per_person_per_day}"


class NotificationPreference(models.Model):
    """Explicit account-owned notification configuration. Default state is no row."""

    class NotificationType(models.TextChoices):
        PRE_TRIP = "pre_trip", "Pre-trip reminder"

    class Cadence(models.TextChoices):
        ONCE = "once", "Once when due"
        DAILY = "daily", "Daily while due"

    class DeliveryChannel(models.TextChoices):
        IN_APP = "in_app", "In-app"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_preferences",
    )
    notification_type = models.CharField(
        max_length=24,
        choices=NotificationType.choices,
    )
    enabled = models.BooleanField(default=False)
    timezone_name = models.CharField(max_length=64, default="UTC")
    cadence = models.CharField(
        max_length=16,
        choices=Cadence.choices,
        default=Cadence.ONCE,
    )
    lead_days = models.PositiveSmallIntegerField(default=3)
    delivery_channel = models.CharField(
        max_length=16,
        choices=DeliveryChannel.choices,
        default=DeliveryChannel.IN_APP,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("notification_type", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("user", "notification_type"),
                name="unique_user_notification_type",
            ),
            models.CheckConstraint(
                condition=models.Q(lead_days__gte=1, lead_days__lte=30),
                name="notification_preference_lead_days_range",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(self.timezone_name)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            from django.core.exceptions import ValidationError

            raise ValidationError(
                {"timezone_name": "Enter a valid IANA timezone, for example Europe/Helsinki."}
            ) from exc

    def __str__(self) -> str:
        return (
            f"{self.user_id}:{self.notification_type} "
            f"enabled={self.enabled} {self.timezone_name}/{self.cadence}"
        )
