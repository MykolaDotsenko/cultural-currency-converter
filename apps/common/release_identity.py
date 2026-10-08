"""Public, non-secret Git revision identity for release verification.

An absent, malformed or conflicting revision must never be presented as known.
The hosting platform remains the authoritative source of deployed identity.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping

_FULL_GIT_SHA = re.compile(r"^[0-9a-fA-F]{40}$")
_REVISION_VARIABLES = ("RENDER_GIT_COMMIT", "APP_RELEASE_SHA")


def get_deployed_revision(environ: Mapping[str, str] | None = None) -> str | None:
    """Return one validated full commit SHA or None when identity is not provable."""

    values = os.environ if environ is None else environ
    declared = [values.get(name, "").strip() for name in _REVISION_VARIABLES]
    present = [value for value in declared if value]

    if not present or any(_FULL_GIT_SHA.fullmatch(value) is None for value in present):
        return None

    normalized = {value.lower() for value in present}
    return normalized.pop() if len(normalized) == 1 else None
