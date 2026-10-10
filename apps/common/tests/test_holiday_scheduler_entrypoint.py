"""Read-only tests of the holiday scheduled ingestion shell admission gates."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _ROOT / "scripts" / "render-holiday-sync-job.sh"


def _run(tmp_path, *, approved=None, country=None, years="1", fail=""):
    fake = tmp_path / "python"
    fake.write_text(
        "#!/bin/sh\n"
        'printf "%s\\n" "$*" >> "$TRACE_FILE"\n'
        'if [ "$2" = "$FAIL_STAGE" ]; then exit 11; fi\n',
        encoding="utf-8",
    )
    fake.chmod(0o755)
    trace = tmp_path / "trace.txt"
    env = {
        **os.environ,
        "PATH": f"{tmp_path}:/usr/bin:/bin",
        "TRACE_FILE": str(trace),
        "FAIL_STAGE": fail,
        "HOLIDAY_SYNC_YEARS_AHEAD": years,
    }
    env.pop("HOLIDAY_SYNC_SCHEDULER_APPROVED", None)
    env.pop("HOLIDAY_SYNC_COUNTRY", None)
    if approved is not None:
        env["HOLIDAY_SYNC_SCHEDULER_APPROVED"] = approved
    if country is not None:
        env["HOLIDAY_SYNC_COUNTRY"] = country
    result = subprocess.run(
        ["bash", str(_SCRIPT)],
        cwd=_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    calls = trace.read_text(encoding="utf-8").splitlines() if trace.exists() else []
    return result.returncode, calls


@pytest.mark.parametrize("approved", [None, "", "yes", "True", "1"])
def test_unapproved_holiday_job_has_no_side_effects(tmp_path, approved):
    code, calls = _run(tmp_path, approved=approved, country="FI")
    assert code == 78
    assert calls == []


@pytest.mark.parametrize(
    "country,years",
    [
        (None, "1"),
        ("fi", "1"),
        ("FI;rm", "1"),
        ("FI", "6"),
        ("FI", "1;rm"),
    ],
)
def test_unapproved_scope_never_calls_django(tmp_path, country, years):
    code, calls = _run(tmp_path, approved="true", country=country, years=years)
    assert code == 64
    assert calls == []


def test_approved_country_year_job_is_strict_and_ordered(tmp_path):
    code, calls = _run(tmp_path, approved="true", country="FI", years="2")
    assert code == 0
    assert calls == [
        "manage.py audit_persistence --require-postgresql",
        "manage.py check_reference_catalog",
        "manage.py sync_public_holidays --country FI --years-ahead 2 --require-nonempty-scopes",
    ]


@pytest.mark.parametrize("fail", ["audit_persistence", "check_reference_catalog"])
def test_unhealthy_database_or_catalog_blocks_provider_calls(tmp_path, fail):
    code, calls = _run(tmp_path, approved="true", country="FI", fail=fail)
    assert code == 11
    assert not any("sync_public_holidays" in x for x in calls)
