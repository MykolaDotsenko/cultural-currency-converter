from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from django.core import signing

from apps.exchange.domain import (
    DEFAULT_SOURCE_POLICY,
    ConversionResult,
    ObservationGranularity,
    RateQuote,
    same_currency_quote,
)
from apps.exchange.share_snapshot import (
    _TOKEN_SALT,
    ConversionShareTokenError,
    build_conversion_share_token,
    load_conversion_share_token,
)


def _current_result(*, stale: bool = False) -> ConversionResult:
    return ConversionResult(
        input_amount=Decimal("100.00"),
        output_amount=Decimal("17450"),
        quote=RateQuote(
            base_currency="EUR",
            quote_currency="JPY",
            rate=Decimal("174.50"),
            requested_date=None,
            effective_date=date(2026, 9, 18),
            fetched_at=datetime(2026, 9, 20, 8, tzinfo=UTC),
            provider_policy=DEFAULT_SOURCE_POLICY,
            provider_keys=("ecb",),
            historical=False,
        ),
        stale=stale,
    )


def _historical_result() -> ConversionResult:
    return ConversionResult(
        input_amount=Decimal("100"),
        output_amount=Decimal("21.35"),
        quote=RateQuote(
            base_currency="FIM",
            quote_currency="USD",
            rate=Decimal("0.2135"),
            requested_date=date(1998, 6, 15),
            effective_date=date(1998, 6, 12),
            fetched_at=datetime(2026, 9, 20, 8, tzinfo=UTC),
            provider_policy=DEFAULT_SOURCE_POLICY,
            provider_keys=("ecb",),
            historical=True,
            observation_granularity=ObservationGranularity.MONTHLY,
        ),
        stale=False,
    )


def test_share_token_round_trips_current_result_without_losing_attribution() -> None:
    token = build_conversion_share_token(_current_result(stale=True))

    snapshot = load_conversion_share_token(token)

    assert snapshot.input_amount == Decimal("100.00")
    assert snapshot.output_amount == Decimal("17450")
    assert snapshot.base_currency == "EUR"
    assert snapshot.quote_currency == "JPY"
    assert snapshot.rate == Decimal("174.50")
    assert snapshot.effective_date == date(2026, 9, 18)
    assert snapshot.fetched_at == datetime(2026, 9, 20, 8, tzinfo=UTC)
    assert snapshot.provider_keys == ("ecb",)
    assert snapshot.stale is True
    assert snapshot.exact is False


def test_share_token_preserves_historical_requested_and_observation_semantics() -> None:
    snapshot = load_conversion_share_token(build_conversion_share_token(_historical_result()))

    assert snapshot.historical is True
    assert snapshot.requested_date == date(1998, 6, 15)
    assert snapshot.effective_date == date(1998, 6, 12)
    assert snapshot.observation_granularity is ObservationGranularity.MONTHLY
    assert snapshot.provider_keys == ("ecb",)


def test_exact_same_currency_share_has_no_external_provider() -> None:
    quote = same_currency_quote(
        "EUR",
        fetched_at=datetime(2026, 10, 5, 6, tzinfo=UTC),
    )
    result = ConversionResult(
        input_amount=Decimal("12"),
        output_amount=Decimal("12.00"),
        quote=quote,
        stale=False,
    )

    snapshot = load_conversion_share_token(build_conversion_share_token(result))

    assert snapshot.exact is True
    assert snapshot.rate == Decimal("1")
    assert snapshot.provider_keys == ()


def test_tampered_share_token_is_rejected() -> None:
    token = build_conversion_share_token(_current_result())

    with pytest.raises(ConversionShareTokenError, match="invalid"):
        load_conversion_share_token(token + "tamper")


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
            "effective_date": "2026-09-18",
            "fetched_at": "2026-09-20T08:00:00+00:00",
            "historical": False,
            "observation_granularity": "daily",
            "provider_keys": [],
            "stale": False,
        },
        {
            "v": 1,
            "input_amount": "12",
            "output_amount": "12",
            "base_currency": "EUR",
            "quote_currency": "EUR",
            "rate": "2",
            "requested_date": None,
            "effective_date": "2026-10-05",
            "fetched_at": "2026-10-05T06:00:00+00:00",
            "historical": False,
            "observation_granularity": "daily",
            "provider_keys": [],
            "stale": False,
        },
    ],
)
def test_malformed_or_semantically_incomplete_signed_share_payload_is_rejected(payload) -> None:
    token = signing.dumps(payload, salt=_TOKEN_SALT, compress=True)

    with pytest.raises(ConversionShareTokenError):
        load_conversion_share_token(token)
