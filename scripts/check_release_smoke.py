#!/usr/bin/env python3
"""Read-only strict live release smoke for revision, liveness and readiness.

Never proves database persistence or backup/recovery by itself.
"""

from __future__ import annotations

import argparse
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, build_opener

from scripts.check_deployment_revision import (
    RejectRedirects,
    RevisionCheckError,
    check_revision,
    validate_url,
)

_MAX_BODY_BYTES = 4096


def _health_payload(url: str, *, opener) -> dict:
    """Read a bounded JSON response from the already validated HTTPS origin."""

    try:
        request = Request(url, headers={"Accept": "application/json"})
        with opener.open(request, timeout=5) as response:
            if response.status != 200:
                raise RevisionCheckError("health_unavailable")
            media_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip()
            if media_type.lower() != "application/json":
                raise RevisionCheckError("health_invalid_response")
            body = response.read(_MAX_BODY_BYTES + 1)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise RevisionCheckError("health_unavailable") from exc

    if len(body) > _MAX_BODY_BYTES:
        raise RevisionCheckError("health_invalid_response")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RevisionCheckError("health_invalid_response") from exc
    if not isinstance(payload, dict):
        raise RevisionCheckError("health_invalid_response")
    return payload


def check_release_smoke(
    revision_url: str,
    expected_sha: str,
    *,
    require_shared_cache: bool = False,
    opener=None,
) -> dict[str, str]:
    """Confirm exact SHA + live process + ready DB, never stored-data durability."""

    validate_url(revision_url)
    transport = opener if opener is not None else build_opener(RejectRedirects())
    revision = check_revision(revision_url, expected_sha, opener=transport)

    base = urlsplit(revision_url)
    live = urlunsplit(base._replace(path="/health/live/"))
    ready = urlunsplit(base._replace(path="/health/ready/"))

    live_payload = _health_payload(live, opener=transport)
    if live_payload.get("status") != "ok":
        raise RevisionCheckError("liveness_failed")

    ready_payload = _health_payload(ready, opener=transport)
    checks = ready_payload.get("checks")
    if (
        ready_payload.get("status") != "ok"
        or not isinstance(checks, dict)
        or checks.get("database") != "ok"
    ):
        raise RevisionCheckError("readiness_failed")

    cache_status = checks.get("cache", "not_checked")
    if require_shared_cache and cache_status != "ok":
        raise RevisionCheckError("shared_cache_unverified")
    if cache_status not in {"ok", "not_checked"}:
        raise RevisionCheckError("readiness_failed")

    return {
        "revision": revision,
        "liveness": "ok",
        "readiness": "ok",
        "database": "ok",
        "cache": cache_status,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="Exact /health/revision/ HTTPS endpoint")
    parser.add_argument("--expected-sha", required=True, help="Pinned full 40-character SHA")
    parser.add_argument("--require-shared-cache", action="store_true")
    args = parser.parse_args(argv)

    try:
        result = check_release_smoke(
            args.url, args.expected_sha, require_shared_cache=args.require_shared_cache
        )
    except RevisionCheckError as exc:
        print(f"FAIL live release smoke: {exc}", file=sys.stderr)
        return 1

    print(json.dumps({"status": "ok", **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
