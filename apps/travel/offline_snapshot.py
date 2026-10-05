from __future__ import annotations

import hashlib
import json

from apps.travel.models import SavedScenario

OFFLINE_TRIP_SNAPSHOT_VERSION = 1


def build_offline_snapshot_revision(scenario: SavedScenario) -> str:
    """Fingerprint the saved state represented by one explicit device snapshot.

    The revision is lifecycle metadata only. It is not authentication, a
    signature, or proof that any financial value is current.
    """

    payload = {
        "version": OFFLINE_TRIP_SNAPSHOT_VERSION,
        "scenario": {
            "id": scenario.pk,
            "updated_at": scenario.updated_at.isoformat() if scenario.updated_at else "",
            "kind": scenario.kind,
            "title": scenario.title,
            "source_amount": str(scenario.source_amount),
            "budget_basis": scenario.budget_basis,
            "planning_destination_amount": (
                str(scenario.planning_destination_amount)
                if scenario.planning_destination_amount is not None
                else None
            ),
            "duration_days": scenario.duration_days,
            "travelers": scenario.travelers,
            "travel_start_date": (
                scenario.travel_start_date.isoformat() if scenario.travel_start_date else None
            ),
            "travel_end_date": (
                scenario.travel_end_date.isoformat() if scenario.travel_end_date else None
            ),
        },
        "budget_items": [
            (
                item.pk,
                item.category,
                str(item.units_per_person_per_day),
                item.updated_at.isoformat() if item.updated_at else "",
            )
            for item in scenario.budget_items.all()
        ],
        "observations": [
            (
                observation.pk,
                observation.kind,
                str(observation.input_amount),
                str(observation.output_amount),
                str(observation.rate),
                observation.effective_date.isoformat(),
                observation.fetched_at.isoformat(),
                bool(observation.stale),
                tuple(str(key) for key in observation.provider_keys),
            )
            for observation in scenario.observations.all()
        ],
        "spend_entries": [
            (
                entry.pk,
                str(entry.amount),
                entry.source,
                entry.recorded_at.isoformat(),
            )
            for entry in scenario.spend_entries.all()
        ],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]
