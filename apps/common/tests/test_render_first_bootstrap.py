"""Deploy startup is fail-closed and bootstraps ONLY a reviewed empty PostgreSQL."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_START = _ROOT / "scripts" / "render-start.sh"
_RELEASE_SHA = "a" * 40


def _launch(
    tmp_path: Path,
    *,
    approved: str | None = None,
    environment: str = "demo",
    expected_sha: str | None = None,
    actual_sha: str = _RELEASE_SHA,
    catalog_present: bool = False,
    fail: str = "",
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    python = tmp_path / "python"
    python.write_text(
        "#!/bin/sh\n"
        'printf "python %s\\n" "$*" >> "$TRACE_FILE"\n'
        'if [ "$FAIL_STAGE" = "audit" ] && [ "$2" = "audit_persistence" ]; then exit 11; fi\n'
        'if [ "$2" = "check_reference_catalog" ]; then\n'
        '  if [ "$3" = "--require-empty" ]; then\n'
        '    if [ "$FAIL_STAGE" = "not_empty" ]; then exit 11; fi\n'
        '  elif [ "$CATALOG_PRESENT" = "no" ] && [ "$FAIL_STAGE" != "seeded" ]; then\n'
        '    if [ "$CATALOG_SEEDED_FILE" != "" ] && [ -e "$CATALOG_SEEDED_FILE" ]; then :; else exit 1; fi\n'
        "  fi\n"
        "fi\n"
        'if [ "$2" = "seed_reference_data" ]; then touch "$CATALOG_SEEDED_FILE"; fi\n',
        encoding="utf-8",
    )
    python.chmod(0o755)
    gunicorn = tmp_path / "gunicorn"
    gunicorn.write_text(
        '#!/bin/sh\nprintf "gunicorn %s\\n" "$*" >> "$TRACE_FILE"\n',
        encoding="utf-8",
    )
    gunicorn.chmod(0o755)
    trace = tmp_path / "trace.txt"
    seeded = tmp_path / "seeded"
    env = {
        **os.environ,
        "PATH": f"{tmp_path}:/usr/bin:/bin",
        "TRACE_FILE": str(trace),
        "CATALOG_SEEDED_FILE": str(seeded),
        "CATALOG_PRESENT": "yes" if catalog_present else "no",
        "FAIL_STAGE": fail,
        "APP_ENV": environment,
        "RENDER_GIT_COMMIT": actual_sha,
    }
    for name in ("RENDER_BOOTSTRAP_EMPTY_POSTGRES", "RENDER_BOOTSTRAP_APPROVED_SHA"):
        env.pop(name, None)
    if approved is not None:
        env["RENDER_BOOTSTRAP_EMPTY_POSTGRES"] = approved
    if expected_sha is not None:
        env["RENDER_BOOTSTRAP_APPROVED_SHA"] = expected_sha

    result = subprocess.run(
        ["bash", str(_START)],
        cwd=_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    commands = trace.read_text(encoding="utf-8").splitlines() if trace.exists() else []
    return result, commands


def test_normal_deploy_does_not_write_reference_seeds(tmp_path: Path) -> None:
    result, commands = _launch(tmp_path, catalog_present=True)
    assert result.returncode == 0
    assert commands[0] == "python manage.py migrate --noinput"
    assert commands[1] == "python manage.py check_reference_catalog"
    assert commands[-1].startswith("gunicorn config.wsgi:application")
    assert not any("seed_" in call for call in commands)


@pytest.mark.parametrize("approved", ["", "yes", "True", "1", "off", "FALSE"])
def test_invalid_flag_exits_without_touching_database(tmp_path: Path, approved: str) -> None:
    result, commands = _launch(tmp_path, approved=approved)
    assert result.returncode == 64
    assert commands == []


@pytest.mark.parametrize("environment", ["production", "local", "test", ""])
def test_bootstrap_prohibited_outside_demo_preview(tmp_path: Path, environment: str) -> None:
    result, commands = _launch(
        tmp_path, approved="true", environment=environment, expected_sha=_RELEASE_SHA
    )
    assert result.returncode == 78
    assert commands == []


@pytest.mark.parametrize("expected_sha", [None, "", "b" * 40, "short"])
def test_bootstrap_requires_exact_running_release(tmp_path: Path, expected_sha: str | None) -> None:
    result, commands = _launch(tmp_path, approved="true", expected_sha=expected_sha)
    assert result.returncode == 78
    assert commands == []


def test_first_deployment_can_bootstrap_verified_empty_postgres(tmp_path: Path) -> None:
    result, commands = _launch(tmp_path, approved="true", expected_sha=_RELEASE_SHA)
    assert result.returncode == 0, result.stderr
    assert commands == [
        "python manage.py migrate --noinput",
        "python manage.py audit_persistence --require-postgresql",
        "python manage.py check_reference_catalog",
        "python manage.py check_reference_catalog --require-empty",
        "python manage.py seed_reference_data",
        "python manage.py seed_story_data",
        "python manage.py seed_destination_context",
        "python manage.py check_reference_catalog",
        commands[-1],
    ]
    assert commands[-1].startswith("gunicorn config.wsgi:application")


def test_existing_catalog_never_seeds_even_with_bootstrap_opt_in(tmp_path: Path) -> None:
    result, commands = _launch(
        tmp_path, approved="true", expected_sha=_RELEASE_SHA, catalog_present=True
    )
    assert result.returncode == 0
    assert commands[:3] == [
        "python manage.py migrate --noinput",
        "python manage.py audit_persistence --require-postgresql",
        "python manage.py check_reference_catalog",
    ]
    assert not any("seed_" in call for call in commands)


@pytest.mark.parametrize("failure", ["audit", "not_empty"])
def test_failed_preflight_blocks_seeding_and_gunicorn(tmp_path: Path, failure: str) -> None:
    result, commands = _launch(tmp_path, approved="true", expected_sha=_RELEASE_SHA, fail=failure)
    assert result.returncode != 0
    assert not any("seed_" in call for call in commands)
    assert not any("gunicorn" in call for call in commands)
