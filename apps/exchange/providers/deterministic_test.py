from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from apps.exchange.domain import (
    FxSourcePolicy,
    ObservationGranularity,
    ProviderPolicyMode,
    RateQuote,
    RateSeries,
    RateSeriesGrouping,
    RateSeriesPoint,
    normalize_currency_code,
)
from apps.exchange.providers.base import FxProviderUnsupportedPair

# Deterministic browser-quality fixture values expressed as units per EUR.
# This provider is enabled only through FX_TEST_FIXTURE_ENABLED in APP_ENV=test.
_REFERENCE_PER_EUR = {
    "EUR": Decimal("1"),
    "JPY": Decimal("174.5"),
    "NOK": Decimal("11.8"),
    "USD": Decimal("1.08"),
    "FIM": Decimal("5.94573"),
}
_PROVIDER_KEY = "browser-quality-fixture"


def _provider_keys(policy: FxSourcePolicy) -> tuple[str, ...]:
    if policy.mode is ProviderPolicyMode.PINNED:
        return (policy.provider_key or _PROVIDER_KEY,)
    if policy.include_attribution:
        return (_PROVIDER_KEY,)
    return ()


def _rate(base: str, quote: str) -> Decimal:
    base_code = normalize_currency_code(base)
    quote_code = normalize_currency_code(quote)
    try:
        base_per_eur = _REFERENCE_PER_EUR[base_code]
        quote_per_eur = _REFERENCE_PER_EUR[quote_code]
    except KeyError as exc:
        raise FxProviderUnsupportedPair(
            f"Deterministic test FX fixture does not support {base_code}/{quote_code}."
        ) from exc
    return quote_per_eur / base_per_eur


class DeterministicTestFxProvider:
    """Offline FX provider for browser/release-quality tests only."""

    def latest_quote(
        self,
        base: str,
        quote: str,
        policy: FxSourcePolicy,
    ) -> RateQuote:
        fetched_at = datetime.now(UTC)
        return RateQuote(
            base_currency=base,
            quote_currency=quote,
            rate=_rate(base, quote),
            requested_date=None,
            effective_date=fetched_at.date(),
            fetched_at=fetched_at,
            provider_policy=policy,
            provider_keys=_provider_keys(policy),
            historical=False,
            observation_granularity=ObservationGranularity.DAILY,
        )

    def historical_quote(
        self,
        base: str,
        quote: str,
        requested_date: date,
        policy: FxSourcePolicy,
    ) -> RateQuote:
        return RateQuote(
            base_currency=base,
            quote_currency=quote,
            rate=_rate(base, quote),
            requested_date=requested_date,
            effective_date=requested_date,
            fetched_at=datetime.now(UTC),
            provider_policy=policy,
            provider_keys=_provider_keys(policy),
            historical=True,
            observation_granularity=ObservationGranularity.DAILY,
        )

    def rate_series(
        self,
        base: str,
        quote: str,
        start_date: date,
        end_date: date,
        grouping: RateSeriesGrouping,
        policy: FxSourcePolicy,
    ) -> RateSeries:
        cadence = {
            RateSeriesGrouping.DAILY: timedelta(days=1),
            RateSeriesGrouping.WEEK: timedelta(days=7),
            RateSeriesGrouping.MONTH: timedelta(days=30),
        }[grouping]
        baseline = _rate(base, quote)
        points: list[RateSeriesPoint] = []
        observation_date = start_date
        index = 0
        while observation_date <= end_date:
            # Small deterministic movement exercises chart variation without
            # pretending this fixture is real market data.
            multiplier = Decimal("1") + Decimal(index % 9) / Decimal("1000")
            points.append(
                RateSeriesPoint(
                    observation_date=observation_date,
                    rate=baseline * multiplier,
                    provider_keys=_provider_keys(policy),
                )
            )
            observation_date += cadence
            index += 1

        if not points or points[-1].observation_date != end_date:
            points.append(
                RateSeriesPoint(
                    observation_date=end_date,
                    rate=baseline,
                    provider_keys=_provider_keys(policy),
                )
            )

        return RateSeries(
            base_currency=base,
            quote_currency=quote,
            start_date=start_date,
            end_date=end_date,
            grouping=grouping,
            points=tuple(points),
            fetched_at=datetime.now(UTC),
            provider_policy=policy,
            observation_granularity=ObservationGranularity.DAILY,
        )
