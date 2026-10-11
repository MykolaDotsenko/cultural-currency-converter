"""Explicit, owner-scoped editing of saved scenario metadata.

Financial baselines, budget assumptions and immutable FX observations are not
part of this form. Optimistic version checks avoid silent multi-tab overwrites.
"""

from __future__ import annotations

from django import forms
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from apps.travel.models import SavedScenario, SavedScenarioKind


class SavedScenarioMetadataForm(forms.ModelForm):
    class Meta:
        model = SavedScenario
        fields = ("title", "travel_start_date", "travel_end_date")
        widgets = {
            "title": forms.TextInput(
                attrs={"class": "qa-text-input", "autocomplete": "off", "maxlength": "120"}
            ),
            "travel_start_date": forms.DateInput(
                attrs={"class": "qa-text-input", "type": "date"}, format="%Y-%m-%d"
            ),
            "travel_end_date": forms.DateInput(
                attrs={"class": "qa-text-input", "type": "date"}, format="%Y-%m-%d"
            ),
        }

    def __init__(self, *args, instance: SavedScenario, **kwargs):
        super().__init__(*args, instance=instance, **kwargs)
        if instance.kind != SavedScenarioKind.BUDGET:
            self.fields.pop("travel_start_date")
            self.fields.pop("travel_end_date")

    def clean(self):
        cleaned = super().clean()
        if "travel_start_date" in self.fields:
            start = cleaned.get("travel_start_date")
            end = cleaned.get("travel_end_date")
            if end is not None and start is None:
                self.add_error("travel_start_date", "A start date is required for an end date.")
            elif start is not None and end is not None and end < start:
                self.add_error("travel_end_date", "The end date cannot precede the start date.")
        return cleaned


def _render_edit(
    request: HttpRequest, scenario: SavedScenario, form: SavedScenarioMetadataForm, *, status=200
) -> HttpResponse:
    response = render(
        request,
        "travel/edit_saved_scenario.html",
        {
            "scenario": scenario,
            "form": form,
            "version": scenario.updated_at.isoformat(),
        },
        status=status,
    )
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def edit_saved_scenario(request: HttpRequest, scenario_id: int) -> HttpResponse:
    owned = SavedScenario.objects.filter(user=request.user)
    if request.method == "GET":
        scenario = get_object_or_404(owned, pk=scenario_id)
        return _render_edit(
            request, scenario, SavedScenarioMetadataForm(instance=scenario)
        )

    with transaction.atomic():
        scenario = get_object_or_404(owned.select_for_update(), pk=scenario_id)
        if request.POST.get("version", "") != scenario.updated_at.isoformat():
            form = SavedScenarioMetadataForm(instance=scenario)
            form.add_error(
                None,
                "This scenario changed since you opened the editor. Review the latest values.",
            )
            return _render_edit(request, scenario, form, status=409)

        form = SavedScenarioMetadataForm(request.POST, instance=scenario)
        if not form.is_valid():
            return _render_edit(request, scenario, form, status=422)

        edited = form.save(commit=False)
        updated_fields = ["title", "updated_at"]
        if scenario.kind == SavedScenarioKind.BUDGET:
            updated_fields.extend(("travel_start_date", "travel_end_date"))
        edited.save(update_fields=updated_fields)
        return redirect("saved_scenario_detail", scenario_id=scenario.pk)
