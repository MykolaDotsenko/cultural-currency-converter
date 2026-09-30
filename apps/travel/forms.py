from __future__ import annotations

from django import forms

from apps.travel.models import SavedScenarioKind


class SavedScenarioCreateForm(forms.Form):
    kind = forms.ChoiceField(
        choices=(
            (SavedScenarioKind.TRIP, "Trip plan"),
            (SavedScenarioKind.BUDGET, "Budget plan"),
        ),
        initial=SavedScenarioKind.TRIP,
        label="Plan type",
        widget=forms.Select(attrs={"class": "qa-native-select"}),
    )
    title = forms.CharField(
        required=False,
        max_length=120,
        label="Plan name",
        widget=forms.TextInput(
            attrs={
                "class": "qa-text-input",
                "autocomplete": "off",
                "placeholder": "Tokyo spring trip",
            }
        ),
    )
    travel_start_date = forms.DateField(
        required=False,
        label="Start date",
        widget=forms.DateInput(attrs={"class": "qa-text-input", "type": "date"}),
    )
    travel_end_date = forms.DateField(
        required=False,
        label="End date",
        widget=forms.DateInput(attrs={"class": "qa-text-input", "type": "date"}),
    )

    def add_error(self, field, error):
        super().add_error(field, error)
        if field and field in self.fields:
            widget = self.fields[field].widget
            existing = str(widget.attrs.get("aria-describedby", "")).strip()
            descriptions = " ".join(
                item for item in (f"{field}-error", existing) if item
            )
            widget.attrs.update(
                {
                    "aria-invalid": "true",
                    "aria-describedby": descriptions,
                }
            )

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("travel_start_date")
        end = cleaned.get("travel_end_date")
        if start and end and end < start:
            self.add_error("travel_end_date", "End date cannot be before the start date.")

        title = cleaned.get("title")
        if isinstance(title, str):
            cleaned["title"] = title.strip()
        return cleaned
