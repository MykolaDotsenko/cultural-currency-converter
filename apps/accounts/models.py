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
