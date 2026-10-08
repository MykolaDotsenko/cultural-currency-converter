#!/usr/bin/env python3
"""Read-only fail-closed check of the exact revision serving an HTTP deployment."""

from __future__ import annotations

import argparse
import json
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

_SHA = re.compile(r"^[0-9a-f]{40}$")
_LOCAL_HTTP_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_MAX_RESPONSE_BYTES = 4096


class RevisionCheckError(Exception):
    """Expected, non-sensitive failure reported as an operator-safe code."""


class RejectRedirects(HTTPRedirectHandler):
    """A different HTTP origin must not silently impersonate the deployment."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def validate_url(url: str) -> None:
    """Require the exact diagnostic endpoint and HTTPS outside loopback."""

    if not url or url.strip() != url or len(url) > 2048:
        raise RevisionCheckError("invalid_endpoint_url")

    try:
        parts = urlsplit(url)
        host = parts.hostname
        _port = parts.port
    except ValueError as exc:
        raise RevisionCheckError("invalid_endpoint_url") from exc

    if (
        parts.scheme not in {"https", "http"}
        or not host
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
        or parts.path != "/health/revision/"
        or (parts.scheme == "http" and host not in _LOCAL_HTTP_HOSTS)
    ):
        raise RevisionCheckError("invalid_endpoint_url")


def check_revision(url: str, expected_sha: str, *, opener=None) -> str:
    """Return the matched full SHA, otherwise refuse certification."""

    validate_url(url)
    if _SHA.fullmatch(expected_sha) is None:
        raise RevisionCheckError("invalid_expected_sha")

    transport = opener if opener is not None else build_opener(RejectRedirects())
    request = Request(url, headers={"Accept": "application/json"})

    try:
        with transport.open(request, timeout=5) as response:
            if response.status != 200:
                raise RevisionCheckError("endpoint_unavailable")
            content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip()
            if content_type.lower() != "application/json":
                raise RevisionCheckError("invalid_response")
            raw = response.read(_MAX_RESPONSE_BYTES + 1)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise RevisionCheckError("endpoint_unavailable") from exc

    if len(raw) > _MAX_RESPONSE_BYTES:
        raise RevisionCheckError("invalid_response")

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RevisionCheckError("invalid_response") from exc

    if not isinstance(payload, dict):
        raise RevisionCheckError("invalid_response")
    actual_sha = payload.get("revision")
    if (
        payload.get("status") != "known"
        or not isinstance(actual_sha, str)
        or _SHA.fullmatch(actual_sha) is None
    ):
        raise RevisionCheckError("revision_unknown")
    if actual_sha != expected_sha:
        raise RevisionCheckError("revision_mismatch")
    return actual_sha


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="Exact /health/revision/ HTTPS endpoint")
    parser.add_argument("--expected-sha", required=True, help="Exact 40-character release Git SHA")
    args = parser.parse_args(argv)

    try:
        revision = check_revision(args.url, args.expected_sha)
    except RevisionCheckError as exc:
        print(f"FAIL deployment revision: {exc}", file=sys.stderr)
        return 1

    print(f"PASS deployment revision: {revision}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
