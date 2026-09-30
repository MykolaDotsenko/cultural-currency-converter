from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from apps.exchange.domain import (
    DEFAULT_SOURCE_POLICY,
    ConversionRepresentationError,
    FxDomainError,
    FxSourcePolicy,
    ProviderPolicyMode,
    RateQuote,
    convert_amount,
    same_currency_quote,
)


def quote(rate="174.505"):
    return RateQuote(
        base_currency="EUR",
        quote_currency="JPY",
        rate=Decimal(rate),
        requested_date=None,
        effective_date=date(2026, 9, 18),
        fetched_at=datetime(2026, 9, 20, 8, tzinfo=UTC),
        provider_policy=DEFAULT_SOURCE_POLICY,
        provider_keys=("ecb",),
        historical=False,
    )


def test_decimal_conversion_rounds_once_at_display_boundary():
    assert convert_amount(Decimal("100.125"), quote(), minor_units=0) == Decimal("17472")


def test_unrepresentable_conversion_uses_specific_domain_error():
    with pytest.raises(ConversionRepresentationError, match="cannot be represented"):
        convert_amount(Decimal("100"), quote("1E+50"), minor_units=0)


def test_invalid_rate_cannot_enter_domain():
    with pytest.raises(FxDomainError):
        quote("0")


def test_pinned_policy_requires_provider():
    with pytest.raises(FxDomainError):
        FxSourcePolicy(mode=ProviderPolicyMode.PINNED)


def test_historical_quote_cannot_claim_future_effective_observation():
    with pytest.raises(FxDomainError):
        RateQuote(
            base_currency="EUR",
            quote_currency="JPY",
            rate=Decimal("174.5"),
            requested_date=date(2026, 9, 18),
            effective_date=date(2026, 9, 19),
            fetched_at=datetime(2026, 9, 20, tzinfo=UTC),
            provider_policy=DEFAULT_SOURCE_POLICY,
            provider_keys=("ecb",),
            historical=True,
        )


def test_quote_cannot_claim_observation_after_fetch_date():
    with pytest.raises(FxDomainError, match="after fetch date"):
        RateQuote(
            base_currency="EUR",
            quote_currency="JPY",
            rate=Decimal("174.5"),
            requested_date=None,
            effective_date=date(2026, 9, 21),
            fetched_at=datetime(2026, 9, 20, 23, 59, tzinfo=UTC),
            provider_policy=DEFAULT_SOURCE_POLICY,
            provider_keys=("ecb",),
            historical=False,
        )


def test_exact_same_currency_quote_allows_one_day_local_calendar_rollover():
    quote_value = same_currency_quote(
        "EUR",
        fetched_at=datetime(2026, 9, 20, 21, 30, tzinfo=UTC),
        requested_date=date(2026, 9, 21),
    )

    assert quote_value.rate == Decimal("1")
    assert quote_value.effective_date == date(2026, 9, 21)
    assert quote_value.provider_keys == ()


def test_exact_same_currency_quote_cannot_jump_more_than_one_calendar_day():
    with pytest.raises(FxDomainError, match="after fetch date"):
        same_currency_quote(
            "EUR",
            fetched_at=datetime(2026, 9, 20, 21, 30, tzinfo=UTC),
            requested_date=date(2026, 9, 22),
        )


def test_provider_attributed_same_currency_quote_does_not_get_identity_rollover_exception():
    with pytest.raises(FxDomainError, match="after fetch date"):
        RateQuote(
            base_currency="EUR",
            quote_currency="EUR",
            rate=Decimal("1"),
            requested_date=date(2026, 9, 21),
            effective_date=date(2026, 9, 21),
            fetched_at=datetime(2026, 9, 20, 21, 30, tzinfo=UTC),
            provider_policy=DEFAULT_SOURCE_POLICY,
            provider_keys=("ecb",),
            historical=True,
        )


@pytest.mark.parametrize("raw_rate", [1.25, 1, "1.25"])
def test_rate_quote_rejects_non_decimal_rate_types(raw_rate):
    with pytest.raises(FxDomainError, match="must be a Decimal"):
        RateQuote(
            base_currency="EUR",
            quote_currency="JPY",
            rate=raw_rate,
            requested_date=None,
            effective_date=date(2026, 9, 18),
            fetched_at=datetime(2026, 9, 20, tzinfo=UTC),
            provider_policy=DEFAULT_SOURCE_POLICY,
            provider_keys=("ecb",),
            historical=False,
        )


@pytest.mark.parametrize("raw_amount", [1.25, 1, "1.25"])
def test_conversion_rejects_non_decimal_amount_types(raw_amount):
    with pytest.raises(FxDomainError, match="Amount must be a Decimal"):
        convert_amount(raw_amount, quote(), minor_units=2)
