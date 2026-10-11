"""Owner-only, versioned travel budget re-planning interface."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django import forms
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from apps.travel.models import SavedScenario, SavedScenarioKind
from apps.travel.replanning import ReplanningConflict, ReplanningError, replan_budget


class BudgetReplanningForm(forms.Form):
    travelers = forms.IntegerField(
        min_value=1,
        max_value=20,
        widget=forms.NumberInput(attrs={"min": "1", "max": "20", "class": "qa-text-input"}),
    )
    duration_days = forms.IntegerField(
        min_value=1,
        max_value=365,
        required=False,
        widget=forms.NumberInput(attrs={"min": "1", "max": "365", "class": "qa-text-input"}),
    )

    def __init__(self, *args: Any, budget_items: tuple, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.budget_items = budget_items
        for item in budget_items:
            field_name = f"budget_item_{item.pk}"
            self.fields[field_name] = forms.DecimalField(
                label=f"{item.category.replace('_', ' ').title()} units per traveler per day",
                min_value=Decimal("0.01"),
                max_value=Decimal("100"),
                decimal_places=2,
                max_digits=5,
                required=False,
                initial=item.units_per_person_per_day,
                widget=forms.NumberInput(
                    attrs={"class": "qa-text-input", "step": "0.01", "min": "0.01", "max": "100"}
                ),
            )


def _render(
    request: HttpRequest,
    scenario: SavedScenario,
    form: BudgetReplanningForm,
    *,
    status: int = 200,
    error: str = "",
) -> HttpResponse:
    response = render(
        request,
        "travel/replan_saved_budget.html",
        {
            "scenario": scenario,
            "form": form,
            "version": scenario.updated_at.isoformat(),
            "revisions": tuple(scenario.plan_revisions.order_by("-revision")[:21]),
            "error": error,
        },
        status=status,
    )
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def replan_saved_budget(request: HttpRequest, scenario_id: int) -> HttpResponse:
    scenario = get_object_or_404(
        SavedScenario.objects.filter(user=request.user),
        pk=scenario_id,
    )
    if scenario.kind != SavedScenarioKind.BUDGET:
        raise Http404("Re-planning is available for saved budgets only.")

    budget_items = tuple(scenario.budget_items.order_by("category", "pk"))
    if request.method == "GET":
        return _render(
            request,
            scenario,
            BudgetReplanningForm(
                budget_items=budget_items,
                initial={"travelers": scenario.travelers, "duration_days": scenario.duration_days},
            ),
        )

    form = BudgetReplanningForm(request.POST, budget_items=budget_items)
    if not form.is_valid():
        return _render(request, scenario, form, status=422)

    try:
        replan_budget(
            owner_id=request.user.pk,
            scenario_id=scenario.pk,
            expected_version=request.POST.get("version", ""),
            travelers=form.cleaned_data["travelers"],
            duration_days=form.cleaned_data["duration_days"],
            budget_item_changes={
                item.pk: form.cleaned_data[f"budget_item_{item.pk}"]
                for item in budget_items
                if form.cleaned_data[f"budget_item_{item.pk}"] is not None
            },
        )
    except ReplanningConflict as exc:
        scenario.refresh_from_db()
        current = BudgetReplanningForm(
            budget_items=tuple(scenario.budget_items.order_by("category", "pk")),
            initial={"travelers": scenario.travelers, "duration_days": scenario.duration_days},
        )
        return _render(request, scenario, current, status=409, error=str(exc))
    except ReplanningError as exc:
        scenario.refresh_from_db()
        return _render(request, scenario, form, status=422, error=str(exc))

    return redirect("saved_scenario_detail", scenario_id=scenario.pk)
