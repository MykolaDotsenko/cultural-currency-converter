from __future__ import annotations

import json
from datetime import date

from django.core.management.base import BaseCommand, CommandError

from apps.culture.city_health import build_city_coverage_health


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

    def handle(self, *args, **options):
        country = (options["country"] or "").strip().upper()
        city = (options["city"] or "").strip().lower()
        if city and not country:
            raise CommandError("--city requires --country because city slugs are country-scoped.")

        selected_date = self._date(options["as_of"])
        reports = build_city_coverage_health(
            as_of=selected_date,
            country_code=country,
            city_slug=city,
        )
        if not reports:
            scope = f"{country}/{city}" if city else (country or "active cities")
            raise CommandError(f"No active city coverage scope found for {scope}.")

        if options["as_json"]:
            self.stdout.write(
                json.dumps(
                    [report.as_dict() for report in reports],
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
            return

        for report in reports:
            self.stdout.write(
                (
                    f"{report.country_code}/{report.city_slug} · {report.city_name} · "
                    f"currency={report.currency_code or 'NONE'} · "
                    f"supported={report.total_supported_categories} · "
                    f"fresh={self._categories(report.fresh_categories)} · "
                    f"stale={self._categories(report.stale_categories)} · "
                    f"fallback={self._categories(report.national_fallback_categories)} · "
                    f"provenance_gaps={self._categories(report.provenance_gap_categories)} · "
                    f"score={report.coverage_score}/100"
                )
            )
            self.stdout.write(f"  {report.summary}")

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
