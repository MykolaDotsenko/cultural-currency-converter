from __future__ import annotations

from django.conf import settings
from django.db import models


class PreferredLanguage(models.TextChoices):
    ENGLISH = "en", "English"
    FINNISH = "fi", "Finnish"
    UKRAINIAN = "uk", "Ukrainian"


class AnswerDetail(models.TextChoices):
    CONCISE = "concise", "Concise"
    BALANCED = "balanced", "Balanced"
    DETAILED = "detailed", "Detailed"


class TravelStyle(models.TextChoices):
    BALANCED = "balanced", "Balanced"
    BUDGET = "budget", "Budget-conscious"
    COMFORT = "comfort", "Comfort-first"


class AccountPreferences(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="account_preferences",
    )
    sync_recent_history = models.BooleanField(default=False)
    preferred_language = models.CharField(
        max_length=5,
        choices=PreferredLanguage.choices,
        default=PreferredLanguage.ENGLISH,
    )
    answer_detail = models.CharField(
        max_length=12,
        choices=AnswerDetail.choices,
        default=AnswerDetail.BALANCED,
    )
    travel_style = models.CharField(
        max_length=16,
        choices=TravelStyle.choices,
        default=TravelStyle.BALANCED,
    )
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
        return (
            f"{self.user_id}: recent_history={self.sync_recent_history}, home={home}, "
            f"language={self.preferred_language}, detail={self.answer_detail}, "
            f"travel_style={self.travel_style}"
        )


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
