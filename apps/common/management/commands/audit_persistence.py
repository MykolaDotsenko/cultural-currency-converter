"""Read-only, credential-free evidence for the deployed database configuration.

This is an operator command, not a public health endpoint. A configured
PostgreSQL backend alone does NOT demonstrate durable data or backups.
"""

from __future__ import annotations

import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connections
from django.db.migrations.executor import MigrationExecutor

_DEPLOYED_ENVIRONMENTS = frozenset({"demo", "preview", "production"})
_RECOGNIZED_BACKENDS = frozenset({"sqlite", "postgresql"})


def _safe_backend(vendor: str) -> str:
    """Disclose only an allow-listed engine family, never DSNs or paths."""

    return vendor if vendor in _RECOGNIZED_BACKENDS else "other"


class Command(BaseCommand):
    help = (
        "Inspect the default database and migrations without writing data "
        "or printing connection details. This does not prove persistence."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--require-postgresql",
            action="store_true",
            help="Exit nonzero unless PostgreSQL is reachable and migrations are current.",
        )

    def handle(self, *args, **options) -> None:
        connection = connections["default"]
        backend = _safe_backend(connection.vendor)
        environment = str(getattr(settings, "APP_ENV", "unknown")).lower()
        if environment not in {"local", "test", "demo", "preview", "production"}:
            environment = "unknown"

        connection_status = "unavailable"
        migrations_status = "unknown"

        # No SELECT from application/user tables. Avoid printing exception text:
        # driver errors may include hostnames, credentials or database names.
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                reachable = cursor.fetchone() == (1,)
            if reachable:
                connection_status = "ok"
        except Exception:
            connection_status = "unavailable"

        if connection_status == "ok":
            try:
                executor = MigrationExecutor(connection)
                pending = executor.migration_plan(executor.loader.graph.leaf_nodes())
                migrations_status = "pending" if pending else "current"
            except Exception:
                migrations_status = "unknown"

        result = {
            "backend": backend,
            "connection": connection_status,
            "deployed_sqlite_risk": (environment in _DEPLOYED_ENVIRONMENTS and backend == "sqlite"),
            "durability": "unverified",
            "environment": environment,
            "migrations": migrations_status,
        }
        self.stdout.write(json.dumps(result, sort_keys=True))

        # This opt-in gate checks configuration, connectivity and migration
        # readiness ONLY. A real restart/deploy/backup drill remains mandatory.
        if options["require_postgresql"] and not (
            backend == "postgresql" and connection_status == "ok" and migrations_status == "current"
        ):
            raise CommandError(
                "PostgreSQL persistence preflight failed; inspect the sanitized audit result."
            )
