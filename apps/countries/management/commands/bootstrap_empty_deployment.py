"""Atomically initialize an explicitly verified empty demo/preview database.

The web startup performs environment/SHA admission before invoking this
command. Standalone invocations remain guarded and can never seed production.
"""

from __future__ import annotations

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

_ADVISORY_LOCK_KEY = 3_114_825_700_129


class Command(BaseCommand):
    help = "One-time atomic demo/preview bootstrap for a verified empty PostgreSQL."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--confirm-empty", action="store_true")

    def handle(self, *args, **options) -> None:
        environment = str(settings.APP_ENV)
        if environment not in {"demo", "preview", "test"} or not options["confirm_empty"]:
            raise CommandError("Atomic bootstrap requires explicit non-production approval.")
        if connection.vendor != "postgresql" and environment != "test":
            raise CommandError("Atomic deployed bootstrap requires PostgreSQL.")

        # Roll back ALL seed writes if any command fails. The PostgreSQL
        # transaction-scoped advisory lock prevents concurrent first boots
        # from both passing the empty-database check.
        with transaction.atomic():
            if connection.vendor == "postgresql":
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_xact_lock(%s)", [_ADVISORY_LOCK_KEY])

            call_command("check_reference_catalog", require_empty=True, stdout=self.stdout)
            call_command("seed_reference_data", stdout=self.stdout)
            call_command("seed_story_data", stdout=self.stdout)
            call_command("seed_destination_context", stdout=self.stdout)
            call_command("check_reference_catalog", stdout=self.stdout)

        self.stdout.write("Atomic empty-database bootstrap completed.")
