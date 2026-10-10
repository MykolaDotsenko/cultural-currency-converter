#!/usr/bin/env python3
"""Validate a release-evidence manifest's completeness, never certify production.

Claims and evidence URLs are supplied by operators; this tool cannot prove
that events happened or that linked records are authentic.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

_CI = frozenset(
    {"python_313", "python_314", "postgres", "frontend", "chromium", "firefox", "webkit"}
)
_OPERATIONS = frozenset(
    {
        "protected_master",
        "no_open_p0_p1",
        "durable_restart",
        "durable_redeploy",
        "database_recovery",
        "media_recovery",
        "exact_live_revision",
        "full_user_journey",
        "provider_degradation",
        "offline_privacy",
    }
)
_SHA = re.compile(r"[a-f0-9]{40}")


def _valid_reference(value: object) -> bool:
    if not isinstance(value, str) or len(value) > 400:
        return False
    try:
        uri = urlsplit(value)
        return (
            uri.scheme == "https"
            and bool(uri.hostname)
            and uri.username is None
            and uri.password is None
            and not uri.query
            and not uri.fragment
        )
    except ValueError:
        return False


def validate_manifest(document: object, expected_sha: str) -> tuple[str, ...]:
    """Return only allow-listed names of invalid gates, never untrusted data."""

    if not _SHA.fullmatch(expected_sha):
        return ("expected_sha",)
    if not isinstance(document, dict):
        return ("manifest",)
    problems: list[str] = []
    if set(document) != {"schema_version", "candidate_sha", "live_sha", "ci", "operations"}:
        problems.append("schema")
    if document.get("schema_version") != 1:
        problems.append("schema_version")
    if document.get("candidate_sha") != expected_sha:
        problems.append("candidate_sha")
    if document.get("live_sha") != expected_sha:
        problems.append("live_sha")

    for key, required in (("ci", _CI), ("operations", _OPERATIONS)):
        evidence = document.get(key)
        if not isinstance(evidence, dict) or set(evidence) != required:
            problems.append(key)
            continue
        for name in sorted(required):
            row = evidence[name]
            if (
                not isinstance(row, dict)
                or set(row) != {"sha", "status", "evidence_url"}
                or row.get("sha") != expected_sha
                or row.get("status") != "passed"
                or not _valid_reference(row.get("evidence_url"))
            ):
                problems.append(f"{key}.{name}")
    return tuple(problems)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--expected-sha", required=True)
    args = parser.parse_args(argv)
    try:
        document = json.loads(args.manifest.read_text(encoding="utf-8"))
        problems = validate_manifest(document, args.expected_sha)
    except (OSError, UnicodeError, json.JSONDecodeError):
        problems = ("manifest_unreadable",)
    if problems:
        print(json.dumps({"status": "incomplete", "invalid_gates": problems}), file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "status": "evidence_manifest_complete",
                "production_certification": "requires_independent_verification",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
