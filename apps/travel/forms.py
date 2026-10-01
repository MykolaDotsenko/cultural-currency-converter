from __future__ import annotations

from typing import Any

from django import forms


class SavedScenarioPlanningForm(forms.Form):
    """Optional account-owned planning metadata for a saved scenario."""

    title = forms.CharField(required=False, max_length=120, strip=True)
    travel_start_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": "qa-text-input"}),
    )
    travel_end_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": "qa-text-input"}),
    )

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean() or {}
        start = cleaned.get("travel_start_date")
        end = cleaned.get("travel_end_date")

        if end is not None and start is None:
            self.add_error(
                "travel_start_date",
                "Add a trip start date before setting an end date.",
            )
        elif start is not None and end is not None and end < start:
            self.add_error(
                "travel_end_date",
                "Trip end date cannot be before the start date.",
            )

        return cleaned
