"""The persistence audit must not expose database topology or touch user data."""

from __future__ import annotations

import json
from io import StringIO
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import SimpleTestCase, TestCase, override_settings

MODULE = "apps.common.management.commands.audit_persistence"


class PersistenceAuditTests(SimpleTestCase):
    def _run(
        self,
        *,
        vendor: str = "sqlite",
        connection_error: Exception | None = None,
        migration_error: Exception | None = None,
        pending: bool = False,
        strict: bool = False,
    ) -> tuple[dict[str, object], MagicMock, MagicMock, CommandError | None]:
        connection = MagicMock()
        connection.vendor = vendor
        connection.cursor.return_value.__enter__.return_value.fetchone.return_value = (1,)
        if connection_error:
            connection.cursor.side_effect = connection_error

        output = StringIO()
        error: CommandError | None = None
        with (
            patch(f"{MODULE}.connections") as connections,
            patch(f"{MODULE}.MigrationExecutor") as executor_class,
        ):
            connections.__getitem__.return_value = connection
            executor_class.return_value.migration_plan.return_value = [object()] if pending else []
            if migration_error:
                executor_class.side_effect = migration_error
            try:
                call_command(
                    "audit_persistence",
                    require_postgresql=strict,
                    stdout=output,
                )
            except CommandError as exc:
                error = exc
            executor = executor_class.return_value
        return json.loads(output.getvalue()), connection, executor, error

    @override_settings(APP_ENV="demo")
    def test_deployed_sqlite_reports_risk_without_claiming_data_loss(self) -> None:
        result, connection, executor, error = self._run()
        self.assertIsNone(error)
        self.assertEqual(
            result,
            {
                "backend": "sqlite",
                "connection": "ok",
                "deployed_sqlite_risk": True,
                "durability": "unverified",
                "environment": "demo",
                "migrations": "current",
            },
        )
        connection.cursor.return_value.__enter__.return_value.execute.assert_called_once_with(
            "SELECT 1"
        )
        executor.migration_plan.assert_called_once()

    @override_settings(APP_ENV="local")
    def test_local_sqlite_is_not_labelled_deployment_risk(self) -> None:
        result, _, _, error = self._run()
        self.assertIsNone(error)
        self.assertFalse(result["deployed_sqlite_risk"])
        self.assertEqual(result["durability"], "unverified")

    @override_settings(APP_ENV="production")
    def test_reachable_postgres_passes_strict_preflight_without_certification(self) -> None:
        result, _, _, error = self._run(vendor="postgresql", strict=True)
        self.assertIsNone(error)
        self.assertEqual(result["backend"], "postgresql")
        self.assertEqual(result["migrations"], "current")
        self.assertEqual(result["durability"], "unverified")

    @override_settings(APP_ENV="demo")
    def test_strict_preflight_rejects_deployed_sqlite(self) -> None:
        result, _, _, error = self._run(strict=True)
        self.assertTrue(result["deployed_sqlite_risk"])
        self.assertIsNotNone(error)

    @override_settings(APP_ENV="production")
    def test_strict_preflight_rejects_pending_migrations(self) -> None:
        result, _, _, error = self._run(
            vendor="postgresql",
            pending=True,
            strict=True,
        )
        self.assertEqual(result["migrations"], "pending")
        self.assertIsNotNone(error)

    @override_settings(APP_ENV="production")
    def test_connection_exception_never_leaks_secrets(self) -> None:
        result, _, executor, error = self._run(
            vendor="postgresql",
            connection_error=RuntimeError(
                "postgresql://user:SECRET@private-host/sensitive-database"
            ),
            strict=True,
        )
        text = json.dumps(result) + str(error)
        self.assertNotIn("SECRET", text)
        self.assertNotIn("private-host", text)
        self.assertNotIn("sensitive-database", text)
        self.assertEqual(result["connection"], "unavailable")
        self.assertEqual(result["migrations"], "unknown")
        executor.migration_plan.assert_not_called()
        self.assertIsNotNone(error)

    @override_settings(APP_ENV="production")
    def test_migration_inspection_failure_is_independent_of_connectivity(self) -> None:
        result, _, _, error = self._run(
            vendor="postgresql",
            migration_error=RuntimeError("password=sensitive"),
            strict=True,
        )
        self.assertEqual(result["connection"], "ok")
        self.assertEqual(result["migrations"], "unknown")
        self.assertNotIn("sensitive", json.dumps(result) + str(error))
        self.assertIsNotNone(error)

    @override_settings(APP_ENV="production")
    def test_unknown_vendor_is_not_disclosed_or_approved(self) -> None:
        result, _, _, error = self._run(vendor="unexpected-plugin-private-string", strict=True)
        self.assertEqual(result["backend"], "other")
        self.assertNotIn("private-string", json.dumps(result))
        self.assertIsNotNone(error)


class PersistenceAuditDatabaseTests(TestCase):
    def test_real_test_database_reports_current_migrations_without_durability_claim(self) -> None:
        output = StringIO()
        call_command("audit_persistence", stdout=output)
        result = json.loads(output.getvalue())
        self.assertEqual(result["backend"], connection.vendor)
        self.assertEqual(result["connection"], "ok")
        self.assertEqual(result["migrations"], "current")
        self.assertEqual(result["durability"], "unverified")
