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


def test_production_revision_watch_is_read_only_and_never_runs_on_pr_heads():
    workflow = (_WORKFLOWS / "production-deployment-drift.yml").read_text()

    assert 'cron: "17 8,20 * * *"' in workflow
    assert "workflow_dispatch:" in workflow
    assert "pull_request:" not in workflow
    assert "  push:" not in workflow
    assert "permissions:\n  contents: read" in workflow
    assert "ref: master" in workflow
    assert "persist-credentials: false" in workflow
    assert "python scripts/check_deployment_revision.py" in workflow
    assert '--expected-sha "$expected_sha"' in workflow
    assert "exit 1" in workflow
    assert "sleep 20" in workflow
    assert "https://cultural-currency-converter-mykola.onrender.com/health/revision/" in workflow
