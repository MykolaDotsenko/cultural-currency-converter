from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any

from django.core.cache import cache

from apps.exchange.domain import (
    FxSourcePolicy,
    HistoricalObservationUnavailable,
    ObservationGranularity,
    ProviderPolicyMode,
    RateQuote,
    RateSeries,
    RateSeriesGrouping,
    RateSeriesPoint,
    normalize_currency_code,
)
from apps.exchange.providers.base import FxProvider, FxProviderInvalidPayload, FxProviderUnavailable

logger = logging.getLogger("cultural_currency.exchange")
CACHE_VERSION = "v1"


class QuoteFreshness(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    TOO_OLD = "too_old"


def _allowed_observation_gap(
    granularity: ObservationGranularity,
    *,
    daily_gap: timedelta,
) -> timedelta:
    return {
        ObservationGranularity.DAILY: daily_gap,
        ObservationGranularity.MONTHLY: timedelta(days=31),
        ObservationGranularity.QUARTERLY: timedelta(days=92),
        ObservationGranularity.UNKNOWN: daily_gap,
    }[granularity]


def latest_cache_key(base: str, quote: str, policy: FxSourcePolicy) -> str:
    base_code = normalize_currency_code(base)
    quote_code = normalize_currency_code(quote)
    return (
        f"fx:{CACHE_VERSION}:latest:{policy.mode.value}:{policy.cache_identity}:"
        f"{base_code}:{quote_code}"
    )


def historical_cache_key(
    base: str,
    quote: str,
    effective_date: date,
    policy: FxSourcePolicy,
) -> str:
    base_code = normalize_currency_code(base)
    quote_code = normalize_currency_code(quote)
    return (
        f"fx:{CACHE_VERSION}:historical:{policy.mode.value}:{policy.cache_identity}:"
        f"{base_code}:{quote_code}:{effective_date.isoformat()}"
    )


def rate_series_cache_key(
    base: str,
    quote: str,
    start_date: date,
    end_date: date,
    grouping: RateSeriesGrouping,
    policy: FxSourcePolicy,
) -> str:
    base_code = normalize_currency_code(base)
    quote_code = normalize_currency_code(quote)
    return (
        f"fx-series:{CACHE_VERSION}:{policy.mode.value}:{policy.cache_identity}:"
        f"{base_code}:{quote_code}:{start_date.isoformat()}:{end_date.isoformat()}:"
        f"{grouping.value}"
    )


def historical_resolution_cache_key(
    base: str,
    quote: str,
    requested_date: date,
    policy: FxSourcePolicy,
) -> str:
    base_code = normalize_currency_code(base)
    quote_code = normalize_currency_code(quote)
    return (
        f"fx:{CACHE_VERSION}:historical-resolution:{policy.mode.value}:{policy.cache_identity}:"
        f"{base_code}:{quote_code}:{requested_date.isoformat()}"
    )


def serialize_quote(quote: RateQuote) -> dict[str, Any]:
    return {
        "base_currency": quote.base_currency,
        "quote_currency": quote.quote_currency,
        "rate": str(quote.rate),
        "requested_date": quote.requested_date.isoformat() if quote.requested_date else None,
        "effective_date": quote.effective_date.isoformat(),
        "fetched_at": quote.fetched_at.isoformat(),
        "provider_policy": {
            "mode": quote.provider_policy.mode.value,
            "provider_key": quote.provider_policy.provider_key,
            "include_attribution": quote.provider_policy.include_attribution,
        },
        "provider_keys": list(quote.provider_keys),
        "historical": quote.historical,
        "observation_granularity": quote.observation_granularity.value,
    }


def deserialize_quote(value: Any) -> RateQuote | None:
    if not isinstance(value, dict):
        return None
    try:
        raw_policy = value["provider_policy"]
        raw_provider_keys = value["provider_keys"]
        raw_historical = value["historical"]
        if not isinstance(raw_policy, dict):
            return None
        if not isinstance(raw_provider_keys, (list, tuple)) or not all(
            isinstance(key, str) for key in raw_provider_keys
        ):
            return None
        if not isinstance(raw_historical, bool):
            return None
        policy = FxSourcePolicy(
            mode=ProviderPolicyMode(raw_policy["mode"]),
            provider_key=raw_policy.get("provider_key"),
            include_attribution=bool(raw_policy.get("include_attribution", True)),
        )
        return RateQuote(
            base_currency=value["base_currency"],
            quote_currency=value["quote_currency"],
            rate=Decimal(value["rate"]),
            requested_date=(
                date.fromisoformat(value["requested_date"]) if value.get("requested_date") else None
            ),
            effective_date=date.fromisoformat(value["effective_date"]),
            fetched_at=datetime.fromisoformat(value["fetched_at"]),
            provider_policy=policy,
            provider_keys=tuple(raw_provider_keys),
            historical=raw_historical,
            observation_granularity=ObservationGranularity(value["observation_granularity"]),
        )
    except (KeyError, TypeError, ValueError, ArithmeticError):
        return None


def serialize_series(series: RateSeries) -> dict[str, Any]:
    return {
        "base_currency": series.base_currency,
        "quote_currency": series.quote_currency,
        "start_date": series.start_date.isoformat(),
        "end_date": series.end_date.isoformat(),
        "grouping": series.grouping.value,
        "fetched_at": series.fetched_at.isoformat(),
        "provider_policy": {
            "mode": series.provider_policy.mode.value,
            "provider_key": series.provider_policy.provider_key,
            "include_attribution": series.provider_policy.include_attribution,
        },
        "observation_granularity": series.observation_granularity.value,
        "points": [
            {
                "observation_date": point.observation_date.isoformat(),
                "rate": str(point.rate),
                "provider_keys": list(point.provider_keys),
            }
            for point in series.points
        ],
    }


def deserialize_series(value: Any) -> RateSeries | None:
    if not isinstance(value, dict):
        return None
    try:
        raw_policy = value["provider_policy"]
        raw_points = value["points"]
        if not isinstance(raw_policy, dict) or not isinstance(raw_points, list):
            return None
        policy = FxSourcePolicy(
            mode=ProviderPolicyMode(raw_policy["mode"]),
            provider_key=raw_policy.get("provider_key"),
            include_attribution=bool(raw_policy.get("include_attribution", True)),
        )
        points: list[RateSeriesPoint] = []
        for raw_point in raw_points:
            if not isinstance(raw_point, dict):
                return None
            raw_provider_keys = raw_point.get("provider_keys")
            if not isinstance(raw_provider_keys, (list, tuple)) or not all(
                isinstance(key, str) for key in raw_provider_keys
            ):
                return None
            points.append(
                RateSeriesPoint(
                    observation_date=date.fromisoformat(raw_point["observation_date"]),
                    rate=Decimal(raw_point["rate"]),
                    provider_keys=tuple(raw_provider_keys),
                )
            )
        return RateSeries(
            base_currency=value["base_currency"],
            quote_currency=value["quote_currency"],
            start_date=date.fromisoformat(value["start_date"]),
            end_date=date.fromisoformat(value["end_date"]),
            grouping=RateSeriesGrouping(value["grouping"]),
            points=tuple(points),
            fetched_at=datetime.fromisoformat(value["fetched_at"]),
            provider_policy=policy,
            observation_granularity=ObservationGranularity(
                value.get("observation_granularity", ObservationGranularity.DAILY.value)
            ),
        )
    except (KeyError, TypeError, ValueError, ArithmeticError):
        return None


def classify_quote_freshness(
    quote: RateQuote | RateSeries,
    *,
    now: datetime,
    fresh_for: timedelta,
    stale_for: timedelta,
) -> QuoteFreshness:
    age = now.astimezone(UTC) - quote.fetched_at.astimezone(UTC)
    if age <= fresh_for:
        return QuoteFreshness.FRESH
    if age <= stale_for:
        return QuoteFreshness.STALE
    return QuoteFreshness.TOO_OLD


class LatestQuoteGateway:
    def __init__(
        self,
        provider: FxProvider,
        *,
        fresh_for: timedelta = timedelta(hours=6),
        stale_for: timedelta = timedelta(days=7),
        max_observation_gap: timedelta = timedelta(days=7),
        physical_ttl_seconds: int = 8 * 24 * 60 * 60,
    ):
        if fresh_for <= timedelta(0) or stale_for <= fresh_for:
            raise ValueError("FX freshness windows must be positive and ordered.")
        if max_observation_gap < timedelta(0):
            raise ValueError("Latest FX observation gap cannot be negative.")
        self.provider = provider
        self.fresh_for = fresh_for
        self.stale_for = stale_for
        self.max_observation_gap = max_observation_gap
        self.physical_ttl_seconds = physical_ttl_seconds

    def get(
        self, base: str, quote: str, policy: FxSourcePolicy, *, now: datetime
    ) -> tuple[RateQuote, bool]:
        key = latest_cache_key(base, quote, policy)
        cached = self._cache_get(key)
        if cached is not None:
            try:
                self._assert_quote_identity(cached, base=base, quote=quote, policy=policy)
            except FxProviderInvalidPayload:
                logger.warning(
                    "Ignoring semantically mismatched latest FX cache entry",
                    extra={
                        "dependency": "cache",
                        "operation": "latest_quote",
                        "cache_operation": "get",
                        "outcome": "invalid_cache",
                        "cache_status": "invalid",
                    },
                )
                cached = None

        if (
            cached
            and classify_quote_freshness(
                cached, now=now, fresh_for=self.fresh_for, stale_for=self.stale_for
            )
            is QuoteFreshness.FRESH
        ):
            return cached, False

        try:
            fresh = self.provider.latest_quote(base, quote, policy)
            self._assert_quote_identity(fresh, base=base, quote=quote, policy=policy)
        except (FxProviderUnavailable, FxProviderInvalidPayload):
            if (
                cached
                and classify_quote_freshness(
                    cached, now=now, fresh_for=self.fresh_for, stale_for=self.stale_for
                )
                is QuoteFreshness.STALE
            ):
                logger.warning(
                    "fx_stale_fallback",
                    extra={
                        "dependency": "cache",
                        "operation": "latest_quote",
                        "outcome": "degraded",
                        "cache_status": "stale_fallback",
                        "stale": True,
                    },
                )
                return cached, True
            raise

        self._cache_set(key, fresh)
        return fresh, False

    def _assert_quote_identity(
        self,
        quote_value: RateQuote,
        *,
        base: str,
        quote: str,
        policy: FxSourcePolicy,
    ) -> None:
        if quote_value.base_currency != base.upper() or quote_value.quote_currency != quote.upper():
            raise FxProviderInvalidPayload("Provider returned a quote for a different pair.")
        if quote_value.provider_policy != policy:
            raise FxProviderInvalidPayload(
                "Provider returned a quote under a different source policy."
            )
        if quote_value.historical or quote_value.requested_date is not None:
            raise FxProviderInvalidPayload("Latest quote gateway received historical semantics.")

        observation_gap = quote_value.fetched_at.astimezone(UTC).date() - quote_value.effective_date
        allowed_gap = _allowed_observation_gap(
            quote_value.observation_granularity,
            daily_gap=self.max_observation_gap,
        )
        if observation_gap > allowed_gap:
            raise FxProviderInvalidPayload(
                "Latest quote observation falls outside the allowed "
                f"{quote_value.observation_granularity.value} observation window."
            )

    def _cache_get(self, key: str) -> RateQuote | None:
        try:
            return deserialize_quote(cache.get(key))
        except Exception:
            logger.warning(
                "FX cache read failed",
                extra={
                    "dependency": "cache",
                    "operation": "latest_quote",
                    "cache_operation": "get",
                    "outcome": "failure",
                },
                exc_info=True,
            )
            return None

    def _cache_set(self, key: str, quote: RateQuote) -> None:
        try:
            cache.set(key, serialize_quote(quote), timeout=self.physical_ttl_seconds)
        except Exception:
            logger.warning(
                "FX cache write failed",
                extra={
                    "dependency": "cache",
                    "operation": "latest_quote",
                    "cache_operation": "set",
                    "outcome": "failure",
                },
                exc_info=True,
            )


class HistoricalSeriesGateway:
    def __init__(
        self,
        provider: FxProvider,
        *,
        fresh_for: timedelta = timedelta(hours=24),
        stale_for: timedelta = timedelta(days=30),
        physical_ttl_seconds: int = 31 * 24 * 60 * 60,
    ):
        if fresh_for <= timedelta(0) or stale_for <= fresh_for:
            raise ValueError("FX series freshness windows must be positive and ordered.")
        self.provider = provider
        self.fresh_for = fresh_for
        self.stale_for = stale_for
        self.physical_ttl_seconds = physical_ttl_seconds

    def get(
        self,
        base: str,
        quote: str,
        start_date: date,
        end_date: date,
        grouping: RateSeriesGrouping,
        policy: FxSourcePolicy,
        *,
        now: datetime,
    ) -> tuple[RateSeries, bool]:
        key = rate_series_cache_key(
            base,
            quote,
            start_date,
            end_date,
            grouping,
            policy,
        )
        cached = self._cache_get(key)
        if cached is not None:
            try:
                self._assert_series_identity(
                    cached,
                    base=base,
                    quote=quote,
                    start_date=start_date,
                    end_date=end_date,
                    grouping=grouping,
                    policy=policy,
                )
            except FxProviderInvalidPayload:
                logger.warning(
                    "Ignoring semantically mismatched historical FX series cache entry",
                    extra={
                        "dependency": "cache",
                        "operation": "rate_series",
                        "cache_operation": "get",
                        "outcome": "invalid_cache",
                        "cache_status": "invalid",
                    },
                )
                cached = None

        if (
            cached is not None
            and classify_quote_freshness(
                cached,
                now=now,
                fresh_for=self.fresh_for,
                stale_for=self.stale_for,
            )
            is QuoteFreshness.FRESH
        ):
            return cached, False

        try:
            fresh = self.provider.rate_series(
                base,
                quote,
                start_date,
                end_date,
                grouping,
                policy,
            )
            self._assert_series_identity(
                fresh,
                base=base,
                quote=quote,
                start_date=start_date,
                end_date=end_date,
                grouping=grouping,
                policy=policy,
            )
        except (FxProviderUnavailable, FxProviderInvalidPayload):
            if (
                cached is not None
                and classify_quote_freshness(
                    cached,
                    now=now,
                    fresh_for=self.fresh_for,
                    stale_for=self.stale_for,
                )
                is QuoteFreshness.STALE
            ):
                logger.warning(
                    "fx_stale_fallback",
                    extra={
                        "dependency": "cache",
                        "operation": "rate_series",
                        "outcome": "degraded",
                        "cache_status": "stale_fallback",
                        "stale": True,
                    },
                )
                return cached, True
            raise

        self._cache_set(key, fresh)
        return fresh, False

    @staticmethod
    def _assert_series_identity(
        series: RateSeries,
        *,
        base: str,
        quote: str,
        start_date: date,
        end_date: date,
        grouping: RateSeriesGrouping,
        policy: FxSourcePolicy,
    ) -> None:
        if series.base_currency != base.upper() or series.quote_currency != quote.upper():
            raise FxProviderInvalidPayload("Provider returned a series for a different pair.")
        if series.start_date != start_date or series.end_date != end_date:
            raise FxProviderInvalidPayload("Provider returned a series for a different date range.")
        if series.grouping is not grouping:
            raise FxProviderInvalidPayload("Provider returned a series with different grouping.")
        if series.provider_policy != policy:
            raise FxProviderInvalidPayload(
                "Provider returned a series under a different source policy."
            )

    def _cache_get(self, key: str) -> RateSeries | None:
        try:
            return deserialize_series(cache.get(key))
        except Exception:
            logger.warning(
                "Historical FX series cache read failed",
                extra={
                    "dependency": "cache",
                    "operation": "rate_series",
                    "cache_operation": "get",
                    "outcome": "failure",
                },
                exc_info=True,
            )
            return None

    def _cache_set(self, key: str, series: RateSeries) -> None:
        try:
            cache.set(
                key,
                serialize_series(series),
                timeout=self.physical_ttl_seconds,
            )
        except Exception:
            logger.warning(
                "Historical FX series cache write failed",
                extra={
                    "dependency": "cache",
                    "operation": "rate_series",
                    "cache_operation": "set",
                    "outcome": "failure",
                },
                exc_info=True,
            )


class HistoricalQuoteGateway:
    def __init__(
        self,
        provider: FxProvider,
        *,
        max_previous_gap: timedelta = timedelta(days=7),
        physical_ttl_seconds: int = 365 * 24 * 60 * 60,
    ):
        if max_previous_gap < timedelta(0):
            raise ValueError("Historical previous-observation gap cannot be negative.")
        self.provider = provider
        self.max_previous_gap = max_previous_gap
        self.physical_ttl_seconds = physical_ttl_seconds

    def get(
        self,
        base: str,
        quote: str,
        requested_date: date,
        policy: FxSourcePolicy,
    ) -> RateQuote:
        resolution_key = historical_resolution_cache_key(base, quote, requested_date, policy)
        cached = self._cache_get(resolution_key)
        if cached is not None:
            try:
                self._assert_quote_identity(
                    cached,
                    base=base,
                    quote=quote,
                    requested_date=requested_date,
                    policy=policy,
                )
                self._assert_gap(cached)
            except (FxProviderInvalidPayload, HistoricalObservationUnavailable):
                logger.warning(
                    "Ignoring semantically invalid historical FX resolution cache entry",
                    extra={
                        "dependency": "cache",
                        "operation": "historical_quote",
                        "cache_operation": "get",
                        "outcome": "invalid_cache",
                        "cache_status": "invalid",
                    },
                )
                cached = None
            else:
                return cached

        historical = self.provider.historical_quote(base, quote, requested_date, policy)
        self._assert_quote_identity(
            historical,
            base=base,
            quote=quote,
            requested_date=requested_date,
            policy=policy,
        )
        self._assert_gap(historical)

        self._cache_set(resolution_key, historical)
        self._cache_set(
            historical_cache_key(base, quote, historical.effective_date, policy),
            historical,
        )
        return historical

    def invalidate(
        self,
        base: str,
        quote: str,
        requested_date: date,
        policy: FxSourcePolicy,
    ) -> None:
        resolution_key = historical_resolution_cache_key(base, quote, requested_date, policy)
        cached = self._cache_get(resolution_key)
        keys = [resolution_key]
        if cached is not None:
            keys.append(historical_cache_key(base, quote, cached.effective_date, policy))
        for key in keys:
            try:
                cache.delete(key)
            except Exception:
                logger.warning(
                    "Historical FX cache invalidation failed",
                    extra={
                        "dependency": "cache",
                        "operation": "historical_quote",
                        "cache_operation": "delete",
                        "outcome": "failure",
                    },
                    exc_info=True,
                )

    def _assert_gap(self, quote: RateQuote) -> None:
        if quote.requested_date is None:
            raise FxProviderInvalidPayload("Historical quote omitted its requested date.")
        gap = quote.requested_date - quote.effective_date
        allowed_gap = _allowed_observation_gap(
            quote.observation_granularity,
            daily_gap=self.max_previous_gap,
        )
        if gap > allowed_gap:
            raise HistoricalObservationUnavailable(
                "No historical observation is available within the allowed "
                f"{quote.observation_granularity.value} observation window."
            )

    @staticmethod
    def _assert_quote_identity(
        quote_value: RateQuote,
        *,
        base: str,
        quote: str,
        requested_date: date,
        policy: FxSourcePolicy,
    ) -> None:
        if quote_value.base_currency != base.upper() or quote_value.quote_currency != quote.upper():
            raise FxProviderInvalidPayload("Provider returned a quote for a different pair.")
        if quote_value.provider_policy != policy:
            raise FxProviderInvalidPayload(
                "Provider returned a quote under a different source policy."
            )
        if not quote_value.historical or quote_value.requested_date != requested_date:
            raise FxProviderInvalidPayload(
                "Historical quote does not preserve the requested-date semantics."
            )

    def _cache_get(self, key: str) -> RateQuote | None:
        try:
            return deserialize_quote(cache.get(key))
        except Exception:
            logger.warning(
                "Historical FX cache read failed",
                extra={
                    "dependency": "cache",
                    "operation": "historical_quote",
                    "cache_operation": "get",
                    "outcome": "failure",
                },
                exc_info=True,
            )
            return None

    def _cache_set(self, key: str, quote: RateQuote) -> None:
        try:
            cache.set(key, serialize_quote(quote), timeout=self.physical_ttl_seconds)
        except Exception:
            logger.warning(
                "Historical FX cache write failed",
                extra={
                    "dependency": "cache",
                    "operation": "historical_quote",
                    "cache_operation": "set",
                    "outcome": "failure",
                },
                exc_info=True,
            )
