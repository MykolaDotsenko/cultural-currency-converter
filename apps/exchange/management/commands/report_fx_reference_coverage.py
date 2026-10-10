"""Read-only FX-provider metadata coverage report for the active currency catalog.

Metadata coverage is not equivalent to pair-level live quote availability.
"""

from __future__ import annotations

import json
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.countries.models import Currency

_SOURCE = "frankfurter-v2-currencies"


def _coverage_state(currency: Currency, *, today, cutoff) -> str:
    if (
        currency.coverage_source != _SOURCE
        or currency.coverage_from is None
        or currency.coverage_to is None
        or currency.coverage_fetched_at is None
    ):
        return "metadata_missing"
    if currency.coverage_to_is_terminal:
        return "provider_coverage_terminal"
    if (
        currency.coverage_from > today
        or currency.coverage_to < cutoff.date()
        or currency.coverage_fetched_at < cutoff
        or currency.coverage_fetched_at > timezone.now()
    ):
        return "metadata_stale"
    return "metadata_recent"


class Command(BaseCommand):
    help = (
        "Report stored FX-provider currency metadata coverage, without live FX calls "
        "or claims that any particular rate/pair is currently available."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--json", action="store_true")
        parser.add_argument("--strict", action="store_true")
        parser.add_argument("--max-age-days", type=int, default=21)

    def handle(self, *args, **options) -> None:
        age = options["max_age_days"]
        if not 1 <= age <= 90:
            raise CommandError("Max metadata age must be 1–90 days.")

        now = timezone.now()
        today = timezone.localdate()
        cutoff = now - timedelta(days=age)
        rows = tuple(
            {
                "code": currency.code,
                "state": _coverage_state(currency, today=today, cutoff=cutoff),
            }
            for currency in Currency.objects.filter(is_active=True).order_by("code")
        )
        ready = sum(row["state"] == "metadata_recent" for row in rows)
        payload = {
            "currency_metadata_total": len(rows),
            "currency_metadata_recent": ready,
            "pair_availability": "not_evaluated",
            "currencies": rows,
        }
        if options["json"]:
            self.stdout.write(json.dumps(payload, sort_keys=True))
        else:
            for row in rows:
                self.stdout.write(f"{row['code']}: {row['state']}")
            self.stdout.write(f"METADATA: recent={ready} total={len(rows)}")
            self.stdout.write("Pair-specific exchange rates are NOT evaluated.")

        if options["strict"] and ready != len(rows):
            raise CommandError(
                "Currency metadata incomplete or stale; review reported codes and sync policy."
            )
