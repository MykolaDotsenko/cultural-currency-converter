from __future__ import annotations

from collections.abc import Iterable

from django.core.management.base import CommandError
from django.db import transaction

from apps.common.job_observability import ObservableJobCommand

from apps.countries.models import Country
from apps.culture.economic import persist_economic_observation
from integrations.economic_data import (
    EconomicDataSourceError,
    EurostatEconomicClient,
    OECDEconomicClient,
    WorldBankEconomicClient,
)

_SOURCE_CHOICES = ("all", "world_bank", "eurostat", "oecd")


class Command(ObservableJobCommand):
    job_name = "economic_context"
    help = (
        "Fetch authoritative macro observations from World Bank, Eurostat and OECD, "
        "then atomically publish validated EconomicObservation rows."
    )

    def add_arguments(self, parser):
        parser.add_argument("--source", choices=_SOURCE_CHOICES, default="all")
        parser.add_argument(
            "--country",
            action="append",
            default=[],
            help="Optional ISO alpha-2 or alpha-3 country filter; repeatable.",
        )
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--require-observations",
            action="store_true",
            help="Fail if no observations were fetched; intended for scheduled runs.",
        )

    def handle(self, *args, **options):
        countries = self._countries(options["country"])
        if not countries:
            raise CommandError("No active countries matched the requested filters.")

        selected_sources = (
            ("world_bank", "eurostat", "oecd")
            if options["source"] == "all"
            else (options["source"],)
        )

        observations = []
        errors: list[str] = []
        for source in selected_sources:
            try:
                observations.extend(self._fetch_source(source, countries))
            except (EconomicDataSourceError, ValueError) as exc:
                errors.append(f"{source}: {exc}")

        if errors:
            raise CommandError(
                "Economic context sync aborted before database writes: " + "; ".join(errors)
            )

        # A provider may successfully return an empty result. That is a valid
        # exploratory/manual response, but must fail a scheduled freshness gate.
        if options["require_observations"] and not observations:
            raise CommandError("Economic context sync returned no observations; no rows updated.")

        created_count = 0
        updated_count = 0
        with transaction.atomic():
            for observation in observations:
                _row, created = persist_economic_observation(observation)
                created_count += int(created)
                updated_count += int(not created)

            if options["dry_run"]:
                transaction.set_rollback(True)

        self.set_job_counts(
            records_processed=len(observations),
            records_created=created_count,
            records_updated=updated_count,
        )
        suffix = " (dry run; rolled back)" if options["dry_run"] else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"Economic context sync: {len(observations)} observations, "
                f"{created_count} created, {updated_count} updated{suffix}."
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
            from django.db.models import Q

            queryset = queryset.filter(Q(iso2__in=iso2) | Q(iso3__in=iso3))
        return tuple(queryset)

    def _fetch_source(self, source: str, countries: tuple[Country, ...]):
        if source == "world_bank":
            client = WorldBankEconomicClient()
            return tuple(
                observation
                for country in countries
                for observation in client.fetch_country(country.iso3)
            )
        if source == "eurostat":
            client = EurostatEconomicClient()
            return tuple(
                observation
                for country in countries
                for observation in client.fetch_country(country.iso2)
            )
        if source == "oecd":
            client = OECDEconomicClient()
            return client.fetch_countries({country.iso3 for country in countries})
        raise AssertionError(f"Unsupported economic source: {source}")
