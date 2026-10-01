from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import uuid4

from django import forms

from apps.exchange.forms import parse_amount_text


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


class SavedScenarioSpendForm(forms.Form):
    """Minimal confirmed-spend entry in the scenario destination currency."""

    submission_key = forms.UUIDField(
        required=False,
        widget=forms.HiddenInput(),
    )
    amount = forms.CharField(
        max_length=64,
        widget=forms.TextInput(
            attrs={
                "id": "id_spend_amount",
                "class": "qa-text-input",
                "inputmode": "decimal",
                "autocomplete": "off",
                "placeholder": "0",
            }
        ),
    )

    def __init__(
        self,
        *args: Any,
        destination_currency_code: str,
        destination_minor_units: int,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.destination_minor_units = destination_minor_units
        self.fields["amount"].label = f"Confirmed spend in {destination_currency_code}"
        if not self.is_bound:
            self.fields["submission_key"].initial = uuid4()

    def add_error(self, field: str | None, error: Any) -> None:
        super().add_error(field, error)
        if field == "amount":
            self.fields["amount"].widget.attrs.update(
                {
                    "aria-invalid": "true",
                    "aria-describedby": "spend_amount-error",
                }
            )

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean() or {}
        submission_key = cleaned.get("submission_key")
        if submission_key is None:
            cleaned["submission_key"] = uuid4()

        raw = cleaned.get("amount")
        if raw is None or self.has_error("amount"):
            return cleaned

        try:
            amount = parse_amount_text(
                str(raw),
                minor_units=self.destination_minor_units,
            )
        except forms.ValidationError as exc:
            self.add_error("amount", exc)
            return cleaned

        if amount <= Decimal("0"):
            self.add_error("amount", "Enter an amount greater than zero.")
            return cleaned

        cleaned["amount_decimal"] = amount
        return cleaned
