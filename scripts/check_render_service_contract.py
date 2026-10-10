#!/usr/bin/env python3
"""Read-only Render service drift check; reports field names, never secrets."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

_FIELDS = (
    "name",
    "branch",
    "buildCommand",
    "startCommand",
    "healthCheckPath",
    "autoDeployTrigger",
)
_LIVE_FIELDS = (*_FIELDS, "autoDeploy")


def blueprint_contract(path: Path) -> dict[str, str]:
    """Read the fixed scalar contract of the repository's single Render web service."""

    source = path.read_text(encoding="utf-8")
    if len(re.findall(r"^  - type: web\s*$", source, re.MULTILINE)) != 1:
        raise ValueError("Expected one Render web service in the blueprint.")

    expected = {}
    for key in _FIELDS:
        matches = re.findall(rf"^    {re.escape(key)}: (.+)$", source, re.MULTILINE)
        if len(matches) != 1:
            raise ValueError("Missing or duplicated Render contract field.")
        value = matches[0].strip().strip('"').strip("'")
        if not value:
            raise ValueError("Empty Render contract field.")
        expected[key] = value
    expected["autoDeploy"] = "yes"
    return expected


def compare_service(service: Any, expected: dict[str, str]) -> dict[str, object]:
    """Never reflect any untrusted service values in public/operator output."""

    if not isinstance(service, dict):
        return {"status": "unknown", "fields": list(_LIVE_FIELDS)}
    details = service.get("serviceDetails")
    if not isinstance(details, dict):
        return {"status": "unknown", "fields": list(_LIVE_FIELDS)}

    observed = {
        "name": service.get("name"),
        "branch": service.get("branch"),
        "buildCommand": details.get("buildCommand"),
        "startCommand": details.get("startCommand"),
        "healthCheckPath": details.get("healthCheckPath"),
        "autoDeployTrigger": service.get("autoDeployTrigger"),
        "autoDeploy": service.get("autoDeploy"),
    }
    missing = [key for key in _LIVE_FIELDS if not isinstance(observed[key], str)]
    if missing:
        return {"status": "unknown", "fields": missing}
    mismatches = [key for key in _LIVE_FIELDS if observed[key] != expected[key]]
    return {"status": "mismatch" if mismatches else "match", "fields": mismatches}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service-json", type=Path, required=True)
    parser.add_argument("--blueprint", type=Path, default=Path("render.yaml"))
    args = parser.parse_args(argv)
    try:
        expected = blueprint_contract(args.blueprint)
        supplied = json.loads(args.service_json.read_text(encoding="utf-8"))
        if isinstance(supplied, dict) and "service" in supplied:
            supplied = supplied["service"]
        result = compare_service(supplied, expected)
    except (OSError, ValueError, TypeError):
        result = {"status": "unknown", "fields": list(_LIVE_FIELDS)}

    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "match" else 1


if __name__ == "__main__":
    raise SystemExit(main())
