"""Backward-compatible aliases for the generic signed conversion snapshot boundary.

Runtime AI was the first consumer of these tokens, so older internal imports use
explanation-specific names. The implementation now lives at the exchange layer
because non-AI features such as Payment Estimate consume the same trusted
conversion snapshot.
"""

from apps.exchange.snapshot_tokens import (
    TOKEN_MAX_AGE_SECONDS,
    ConversionSnapshotTokenError,
    TrustedConversionSnapshot,
    build_conversion_snapshot_token,
    load_conversion_snapshot_token,
)

ExplanationTokenError = ConversionSnapshotTokenError
build_conversion_explanation_token = build_conversion_snapshot_token
load_conversion_explanation_token = load_conversion_snapshot_token

__all__ = [
    "TOKEN_MAX_AGE_SECONDS",
    "ExplanationTokenError",
    "TrustedConversionSnapshot",
    "build_conversion_explanation_token",
    "load_conversion_explanation_token",
]
