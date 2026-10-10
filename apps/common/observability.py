from __future__ import annotations

import json
import logging
import os
import re
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from uuid import uuid4

_REQUEST_ID = ContextVar("request_id", default=None)
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_SERVICE_NAME = "cultural-currency-converter"

_REDACTED = "[REDACTED]"
_URI_CREDENTIALS_RE = re.compile(r"(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*://)(?P<userinfo>[^\s/@]+)@")
_BEARER_TOKEN_RE = re.compile(r"(?i)\bBearer\s+[^\s,;]+")
_QUERY_SECRET_RE = re.compile(
    r"(?i)(?P<prefix>[?&](?:api[_-]?key|access[_-]?token|refresh[_-]?token|"
    r"client[_-]?secret|token|wskey|secret|password)="
    r")(?P<value>[^&#\s]+)"
)
_NAMED_SECRET_RE = re.compile(
    r"(?i)(?P<prefix>\b(?:(?:[A-Za-z0-9]+_)*api[_-]?key|access[_-]?token|"
    r"refresh[_-]?token|client[_-]?secret|token|wskey|secret|password)"
    r"\s*[:=]\s*[\"']?)(?P<value>[^\s,;\"'&?#]+)"
)

_LOG_FIELDS = (
    "job",
    "records_processed",
    "records_created",
    "records_updated",
    "records_retired",
    "dry_run",
    "method",
    "path",
    "route",
    "status_code",
    "duration_ms",
    "error_code",
    "provider",
    "dependency",
    "operation",
    "outcome",
    "attempts",
    "latency_ms",
    "capability",
    "model",
    "input_tokens",
    "output_tokens",
    "cache_operation",
    "stale",
    "cache_status",
    "csp_directive",
    "csp_disposition",
    "csp_blocked_resource",
)


def redact_log_text(value: object) -> str:
    """Return diagnostic text with common credential forms removed."""

    text = str(value)
    text = _URI_CREDENTIALS_RE.sub(
        lambda match: f"{match.group('scheme')}{_REDACTED}@",
        text,
    )
    text = _BEARER_TOKEN_RE.sub(f"Bearer {_REDACTED}", text)
    text = _QUERY_SECRET_RE.sub(
        lambda match: f"{match.group('prefix')}{_REDACTED}",
        text,
    )
    return _NAMED_SECRET_RE.sub(
        lambda match: f"{match.group('prefix')}{_REDACTED}",
        text,
    )


def normalize_request_id(value: str | None) -> str:
    """Return a validated client request ID or generate a new opaque UUID."""

    if value is not None and _REQUEST_ID_PATTERN.fullmatch(value):
        return value
    return str(uuid4())


def bind_request_id(request_id: str) -> Token[str | None]:
    """Bind a request ID to the current execution context."""

    return _REQUEST_ID.set(request_id)


def reset_request_id(token: Token[str | None]) -> None:
    """Restore the previous request correlation context."""

    _REQUEST_ID.reset(token)


def get_request_id() -> str | None:
    """Return the request ID bound to the current execution context."""

    return _REQUEST_ID.get()


class JsonFormatter(logging.Formatter):
    """Emit a small stable JSON log envelope without serializing request data."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "environment": os.environ.get("APP_ENV", "local"),
            "service": _SERVICE_NAME,
            "request_id": getattr(record, "request_id", None) or get_request_id(),
            "event": redact_log_text(record.getMessage()),
        }

        for field_name in _LOG_FIELDS:
            value = getattr(record, field_name, None)
            if value is not None:
                payload[field_name] = redact_log_text(value) if isinstance(value, str) else value

        if record.exc_info:
            payload["exception"] = redact_log_text(self.formatException(record.exc_info))

        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
