from __future__ import annotations


def camera_scope_for_scenario(scenario_id: int) -> str:
    if scenario_id <= 0:
        raise ValueError("Saved-scenario camera scope requires a positive scenario id.")
    return f"saved-scenario:{scenario_id}"
