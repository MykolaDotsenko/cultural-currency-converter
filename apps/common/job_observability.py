"""Privacy-bounded structured completion records for operator-run background jobs.

This emits only allow-listed job names, outcomes, elapsed time and aggregate counts.
It never logs raw exception messages, scenario identifiers or provider responses.
"""

from __future__ import annotations

import logging
from time import monotonic

from django.core.management.base import BaseCommand

logger = logging.getLogger("cultural_currency.jobs")

_ALLOWED_JOBS = frozenset(
    {"scenario_notifications", "economic_context", "public_holidays"}
)
_COUNT_KEYS = frozenset({"records_processed", "records_created", "records_updated", "records_retired"})


class ObservableJobCommand(BaseCommand):
    """Management-command lifecycle telemetry, preserving command exceptions."""

    job_name: str = ""

    def set_job_counts(self, **counts: int) -> None:
        if not counts.keys() <= _COUNT_KEYS or any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in counts.values()
        ):
            raise ValueError("Invalid background-job aggregate counters.")
        self._job_counts = counts

    def execute(self, *args, **options):
        if self.job_name not in _ALLOWED_JOBS:
            raise ValueError("Unknown background job.")
        self._job_counts: dict[str, int] = {}
        start = monotonic()
        try:
            result = super().execute(*args, **options)
        except Exception:
            logger.warning(
                "background_job_result",
                extra={
                    "job": self.job_name,
                    "outcome": "failure",
                    "duration_ms": round((monotonic() - start) * 1000, 2),
                    "error_code": "job_failed",
                    "dry_run": bool(options.get("dry_run", False)),
                },
            )
            raise

        logger.info(
            "background_job_result",
            extra={
                "job": self.job_name,
                "outcome": "success",
                "duration_ms": round((monotonic() - start) * 1000, 2),
                "dry_run": bool(options.get("dry_run", False)),
                **self._job_counts,
            },
        )
        return result
