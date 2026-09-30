from __future__ import annotations

from datetime import date
from typing import Any

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q
from django.utils import timezone


class Country(models.Model):
    iso2 = models.CharField(max_length=2, unique=True)
    iso3 = models.CharField(max_length=3, unique=True)
    name = models.CharField(max_length=120)
    official_name = models.CharField(max_length=180, blank=True)
    capital = models.CharField(max_length=120, blank=True)
    region = models.CharField(max_length=80, blank=True)
    subregion = models.CharField(max_length=120, blank=True)
    flag_url = models.URLField(blank=True)
    is_active = models.BooleanField(default=True)
    metadata_source = models.CharField(max_length=80, blank=True)
    metadata_fetched_at = models.DateTimeField(null=True, blank=True)
    metadata_verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("name", "iso2")

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.iso2 = self.iso2.upper()
        self.iso3 = self.iso3.upper()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.name} ({self.iso2})"


class CurrencyQuerySet(models.QuerySet):
    def active_on(self, selected_date: date) -> CurrencyQuerySet:
        return self.filter(
            Q(active_from__isnull=True) | Q(active_from__lte=selected_date),
            Q(active_to__isnull=True) | Q(active_to__gte=selected_date),
        )

    def covered_on(self, selected_date: date) -> CurrencyQuerySet:
        return self.filter(
            Q(coverage_from__isnull=True) | Q(coverage_from__lte=selected_date)
        ).filter(
            Q(coverage_to_is_terminal=False)
            | Q(coverage_to__isnull=True)
            | Q(coverage_to__gte=selected_date)
        )


class Currency(models.Model):
    code = models.CharField(max_length=3, unique=True)
    name = models.CharField(max_length=120)
    symbol = models.CharField(max_length=16, blank=True)
    minor_units = models.PositiveSmallIntegerField(default=2)
    is_active = models.BooleanField(default=True)
    active_from = models.DateField(null=True, blank=True)
    active_to = models.DateField(null=True, blank=True)
    coverage_from = models.DateField(null=True, blank=True)
    coverage_to = models.DateField(null=True, blank=True)
    coverage_source = models.CharField(max_length=80, blank=True)
    coverage_fetched_at = models.DateTimeField(null=True, blank=True)
    coverage_to_is_terminal = models.BooleanField(default=False)

    objects = CurrencyQuerySet.as_manager()

    class Meta:
        ordering = ("code",)
        constraints = [
            models.CheckConstraint(
                condition=Q(active_from__isnull=True)
                | Q(active_to__isnull=True)
                | Q(active_to__gte=models.F("active_from")),
                name="currency_active_date_range",
            ),
            models.CheckConstraint(
                condition=Q(coverage_from__isnull=True)
                | Q(coverage_to__isnull=True)
                | Q(coverage_to__gte=models.F("coverage_from")),
                name="currency_coverage_date_range",
            ),
        ]

    def clean(self) -> None:
        if self.active_from and self.active_to and self.active_to < self.active_from:
            raise ValidationError({"active_to": "Currency active_to cannot precede active_from."})
        if self.coverage_from and self.coverage_to and self.coverage_to < self.coverage_from:
            raise ValidationError(
                {"coverage_to": "Currency coverage_to cannot precede coverage_from."}
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.code = self.code.upper()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"


class CountryCurrencyQuerySet(models.QuerySet):
    def current(self, as_of: date | None = None) -> CountryCurrencyQuerySet:
        selected_date = as_of or timezone.localdate()
        return self.filter(
            country__is_active=True,
            currency__is_active=True,
            valid_to__isnull=True,
        ).filter(Q(valid_from__isnull=True) | Q(valid_from__lte=selected_date))

    def on_date(self, selected_date: date) -> CountryCurrencyQuerySet:
        return self.filter(
            Q(valid_from__isnull=True) | Q(valid_from__lte=selected_date),
            Q(valid_to__isnull=True) | Q(valid_to__gte=selected_date),
        )

    def primary(self) -> CountryCurrencyQuerySet:
        return self.filter(is_primary=True)


class CountryCurrency(models.Model):
    country = models.ForeignKey(Country, on_delete=models.CASCADE, related_name="currency_links")
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT, related_name="country_links")
    is_primary = models.BooleanField(default=False)
    valid_from = models.DateField(null=True, blank=True)
    valid_to = models.DateField(null=True, blank=True)
    usage_role = models.CharField(max_length=80, blank=True)
    source = models.CharField(max_length=160)

    objects = CountryCurrencyQuerySet.as_manager()

    class Meta:
        ordering = ("country__name", "-is_primary", "currency__code")
        constraints = [
            models.CheckConstraint(
                condition=Q(valid_from__isnull=True)
                | Q(valid_to__isnull=True)
                | Q(valid_to__gte=models.F("valid_from")),
                name="country_currency_valid_date_range",
            ),
            models.UniqueConstraint(
                fields=("country", "currency"),
                condition=Q(valid_to__isnull=True),
                name="unique_active_country_currency",
            ),
            models.UniqueConstraint(
                fields=("country",),
                condition=Q(is_primary=True, valid_to__isnull=True),
                name="unique_active_primary_currency_per_country",
            ),
        ]

    def _validate_primary_period_overlap(self) -> None:
        if not self.is_primary or self.country_id is None:
            return

        conflicts = CountryCurrency.objects.filter(
            country_id=self.country_id,
            is_primary=True,
        )
        if self.pk is not None:
            conflicts = conflicts.exclude(pk=self.pk)
        if self.valid_from is not None:
            conflicts = conflicts.filter(
                Q(valid_to__isnull=True) | Q(valid_to__gte=self.valid_from)
            )
        if self.valid_to is not None:
            conflicts = conflicts.filter(
                Q(valid_from__isnull=True) | Q(valid_from__lte=self.valid_to)
            )

        conflict = conflicts.select_related("currency").order_by("valid_from", "pk").first()
        if conflict is not None:
            raise ValidationError(
                {
                    "valid_from": (
                        "Primary currency periods for one country cannot overlap. "
                        f"Conflicts with {conflict.currency.code}."
                    )
                }
            )

    def clean(self) -> None:
        if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
            raise ValidationError({"valid_to": "valid_to cannot precede valid_from."})
        self._validate_primary_period_overlap()

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.country_id is None:
            self.clean()
            return super().save(*args, **kwargs)

        with transaction.atomic():
            Country.objects.select_for_update().get(pk=self.country_id)
            self.clean()
            return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.country.iso2} → {self.currency.code}"


def primary_currency_for(country_code: str, selected_date: date | None = None) -> Currency | None:
    links = CountryCurrency.objects.filter(country__iso2=country_code.upper()).primary()
    links = links.current() if selected_date is None else links.on_date(selected_date)
    link = links.select_related("currency").order_by("-valid_from").first()
    return link.currency if link else None
