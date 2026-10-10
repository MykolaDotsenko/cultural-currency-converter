"""Economic sync scheduler entrypoint: explicit approval, provider and DB preflight."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _ROOT / "scripts" / "render-economic-sync-job.sh"


def _run(tmp_path, *, approved=None, source=None, fail=""):
    fake = tmp_path / "python"
    fake.write_text(
        "#!/bin/sh\n"
        'printf "%s\\n" "$*" >> "$TRACE_FILE"\n'
        'if [ "$2" = "$FAIL_STAGE" ]; then exit 11; fi\n',
        encoding="utf-8",
    )
    fake.chmod(0o755)
    log = tmp_path / "trace.txt"
    env = {
        **os.environ,
        "PATH": f"{tmp_path}:/usr/bin:/bin",
        "TRACE_FILE": str(log),
        "FAIL_STAGE": fail,
    }
    env.pop("ECONOMIC_CONTEXT_SCHEDULER_APPROVED", None)
    env.pop("ECONOMIC_SYNC_SOURCE", None)
    if approved is not None:
        env["ECONOMIC_CONTEXT_SCHEDULER_APPROVED"] = approved
    if source is not None:
        env["ECONOMIC_SYNC_SOURCE"] = source
    result = subprocess.run(
        ["bash", str(_SCRIPT)],
        cwd=_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    calls = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    return result.returncode, calls


@pytest.mark.parametrize("approved", [None, "", "True", "yes", "1", "false"])
def test_no_execution_without_explicit_approval(tmp_path, approved):
    status, calls = _run(tmp_path, approved=approved, source="world_bank")
    assert status == 78
    assert calls == []


@pytest.mark.parametrize("source", [None, "", "WorldBank", "invalid"])
def test_no_execution_without_allowlisted_provider(tmp_path, source):
    status, calls = _run(tmp_path, approved="true", source=source)
    assert status == 64
    assert calls == []


def test_operator_approved_economic_sync_is_strict_and_ordered(tmp_path):
    status, calls = _run(tmp_path, approved="true", source="world_bank")
    assert status == 0
    assert calls == [
        "manage.py audit_persistence --require-postgresql",
        "manage.py check_reference_catalog",
        "manage.py sync_economic_context --source world_bank --require-observations",
    ]


@pytest.mark.parametrize("failure", ["audit_persistence", "check_reference_catalog"])
def test_preflight_failure_blocks_external_ingestion(tmp_path, failure):
    status, calls = _run(tmp_path, approved="true", source="world_bank", fail=failure)
    assert status == 11
    assert "manage.py sync_economic_context --source world_bank --require-observations" not in calls
