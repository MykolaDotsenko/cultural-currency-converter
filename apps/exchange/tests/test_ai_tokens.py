from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from django.core import signing

from apps.exchange import trusted_snapshot as tokens
from apps.exchange.domain import (
    DEFAULT_SOURCE_POLICY,
    ConversionResult,
    ObservationGranularity,
    RateQuote,
)
from apps.exchange.trusted_snapshot import (
    TrustedSnapshotTokenError,
    build_trusted_conversion_snapshot_token,
    load_trusted_conversion_snapshot_token,
)


def _result(
    *,
    historical: bool = False,
    requested_date: date | None = None,
    effective_date: date = date(2026, 9, 18),
    stale: bool = False,
    granularity: ObservationGranularity = ObservationGranularity.DAILY,
) -> ConversionResult:
    quote = RateQuote(
        base_currency="EUR",
        quote_currency="JPY",
        rate=Decimal("174.50"),
        requested_date=requested_date if historical else None,
        effective_date=effective_date,
        fetched_at=datetime(2026, 9, 21, 8, tzinfo=UTC),
        provider_policy=DEFAULT_SOURCE_POLICY,
        provider_keys=("ecb",),
        historical=historical,
        observation_granularity=granularity,
    )
    return ConversionResult(
        input_amount=Decimal("100.00"),
        output_amount=Decimal("17450"),
        quote=quote,
        stale=stale,
    )


def test_ai_legacy_token_aliases_use_the_trusted_snapshot_contract():
    token = build_conversion_explanation_token(_result())

    snapshot = load_conversion_explanation_token(token)

    assert snapshot.base_currency == "EUR"
    assert snapshot.quote_currency == "JPY"
    assert snapshot.rate == Decimal("174.50")


def test_signed_conversion_snapshot_round_trips_current_result():
    token = build_trusted_conversion_snapshot_token(_result())

    snapshot = load_trusted_conversion_snapshot_token(token)

    assert snapshot.input_amount == Decimal("100.00")
    assert snapshot.output_amount == Decimal("17450")
    assert snapshot.base_currency == "EUR"
    assert snapshot.quote_currency == "JPY"
    assert snapshot.rate == Decimal("174.50")
    assert snapshot.requested_date is None
    assert snapshot.provider_keys == ("ecb",)
    assert snapshot.stale is False


def test_signed_conversion_snapshot_preserves_historical_semantics():
    token = build_trusted_conversion_snapshot_token(
        _result(
            historical=True,
            requested_date=date(1998, 6, 14),
            effective_date=date(1998, 6, 12),
            stale=True,
            granularity=ObservationGranularity.MONTHLY,
        )
    )

    snapshot = load_trusted_conversion_snapshot_token(token)

    assert snapshot.historical is True
    assert snapshot.requested_date == date(1998, 6, 14)
    assert snapshot.effective_date == date(1998, 6, 12)
    assert snapshot.observation_granularity is ObservationGranularity.MONTHLY
    assert snapshot.stale is True


def test_tampered_or_expired_token_is_rejected():
    token = build_trusted_conversion_snapshot_token(_result())

    with pytest.raises(TrustedSnapshotTokenError, match="invalid"):
        load_trusted_conversion_snapshot_token(token + "tamper")

    with pytest.raises(TrustedSnapshotTokenError, match="expired"):
        load_trusted_conversion_snapshot_token(token, max_age=-1)


@pytest.mark.parametrize(
    "payload",
    [
        {"v": 2},
        {
            "v": 1,
            "input_amount": "100",
            "output_amount": "17450",
            "base_currency": "EUR",
            "quote_currency": "JPY",
            "rate": "174.5",
            "requested_date": None,
            "effective_date": "not-a-date",
            "historical": False,
            "observation_granularity": "daily",
            "provider_keys": [],
            "stale": False,
        },
    ],
)
def test_malformed_signed_payload_is_rejected(payload):
    token = signing.dumps(payload, salt=tokens._TOKEN_SALT)

    with pytest.raises(TrustedSnapshotTokenError):
        load_trusted_conversion_snapshot_token(token)


def test_historical_flag_cannot_disagree_with_requested_date():
    payload = {
        "v": 1,
        "input_amount": "100",
        "output_amount": "17450",
        "base_currency": "EUR",
        "quote_currency": "JPY",
        "rate": "174.5",
        "requested_date": "1998-06-14",
        "effective_date": "1998-06-12",
        "historical": False,
        "observation_granularity": "daily",
        "provider_keys": ["ecb"],
        "stale": False,
    }
    token = signing.dumps(payload, salt=tokens._TOKEN_SALT)

    with pytest.raises(TrustedSnapshotTokenError, match="historical semantics"):
        load_trusted_conversion_snapshot_token(token)


def test_provider_attribution_is_bounded_and_validated():
    payload = {
        "v": 1,
        "input_amount": "100",
        "output_amount": "17450",
        "base_currency": "EUR",
        "quote_currency": "JPY",
        "rate": "174.5",
        "requested_date": None,
        "effective_date": "2026-09-18",
        "historical": False,
        "observation_granularity": "daily",
        "provider_keys": ["../secret"],
        "stale": False,
    }
    token = signing.dumps(payload, salt=tokens._TOKEN_SALT)

    with pytest.raises(TrustedSnapshotTokenError, match="provider attribution"):
        load_trusted_conversion_snapshot_token(token)
