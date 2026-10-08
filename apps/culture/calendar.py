from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from apps.countries.models import Country
from apps.culture.models import PublicHolidayObservation
from integrations.holidays import HolidaySourceObservation


@dataclass(frozen=True, slots=True)
class PublicHolidayContextItem:
    date: date
    name: str
    holiday_types: tuple[str, ...]
    source_name: str
    source_url: str


@dataclass(frozen=True, slots=True)
class CalendarContext:
    as_of: date
    today: tuple[PublicHolidayContextItem, ...]
    upcoming: tuple[PublicHolidayContextItem, ...]
    window_days: int

    @property
    def has_content(self) -> bool:
        return bool(self.today or self.upcoming)


def build_calendar_context(
    *,
    country: Country,
    as_of: date | None = None,
    window_days: int = 30,
    limit: int = 3,
) -> CalendarContext | None:
    if not 1 <= window_days <= 90:
        raise ValueError("Holiday context window must be between 1 and 90 days.")
    if not 1 <= limit <= 6:
        raise ValueError("Holiday context limit must be between 1 and 6.")

    selected_date = as_of or timezone.localdate()
    end_date = selected_date + timedelta(days=window_days)
    rows = tuple(
        PublicHolidayObservation.objects.filter(
            country=country,
            is_published=True,
            national_holiday=True,
            date__gte=selected_date,
            date__lte=end_date,
        ).order_by("date", "name", "pk")[: limit + 8]
    )

    items = tuple(
        PublicHolidayContextItem(
            date=row.date,
            name=row.name,
            holiday_types=tuple(str(value) for value in row.holiday_types),
            source_name=row.source_name,
            source_url=row.source_url,
        )
        for row in rows
    )
    today = tuple(item for item in items if item.date == selected_date)[:limit]
    upcoming = tuple(item for item in items if item.date > selected_date)[:limit]
    context = CalendarContext(
        as_of=selected_date,
        today=today,
        upcoming=upcoming,
        window_days=window_days,
    )
    return context if context.has_content else None


def reconcile_public_holiday_year(
    *,
    country: Country,
    year: int,
    observations: tuple[HolidaySourceObservation, ...],
) -> tuple[int, int, int]:
    expected_code = country.iso2.upper()
    identities: set[tuple[date, str]] = set()

    for observation in observations:
        if observation.country_code.upper() != expected_code:
            raise ValueError("Holiday observation country does not match reconciliation scope.")
        if observation.date.year != year:
            raise ValueError("Holiday observation year does not match reconciliation scope.")
        identity = (observation.date, observation.name.casefold())
        if identity in identities:
            raise ValueError("Holiday observations contain duplicate identity.")
        identities.add(identity)

    created_count = 0
    updated_count = 0
    with transaction.atomic():
        keep_ids: list[int] = []
        for observation in observations:
            row, created = PublicHolidayObservation.objects.update_or_create(
                country=country,
                date=observation.date,
                name=observation.name,
                defaults={
                    "national_holiday": observation.national_holiday,
                    "subdivision_codes": list(observation.subdivision_codes),
                    "holiday_types": list(observation.holiday_types),
                    "source_name": observation.source_name,
                    "source_url": observation.source_url,
                    "source_retrieved_at": observation.retrieved_at,
                    "is_published": True,
                },
            )
            row.full_clean()
            row.save()
            keep_ids.append(row.pk)
            created_count += int(created)
            updated_count += int(not created)

        stale = PublicHolidayObservation.objects.filter(
            country=country,
            date__year=year,
            source_name="Nager.Date",
            is_published=True,
        )
        if keep_ids:
            stale = stale.exclude(pk__in=keep_ids)
        retired_count = stale.update(is_published=False)

    return created_count, updated_count, retired_count
