"""Owner-only, versioned travel budget re-planning interface."""

from __future__ import annotations

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

    if request.method == "GET":
        return _render(
            request,
            scenario,
            BudgetReplanningForm(
                initial={"travelers": scenario.travelers, "duration_days": scenario.duration_days}
            ),
        )

    form = BudgetReplanningForm(request.POST)
    if not form.is_valid():
        return _render(request, scenario, form, status=422)

    try:
        replan_budget(
            owner_id=request.user.pk,
            scenario_id=scenario.pk,
            expected_version=request.POST.get("version", ""),
            travelers=form.cleaned_data["travelers"],
            duration_days=form.cleaned_data["duration_days"],
        )
    except ReplanningConflict as exc:
        scenario.refresh_from_db()
        current = BudgetReplanningForm(
            initial={"travelers": scenario.travelers, "duration_days": scenario.duration_days}
        )
        return _render(request, scenario, current, status=409, error=str(exc))
    except ReplanningError as exc:
        scenario.refresh_from_db()
        return _render(request, scenario, form, status=422, error=str(exc))

    return redirect("saved_scenario_detail", scenario_id=scenario.pk)
