from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.countries.models import Country, Currency


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
