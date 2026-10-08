"""Strict JSON trust boundary for external, untrusted provider responses.

Unlike Python's permissive default decoder, repeated object members and
non-standard non-finite number constants are invalid. This is a *transport*
contract; individual integrations still validate identity, provenance, amount,
units and freshness after decoding.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any


def _unique_members(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate external JSON member.")
        result[key] = value
    return result


def _reject_nonfinite_constant(value: str) -> object:
    raise ValueError("Non-finite external JSON number.")


def strict_provider_json_loads(raw: bytes, *, decimal_floats: bool = False) -> Any:
    """Decode external JSON without ambiguous keys or non-standard numbers.

    Decimal parsing is opt-in so evidence-bearing external prices never pass
    through binary floating point. Invalid JSON raises ValueError,
    UnicodeDecodeError or RecursionError for callers to map to their stable
    source-unavailable error without exposing provider payloads.
    """
    options: dict[str, Any] = {
        "object_pairs_hook": _unique_members,
        "parse_constant": _reject_nonfinite_constant,
    }
    if decimal_floats:
        options["parse_float"] = Decimal
    return json.loads(raw, **options)
