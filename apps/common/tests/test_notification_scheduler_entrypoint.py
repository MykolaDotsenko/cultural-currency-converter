"""Scheduler entrypoint refuses unapproved or unhealthy environments."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _ROOT / "scripts" / "render-notification-job.sh"


def _invoke(tmp_path: Path, *, approved: str | None, fail: str = ""):
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
        "PATH": str(tmp_path) + ":/usr/bin:/bin",
        "TRACE_FILE": str(trace),
        "FAIL_STAGE": fail,
    }
    env.pop("SCENARIO_NOTIFICATIONS_SCHEDULER_APPROVED", None)
    if approved is not None:
        env["SCENARIO_NOTIFICATIONS_SCHEDULER_APPROVED"] = approved
    result = subprocess.run(
        ["bash", str(_SCRIPT)],
        cwd=_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    commands = trace.read_text(encoding="utf-8").splitlines() if trace.exists() else []
    return result, commands


@pytest.mark.parametrize("approved", [None, "", "yes", "True", "1", "false"])
def test_unapproved_execution_cannot_touch_database(tmp_path, approved) -> None:
    result, commands = _invoke(tmp_path, approved=approved)
    assert result.returncode == 78
    assert commands == []
    assert "Scheduler not approved" in result.stderr


def test_approved_execution_verifies_db_and_catalog_before_delivery(tmp_path) -> None:
    result, commands = _invoke(tmp_path, approved="true")
    assert result.returncode == 0
    assert commands == [
        "manage.py audit_persistence --require-postgresql",
        "manage.py check_reference_catalog",
        "manage.py deliver_scenario_notifications",
    ]


@pytest.mark.parametrize("failure", ["audit_persistence", "check_reference_catalog"])
def test_failed_preflight_prevents_notification_generation(tmp_path, failure) -> None:
    result, commands = _invoke(tmp_path, approved="true", fail=failure)
    assert result.returncode == 11
    assert commands[0] == "manage.py audit_persistence --require-postgresql"
    assert "manage.py deliver_scenario_notifications" not in commands
    if failure == "audit_persistence":
        assert len(commands) == 1
    else:
        assert len(commands) == 2
