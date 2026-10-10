from __future__ import annotations

from collections.abc import Iterable

from django.core.management.base import CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.common.job_observability import ObservableJobCommand
from apps.countries.models import Country
from apps.culture.calendar import reconcile_public_holiday_year
from integrations.holidays import HolidayDataSourceError, NagerDateHolidayClient


class Command(ObservableJobCommand):
    job_name = "public_holidays"
    help = (
        "Fetch Nager.Date Community v4 public holidays and atomically reconcile "
        "country/year holiday evidence."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--country",
            action="append",
            default=[],
            help="Optional ISO alpha-2 or alpha-3 country filter; repeatable.",
        )
        parser.add_argument(
            "--years-ahead",
            type=int,
            default=1,
            help="Number of future years to include in addition to the current year (0-5).",
        )
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--require-nonempty-scopes",
            action="store_true",
            help="Reject empty provider responses for any requested country/year in scheduled runs.",
        )

    def handle(self, *args, **options):
        years_ahead = options["years_ahead"]
        if not 0 <= years_ahead <= 5:
            raise CommandError("--years-ahead must be between 0 and 5.")

        countries = self._countries(options["country"])
        if not countries:
            raise CommandError("No active countries matched the requested filters.")

        current_year = timezone.localdate().year
        years = tuple(range(current_year, current_year + years_ahead + 1))
        client = NagerDateHolidayClient()

        fetched: dict[tuple[int, int], tuple] = {}
        errors: list[str] = []
        for country in countries:
            for year in years:
                try:
                    fetched[(country.pk, year)] = client.fetch_year(
                        country.iso2,
                        year,
                        today=timezone.localdate(),
                    )
                except (HolidayDataSourceError, ValueError) as exc:
                    errors.append(f"{country.iso2}/{year}: {exc}")

        if errors:
            raise CommandError(
                "Public holiday sync aborted before database writes: " + "; ".join(errors)
            )

        # A provider's empty response is not sufficient evidence that every
        # previously published holiday disappeared. Protect scheduled refreshes;
        # manual reconciliation keeps its existing explicit semantics.
        if options["require_nonempty_scopes"] and any(
            not observations for observations in fetched.values()
        ):
            raise CommandError(
                "Public holiday sync returned an empty country/year scope; "
                "no existing holiday observations were modified."
            )

        created_count = 0
        updated_count = 0
        retired_count = 0
        country_by_id = {country.pk: country for country in countries}

        with transaction.atomic():
            for (country_id, year), observations in fetched.items():
                created, updated, retired = reconcile_public_holiday_year(
                    country=country_by_id[country_id],
                    year=year,
                    observations=observations,
                )
                created_count += created
                updated_count += updated
                retired_count += retired

            if options["dry_run"]:
                transaction.set_rollback(True)

        self.set_job_counts(
            records_processed=len(fetched),
            records_created=created_count,
            records_updated=updated_count,
            records_retired=retired_count,
        )
        suffix = " (dry run; rolled back)" if options["dry_run"] else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"Public holiday sync: {len(fetched)} country/year scopes, "
                f"{created_count} created, {updated_count} updated, "
                f"{retired_count} retired{suffix}."
            )
        )

    def _countries(self, filters: Iterable[str]) -> tuple[Country, ...]:
        normalized = {value.strip().upper() for value in filters if value.strip()}
        queryset = Country.objects.filter(is_active=True).order_by("name", "iso2")
        if normalized:
            invalid = [code for code in normalized if len(code) not in {2, 3} or not code.isalpha()]
            if invalid:
                raise CommandError(
                    "Country filters must be ISO alpha-2 or alpha-3 codes: "
                    + ", ".join(sorted(invalid))
                )
            iso2 = {code for code in normalized if len(code) == 2}
            iso3 = {code for code in normalized if len(code) == 3}
            queryset = queryset.filter(Q(iso2__in=iso2) | Q(iso3__in=iso3))
        return tuple(queryset)
