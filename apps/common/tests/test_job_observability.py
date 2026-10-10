"""Privacy and lifecycle regression checks for scheduled-command telemetry."""

from __future__ import annotations

import json
import logging
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from apps.common.job_observability import ObservableJobCommand
from apps.common.observability import JsonFormatter


class JobObservabilityTests(SimpleTestCase):
    def test_scenario_notification_completion_reports_aggregate_only(self) -> None:
        deliveries = (object(), object())
        with (
            patch(
                "apps.travel.management.commands.deliver_scenario_notifications."
                "generate_due_notifications",
                return_value=deliveries,
            ),
            self.assertLogs("cultural_currency.jobs", level="INFO") as logs,
        ):
            call_command("deliver_scenario_notifications", stdout=StringIO())

        self.assertEqual(len(logs.records), 1)
        record = logs.records[0]
        self.assertEqual(record.job, "scenario_notifications")
        self.assertEqual(record.outcome, "success")
        self.assertEqual(record.records_processed, 2)
        self.assertEqual(record.records_created, 2)
        self.assertGreaterEqual(record.duration_ms, 0)
        self.assertFalse(record.dry_run)
        self.assertNotIn("object at", JsonFormatter().format(record))

    def test_exception_does_not_log_private_error_text_or_exception(self) -> None:
        with (
            patch(
                "apps.travel.management.commands.deliver_scenario_notifications."
                "generate_due_notifications",
                side_effect=RuntimeError("password=very-private SECRET-amount 1234"),
            ),
            self.assertLogs("cultural_currency.jobs", level="WARNING") as logs,
            self.assertRaisesRegex(RuntimeError, "very-private"),
        ):
            call_command("deliver_scenario_notifications", stdout=StringIO())

        self.assertEqual(len(logs.records), 1)
        record = logs.records[0]
        self.assertEqual(record.outcome, "failure")
        self.assertEqual(record.error_code, "job_failed")
        self.assertIsNone(record.exc_info)
        serialized = json.dumps(json.loads(JsonFormatter().format(record)))
        self.assertNotIn("very-private", serialized)
        self.assertNotIn("SECRET-amount", serialized)
        self.assertNotIn("1234", serialized)
        self.assertNotIn("traceback", serialized.lower())

    def test_invalid_command_arguments_are_reported_without_values(self) -> None:
        with (
            self.assertLogs("cultural_currency.jobs", level="WARNING") as logs,
            self.assertRaises(CommandError),
        ):
            call_command("sync_public_holidays", years_ahead=8, stdout=StringIO())
        record = logs.records[0]
        self.assertEqual(record.job, "public_holidays")
        self.assertEqual(record.outcome, "failure")

    def test_aggregate_counters_reject_identifiers_and_negative_values(self) -> None:
        cmd = ObservableJobCommand()
        for invalid in ({"scenario_id": 123}, {"records_created": -1}, {"records_updated": True}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                cmd.set_job_counts(**invalid)

    def test_allowlisted_log_format_excludes_untrusted_attributes(self) -> None:
        record = logging.LogRecord(
            name="cultural_currency.jobs",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="background_job_result",
            args=(),
            exc_info=None,
        )
        record.job = "public_holidays"
        record.outcome = "success"
        record.dry_run = True
        record.records_processed = 5
        record.records_created = 2
        record.records_updated = 3
        record.records_retired = 0
        record.private_scenario = "secret-private-owner"
        formatted = json.loads(JsonFormatter().format(record))
        for field in ("job", "outcome", "dry_run", "records_processed", "records_retired"):
            self.assertIn(field, formatted)
        self.assertNotIn("private_scenario", formatted)
        self.assertNotIn("secret-private-owner", json.dumps(formatted))
