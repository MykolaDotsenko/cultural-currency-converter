from __future__ import annotations

import os
from datetime import date

from django.core.management.base import BaseCommand, CommandError

from apps.countries.models import Country, Currency
from apps.media.models import DatePrecision, MediaKind, MediaRole
from apps.media.services import upsert_media_candidates, validate_candidate_media_scope
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
        parser.add_argument("--valid-from")
        parser.add_argument("--valid-to")
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

        try:
            valid_from = (
                date.fromisoformat(options["valid_from"]) if options["valid_from"] else None
            )
            valid_to = date.fromisoformat(options["valid_to"]) if options["valid_to"] else None
        except ValueError as exc:
            raise CommandError("Media temporal dates must use YYYY-MM-DD.") from exc

        try:
            validate_candidate_media_scope(
                role=options["role"],
                kind=options["kind"],
                country=country,
                currency=currency,
                valid_from=valid_from,
                valid_to=valid_to,
                date_precision=options["date_precision"],
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

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
                valid_from=valid_from,
                valid_to=valid_to,
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
