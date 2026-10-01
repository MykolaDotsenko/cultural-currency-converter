from __future__ import annotations

from apps.exchange.camera import CameraTokenError, load_confirmed_camera_amount_token
from apps.travel.camera_scope import camera_scope_for_scenario
from apps.travel.models import (
    SavedScenario,
    SavedScenarioKind,
    SavedScenarioSpendEntry,
    SavedScenarioSpendSource,
)
from apps.travel.scenarios import SavedScenarioError, record_scenario_spend

MAX_CONFIRMED_CAMERA_TOKEN_LENGTH = 2048


class CameraSpendHandoffError(ValueError):
    """Raised when a confirmed Camera amount cannot enter trip-budget persistence."""


def record_confirmed_camera_spend(
    scenario: SavedScenario,
    *,
    confirmed_camera_token: str,
) -> SavedScenarioSpendEntry:
    """Persist one explicit Camera-confirmed spend through the shared spend contract.

    The signed token is the only source of the amount/currency. Its signed
    confirmation id becomes the spend idempotency key, so replaying the same
    confirmed handoff cannot double-count spend while a separate confirmation
    of the same amount remains a distinct user action.
    """

    if scenario.pk is None:
        raise CameraSpendHandoffError("Saved scenario must exist before Camera spend can be added.")
    if scenario.kind != SavedScenarioKind.BUDGET:
        raise CameraSpendHandoffError("Camera-confirmed spend requires a saved budget scenario.")

    token = confirmed_camera_token.strip()
    if not token:
        raise CameraSpendHandoffError("Confirmed camera amount token is missing.")
    if len(token) > MAX_CONFIRMED_CAMERA_TOKEN_LENGTH:
        raise CameraSpendHandoffError("Confirmed camera amount token is invalid.")

    scope = camera_scope_for_scenario(scenario.pk)
    try:
        snapshot = load_confirmed_camera_amount_token(
            token,
            expected_scope=scope,
        )
    except CameraTokenError as exc:
        raise CameraSpendHandoffError(str(exc)) from exc

    destination_currency = scenario.destination_currency.code
    if snapshot.currency_code != destination_currency:
        raise CameraSpendHandoffError(
            "Confirmed camera amount currency does not match this saved trip."
        )

    submission_key = snapshot.confirmation_id
    try:
        return record_scenario_spend(
            scenario,
            amount=snapshot.amount,
            source=SavedScenarioSpendSource.CAMERA,
            submission_key=submission_key,
        )
    except SavedScenarioError as exc:
        raise CameraSpendHandoffError(str(exc)) from exc
