from __future__ import annotations

from apps.common.job_observability import ObservableJobCommand
from django.utils import timezone

from apps.travel.notification_delivery import generate_due_notifications


class Command(ObservableJobCommand):
    job_name = "scenario_notifications"
    help = (
        "Generate due owner-scoped in-app notifications for explicitly enabled saved-scenario "
        "preferences. Safe to run repeatedly; delivery dedupe is database-enforced."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--scenario-id",
            action="append",
            type=int,
            dest="scenario_ids",
            help="Restrict delivery generation to one scenario id; may be repeated.",
        )

    def handle(self, *args, **options) -> None:
        deliveries = generate_due_notifications(
            now=timezone.now(),
            scenario_ids=options.get("scenario_ids"),
        )
        self.set_job_counts(records_processed=len(deliveries), records_created=len(deliveries))
        self.stdout.write(self.style.SUCCESS(f"Created {len(deliveries)} in-app notification(s)."))
