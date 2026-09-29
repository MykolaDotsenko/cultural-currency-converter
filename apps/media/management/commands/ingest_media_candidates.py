from __future__ import annotations

import os
from datetime import date

from django.core.management.base import BaseCommand, CommandError

from apps.countries.models import Country, Currency
from apps.media.models import DatePrecision, MediaKind, MediaRole
from apps.media.services import upsert_media_candidates
from apps.media.sources import (
    EuropeanaSearchClient,
    MediaSourceError,
    WikimediaCommonsClient,
)


class Command(BaseCommand):
    help = (
        "Search a reviewed external source and create/update unpublished media candidates. "
        "This command never downloads binaries or publishes media."
    )

    def add_arguments(self, parser):
        parser.add_argument("--source", choices=("wikimedia", "europeana"), required=True)
        parser.add_argument("--query", required=True)
        parser.add_argument("--role", choices=MediaRole.values, required=True)
        parser.add_argument(
            "--kind",
            choices=[
                value for value in MediaKind.values if value != MediaKind.GENERATED_ILLUSTRATION
            ],
            required=True,
        )
        parser.add_argument("--country")
        parser.add_argument("--currency")
        parser.add_argument("--valid-from", type=date.fromisoformat)
        parser.add_argument("--valid-to", type=date.fromisoformat)
        parser.add_argument(
            "--date-precision",
            choices=DatePrecision.values,
            default=DatePrecision.UNKNOWN,
        )
        parser.add_argument("--limit", type=int, default=10)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        country = None
        if options["country"]:
            country = Country.objects.filter(iso2=options["country"].upper()).first()
            if country is None:
                raise CommandError("Unknown country code.")

        currency = None
        if options["currency"]:
            currency = Currency.objects.filter(code=options["currency"].upper()).first()
            if currency is None:
                raise CommandError("Unknown currency code.")

        historical_roles = {
            MediaRole.COMPARISON_THEN,
            MediaRole.HISTORICAL_TIMELINE,
        }
        if options["role"] == MediaRole.COMPARISON_THEN and currency is None:
            raise CommandError(
                "comparison_then candidate ingestion requires --currency."
            )
        if options["role"] in historical_roles:
            if options["date_precision"] == DatePrecision.UNKNOWN:
                raise CommandError(
                    "Historical media candidate ingestion requires --date-precision."
                )
            if options["valid_from"] is None and options["valid_to"] is None:
                raise CommandError(
                    "Historical media candidate ingestion requires --valid-from or --valid-to."
                )
        if (
            options["valid_from"] is not None
            and options["valid_to"] is not None
            and options["valid_from"] > options["valid_to"]
        ):
            raise CommandError("--valid-from must not be after --valid-to.")

        try:
            if options["source"] == "wikimedia":
                client = WikimediaCommonsClient()
            else:
                api_key = os.environ.get("EUROPEANA_API_KEY", "").strip()
                if not api_key:
                    raise CommandError(
                        "EUROPEANA_API_KEY is required for Europeana candidate ingestion."
                    )
                client = EuropeanaSearchClient(api_key=api_key)

            candidates = client.search(options["query"], limit=options["limit"])
            summary = upsert_media_candidates(
                candidates,
                role=options["role"],
                kind=options["kind"],
                country=country,
                currency=currency,
                valid_from=options["valid_from"],
                valid_to=options["valid_to"],
                date_precision=options["date_precision"],
                dry_run=options["dry_run"],
            )
        except (MediaSourceError, ValueError) as exc:
            raise CommandError(str(exc)) from exc

        mode = "DRY RUN" if summary.dry_run else "APPLIED"
        self.stdout.write(
            self.style.SUCCESS(
                f"{mode}: +{summary.created}/~{summary.updated}/"
                f"={summary.unchanged}; protected={summary.skipped_protected}"
            )
        )
