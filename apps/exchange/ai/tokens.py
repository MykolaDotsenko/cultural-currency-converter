"""Compatibility aliases for signed conversion snapshots used by runtime AI.

The canonical implementation lives in :mod:`apps.exchange.trusted_snapshot`
because the snapshot is also consumed by non-AI financial utilities.
"""

from apps.exchange.trusted_snapshot import (
    TOKEN_MAX_AGE_SECONDS,
    TrustedConversionSnapshot,
    TrustedSnapshotTokenError,
    build_trusted_conversion_snapshot_token,
    load_trusted_conversion_snapshot_token,
)

ExplanationTokenError = TrustedSnapshotTokenError
build_conversion_explanation_token = build_trusted_conversion_snapshot_token
load_conversion_explanation_token = load_trusted_conversion_snapshot_token

__all__ = [
    "TOKEN_MAX_AGE_SECONDS",
    "ExplanationTokenError",
    "TrustedConversionSnapshot",
    "TrustedSnapshotTokenError",
    "build_conversion_explanation_token",
    "build_trusted_conversion_snapshot_token",
    "load_conversion_explanation_token",
    "load_trusted_conversion_snapshot_token",
]
