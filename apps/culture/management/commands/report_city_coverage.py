from __future__ import annotations

import json
from datetime import date

from django.core.management.base import BaseCommand, CommandError

from apps.culture.city_health import (
    CITY_COVERAGE_CORE_CATEGORIES,
    build_city_coverage_health,
)


class Command(BaseCommand):
    help = (
        "Report current city TypicalPrice coverage health for data maintenance. "
        "The diagnostic score is not a user-facing affordability or cost-of-living score."
    )

    def add_arguments(self, parser):
        parser.add_argument("--country", help="ISO 3166-1 alpha-2 country code.")
        parser.add_argument("--city", help="Canonical city slug; requires --country.")
        parser.add_argument("--as-of", help="Evaluate freshness/current currency on YYYY-MM-DD.")
        parser.add_argument("--json", action="store_true", dest="as_json")
        parser.add_argument(
            "--strict",
            action="store_true",
            help="Fail when a city lacks the required fresh direct core evidence.",
        )
        parser.add_argument(
            "--min-direct-core",
            type=int,
            default=4,
            help="When strict, require this many of 4 fresh direct core categories (1–4).",
        )

    def handle(self, *args, **options):
        country = (options["country"] or "").strip().upper()
        city = (options["city"] or "").strip().lower()
        if city and not country:
            raise CommandError("--city requires --country because city slugs are country-scoped.")

        min_direct = options["min_direct_core"]
        if not 1 <= min_direct <= len(CITY_COVERAGE_CORE_CATEGORIES):
            raise CommandError("--min-direct-core must be between 1 and 4.")
        if not options["strict"] and min_direct != 4:
            raise CommandError("--min-direct-core requires --strict.")

        selected_date = self._date(options["as_of"])
        reports = build_city_coverage_health(
            as_of=selected_date,
            country_code=country,
            city_slug=city,
        )
        if not reports:
            scope = f"{country}/{city}" if city else (country or "active cities")
            raise CommandError(f"No active city coverage scope found for {scope}.")

        invalid = (
            [
                report
                for report in reports
                if len(set(report.fresh_categories) & set(CITY_COVERAGE_CORE_CATEGORIES))
                < min_direct
                or report.provenance_gap_categories
            ]
            if options["strict"]
            else []
        )

        if options["as_json"]:
            self.stdout.write(
                json.dumps(
                    [report.as_dict() for report in reports],
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
            if invalid:
                raise CommandError(
                    "City coverage below strict direct-evidence threshold; review report."
                )
            return

        for report in reports:
            self.stdout.write(
                f"{report.country_code}/{report.city_slug} · {report.city_name} · "
                f"currency={report.currency_code or 'NONE'} · "
                f"supported={report.total_supported_categories} · "
                f"fresh={self._categories(report.fresh_categories)} · "
                f"stale={self._categories(report.stale_categories)} · "
                f"fallback={self._categories(report.national_fallback_categories)} · "
                f"provenance_gaps={self._categories(report.provenance_gap_categories)} · "
                f"score={report.coverage_score}/100"
            )
            self.stdout.write(f"  {report.summary}")

        if invalid:
            raise CommandError(
                "City coverage below strict direct-evidence threshold; review report."
            )

    @staticmethod
    def _date(value: str | None) -> date | None:
        if not value:
            return None
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise CommandError("--as-of must be YYYY-MM-DD.") from exc

    @staticmethod
    def _categories(values: tuple[str, ...]) -> str:
        return ",".join(values) if values else "-"
