"""Disposable account/trip/spend recovery probe; never enabled outside APP_ENV=test."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.countries.models import Country, Currency
from apps.travel.models import (
    SavedScenario,
    SavedScenarioKind,
    SavedScenarioObservation,
    SavedScenarioObservationKind,
    SavedScenarioSpendEntry,
    SavedScenarioSpendSource,
)

_USER = "ccc-disposable-recovery-ci"
_TITLE = "Disposable CI recovery probe"
_KEY = UUID("9c5cbf9d-33a9-425e-a007-854d86aee1a2")


def _intact() -> bool:
    user = get_user_model().objects.filter(username=_USER).first()
    if user is None or user.has_usable_password():
        return False
    qs = SavedScenario.objects.filter(user=user, title=_TITLE)
    if qs.count() != 1:
        return False
    trip = qs.select_related("source_currency", "destination_currency", "destination_country").get()
    if (
        trip.kind != SavedScenarioKind.BUDGET
        or trip.source_amount != Decimal("123.45")
        or trip.duration_days != 3
        or trip.travelers != 2
        or trip.source_currency.code != "EUR"
        or trip.destination_currency.code != "JPY"
        or trip.destination_country is None
        or trip.destination_country.iso2 != "JP"
    ):
        return False
    observed = SavedScenarioObservation.objects.filter(scenario=trip)
    spent = SavedScenarioSpendEntry.objects.filter(scenario=trip)
    if observed.count() != 1 or spent.count() != 1:
        return False
    rate = observed.get()
    expense = spent.get()
    return (
        rate.kind == SavedScenarioObservationKind.INITIAL
        and rate.input_amount == Decimal("123.45")
        and rate.output_amount == Decimal("246.90")
        and rate.rate == Decimal("2")
        and rate.effective_date == date(2026, 1, 15)
        and expense.amount == Decimal("12.34")
        and expense.source == SavedScenarioSpendSource.MANUAL
        and expense.submission_key == _KEY
    )


class Command(BaseCommand):
    help = "Verify disposable owner-owned data survives a test PostgreSQL backup and restore."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--phase", required=True, choices=("prepare", "verify"))
        parser.add_argument("--confirm-ci-only", action="store_true")

    def handle(self, *args, **options) -> None:
        if settings.APP_ENV != "test" or not options["confirm_ci_only"]:
            raise CommandError("Recovery probe only supports approved isolated test environments.")

        if options["phase"] == "prepare":
            with transaction.atomic():
                user_model = get_user_model()
                if user_model.objects.filter(username=_USER).exists():
                    raise CommandError("Disposable recovery probe already exists; no overwrite.")
                try:
                    euro = Currency.objects.get(code="EUR", is_active=True)
                    yen = Currency.objects.get(code="JPY", is_active=True)
                    japan = Country.objects.get(iso2="JP", is_active=True)
                except (Country.DoesNotExist, Currency.DoesNotExist) as exc:
                    raise CommandError("Initialize test reference data before the recovery probe.") from exc
                owner = user_model.objects.create_user(username=_USER, password=None)
                trip = SavedScenario(
                    user=owner,
                    kind=SavedScenarioKind.BUDGET,
                    title=_TITLE,
                    source_currency=euro,
                    destination_currency=yen,
                    destination_country=japan,
                    source_amount=Decimal("123.45"),
                    duration_days=3,
                    travelers=2,
                )
                trip.full_clean()
                trip.save()
                SavedScenarioObservation.objects.create(
                    scenario=trip,
                    kind=SavedScenarioObservationKind.INITIAL,
                    input_amount=Decimal("123.45"),
                    output_amount=Decimal("246.90"),
                    rate=Decimal("2"),
                    effective_date=date(2026, 1, 15),
                    fetched_at=timezone.now(),
                    provider_keys=["synthetic-ci-only"],
                )
                SavedScenarioSpendEntry.objects.create(
                    scenario=trip,
                    submission_key=_KEY,
                    amount=Decimal("12.34"),
                    source=SavedScenarioSpendSource.MANUAL,
                )

        if not _intact():
            raise CommandError("Disposable recovery fixture integrity check failed.")
        self.stdout.write("Recovery fixture verified: owner, saved budget, FX observation, spend.")
