from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from enum import StrEnum

from apps.travel.models import SavedScenarioObservation


class ScenarioRateDirection(StrEnum):
    HIGHER = "higher"
    LOWER = "lower"
    UNCHANGED = "unchanged"


@dataclass(frozen=True, slots=True)
class ScenarioObservationComparison:
    """Deterministic difference between two trusted observations for one scenario."""

    initial: SavedScenarioObservation
    latest: SavedScenarioObservation
    output_amount_difference: Decimal
    rate_difference: Decimal
    rate_difference_percent: Decimal
    direction: ScenarioRateDirection

    @property
    def changed(self) -> bool:
        return self.direction is not ScenarioRateDirection.UNCHANGED


def compare_scenario_observations(
    initial: SavedScenarioObservation,
    latest: SavedScenarioObservation,
) -> ScenarioObservationComparison:
    """Compare saved observations without attaching investment meaning."""

    if initial.scenario_id != latest.scenario_id:
        raise ValueError("Scenario observations must belong to the same saved scenario.")
    if initial.input_amount != latest.input_amount:
        raise ValueError("Scenario observations must use the same source amount.")
    if initial.rate <= 0 or latest.rate <= 0:
        raise ValueError("Scenario observation rates must be positive.")

    rate_difference = latest.rate - initial.rate
    output_difference = latest.output_amount - initial.output_amount
    try:
        rate_difference_percent = (rate_difference / initial.rate * Decimal("100")).quantize(
            Decimal("0.1"), rounding=ROUND_HALF_EVEN
        )
    except InvalidOperation as exc:
        raise ValueError("Scenario rate difference cannot be represented.") from exc

    if rate_difference > 0:
        direction = ScenarioRateDirection.HIGHER
    elif rate_difference < 0:
        direction = ScenarioRateDirection.LOWER
    else:
        direction = ScenarioRateDirection.UNCHANGED

    return ScenarioObservationComparison(
        initial=initial,
        latest=latest,
        output_amount_difference=output_difference,
        rate_difference=rate_difference,
        rate_difference_percent=rate_difference_percent,
        direction=direction,
    )
