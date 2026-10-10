"""Fail-closed checks for reference-data readiness and one-time initial bootstrap."""

from __future__ import annotations

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError

from apps.countries.models import CountryCurrency

_REQUIRED_PRIMARY_PAIRS = frozenset(
    {
        ("FI", "EUR"),
        ("JP", "JPY"),
        ("US", "USD"),
        ("SE", "SEK"),
        ("DK", "DKK"),
        ("NO", "NOK"),
        ("DE", "EUR"),
        ("SG", "SGD"),
        ("CA", "CAD"),
        ("NZ", "NZD"),
    }
)
_PRODUCT_APP_LABELS = frozenset({"accounts", "countries", "culture", "exchange", "media", "travel"})


def _product_tables_are_empty() -> bool:
    """Inspect every product-owned managed model, including hidden records."""

    # Django's default User model belongs to the auth app, not accounts.
    # Do not treat built-in auth Permission/ContentType rows as user data.
    if get_user_model()._base_manager.exists():
        return False

    for model in apps.get_models():
        if (
            model._meta.app_label in _PRODUCT_APP_LABELS
            and model._meta.managed
            and not model._meta.proxy
            and model._base_manager.exists()
        ):
            return False
    return True


class Command(BaseCommand):
    help = (
        "Verify initial reference country/currency pairs without mutating data; "
        "or require fully empty product tables before operator-initiated seeding."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--require-empty",
            action="store_true",
            help="Fail if any product-owned table has data; use before first-time bootstrap.",
        )

    def handle(self, *args, **options) -> None:
        try:
            if options["require_empty"]:
                if not _product_tables_are_empty():
                    raise CommandError(
                        "Initial bootstrap refused: existing product records require operator review."
                    )
                self.stdout.write("Initial bootstrap preflight: product tables empty.")
                return

            current_pairs = set(
                CountryCurrency.objects.current()
                .filter(
                    is_primary=True,
                    country__is_active=True,
                    currency__is_active=True,
                )
                .values_list("country__iso2", "currency__code")
            )
            if not _REQUIRED_PRIMARY_PAIRS.issubset(current_pairs):
                raise CommandError(
                    "Reference catalog incomplete; initialize explicitly before serving requests."
                )
            self.stdout.write("Reference catalog: required country/currency pairs present.")
        except DatabaseError:
            # Database errors may embed DSNs, credentials, internal table names.
            raise CommandError("Reference catalog could not be verified.") from None
