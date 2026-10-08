"""Keep integration provider changes behind real CI lanes, not skipped gates."""

from __future__ import annotations

from pathlib import Path

_WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"


def test_python_workflow_covers_integrations_on_pr_and_master_push():
    workflow = (_WORKFLOWS / "django-tests.yml").read_text()
    assert workflow.count('"integrations/**"') == 2
    assert "ruff format --check --diff apps config integrations scripts manage.py" in workflow
    assert "ruff check apps config integrations scripts manage.py" in workflow


def test_browser_workflow_runs_for_provider_boundary_changes():
    workflow = (_WORKFLOWS / "browser-quality.yml").read_text()
    assert workflow.count('"integrations/**"') == 2


def test_required_merge_classifier_keeps_provider_changes_in_python_and_browser_lanes():
    workflow = (_WORKFLOWS / "required-merge-quality.yml").read_text()
    assert "apps/*|config/*|integrations/*|scripts/*" in workflow
    assert "frontend/*|templates/*|apps/*|config/*|integrations/*|scripts/*" in workflow
    assert "ruff format --check apps config integrations scripts manage.py" in workflow
    assert "ruff check apps config integrations scripts manage.py" in workflow
