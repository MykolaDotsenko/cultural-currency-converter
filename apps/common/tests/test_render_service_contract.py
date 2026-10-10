"""Render config drift checks must fail closed without echoing credentials."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.check_render_service_contract import blueprint_contract, compare_service, main

_ROOT = Path(__file__).resolve().parents[3]


def _service(expected: dict[str, str]) -> dict:
    return {
        "name": expected["name"],
        "branch": expected["branch"],
        "autoDeploy": expected["autoDeploy"],
        "autoDeployTrigger": expected["autoDeployTrigger"],
        "serviceDetails": {
            "buildCommand": expected["buildCommand"],
            "startCommand": expected["startCommand"],
            "healthCheckPath": expected["healthCheckPath"],
        },
    }


def test_blueprint_contract_matches_repository_manifest() -> None:
    expected = blueprint_contract(_ROOT / "render.yaml")
    assert expected["healthCheckPath"] == "/health/ready/"
    assert expected["autoDeployTrigger"] == "checksPass"
    assert expected["startCommand"] == "bash scripts/render-start.sh"


def test_matching_render_service_passes() -> None:
    expected = blueprint_contract(_ROOT / "render.yaml")
    assert compare_service(_service(expected), expected) == {"status": "match", "fields": []}


def test_actual_render_drift_reports_only_field_names() -> None:
    expected = blueprint_contract(_ROOT / "render.yaml")
    observed = _service(expected)
    observed["autoDeployTrigger"] = "commit"
    observed["serviceDetails"]["healthCheckPath"] = ""
    observed["credentials"] = "PROTECTED_TOKEN_SHOULD_NEVER_APPEAR"
    assert compare_service(observed, expected) == {
        "status": "mismatch",
        "fields": ["healthCheckPath", "autoDeployTrigger"],
    }


def test_missing_details_are_unverifiable_not_green() -> None:
    expected = blueprint_contract(_ROOT / "render.yaml")
    result = compare_service({"name": expected["name"]}, expected)
    assert result["status"] == "unknown"
    assert "healthCheckPath" in result["fields"]


def test_cli_drift_exit_is_nonzero_without_leaking_values(tmp_path, capsys) -> None:
    expected = blueprint_contract(_ROOT / "render.yaml")
    observed = _service(expected)
    observed["autoDeployTrigger"] = "SECRET_VALUE"
    source = tmp_path / "render-private-service.json"
    source.write_text(json.dumps(observed), encoding="utf-8")
    status = main(["--service-json", str(source), "--blueprint", str(_ROOT / "render.yaml")])
    result = capsys.readouterr().out
    assert status == 1
    assert json.loads(result) == {"fields": ["autoDeployTrigger"], "status": "mismatch"}
    assert "SECRET_VALUE" not in result


def test_cli_fails_closed_when_input_is_invalid(tmp_path, capsys) -> None:
    source = tmp_path / "service.json"
    source.write_text("{bad-json-with-secret}", encoding="utf-8")
    status = main(["--service-json", str(source), "--blueprint", str(_ROOT / "render.yaml")])
    assert status == 1
    assert "bad-json-with-secret" not in capsys.readouterr().out


@pytest.mark.parametrize("kind", ["missing", "duplicate"])
def test_incomplete_blueprint_never_passes(kind: str, tmp_path) -> None:
    original = (_ROOT / "render.yaml").read_text(encoding="utf-8")
    if kind == "missing":
        original = original.replace("    healthCheckPath: /health/ready/\n", "")
    else:
        original += "\n    healthCheckPath: /health/ready/\n"
    path = tmp_path / "render.yaml"
    path.write_text(original, encoding="utf-8")
    with pytest.raises(ValueError):
        blueprint_contract(path)
