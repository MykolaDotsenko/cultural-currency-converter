"""Release evidence completeness is separate from factual production certification."""

from __future__ import annotations

import json

from scripts.validate_release_manifest import main, validate_manifest

_SHA = "a" * 40
_URL = "https://example.test/audit/record"


def _valid():
    import scripts.validate_release_manifest as lib

    item = {"sha": _SHA, "status": "passed", "evidence_url": _URL}
    return {
        "schema_version": 1,
        "candidate_sha": _SHA,
        "live_sha": _SHA,
        "ci": {k: dict(item) for k in lib._CI},
        "operations": {k: dict(item) for k in lib._OPERATIONS},
    }


def test_complete_manifest_does_not_claim_automatic_certification(tmp_path, capsys):
    path = tmp_path / "release.json"
    path.write_text(json.dumps(_valid()), encoding="utf-8")
    assert main(["--manifest", str(path), "--expected-sha", _SHA]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "evidence_manifest_complete"
    assert output["production_certification"] == "requires_independent_verification"


def test_mismatched_live_revision_fails_closed():
    record = _valid()
    record["live_sha"] = "b" * 40
    assert validate_manifest(record, _SHA) == ("live_sha",)


def test_missing_branch_protection_evidence_is_never_complete():
    record = _valid()
    record["operations"].pop("protected_master")
    assert "operations" in validate_manifest(record, _SHA)


def test_unverified_database_restore_fails():
    record = _valid()
    record["operations"]["database_recovery"]["status"] = "pending"
    assert "operations.database_recovery" in validate_manifest(record, _SHA)


def test_stale_ci_sha_is_not_accepted():
    record = _valid()
    record["ci"]["postgres"]["sha"] = "b" * 40
    assert "ci.postgres" in validate_manifest(record, _SHA)


def test_untrusted_link_cannot_leak_into_operator_output(tmp_path, capsys):
    record = _valid()
    record["ci"]["python_313"]["evidence_url"] = (
        "https://user:password@secret.example.test/?token=123"
    )
    path = tmp_path / "private.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    assert main(["--manifest", str(path), "--expected-sha", _SHA]) == 1
    result = capsys.readouterr().err
    assert "ci.python_313" in result
    assert "password" not in result
    assert "secret.example" not in result
    assert "token=123" not in result


def test_malformed_manifest_never_passes(tmp_path, capsys):
    path = tmp_path / "bad.json"
    path.write_text("{secret garbage}", encoding="utf-8")
    assert main(["--manifest", str(path), "--expected-sha", _SHA]) == 1
    assert "secret garbage" not in capsys.readouterr().err
