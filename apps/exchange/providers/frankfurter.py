from __future__ import annotations

import json
import logging
import time
from datetime import UTC, date, datetime
from decimal import Decimal
from http.client import HTTPException
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from apps.exchange.domain import (
    FxDomainError,
    FxSourcePolicy,
    ObservationGranularity,
    ProviderPolicyMode,
    RateQuote,
    RateSeries,
    RateSeriesGrouping,
    RateSeriesPoint,
    normalize_currency_code,
    validate_rate_decimal,
)
from apps.exchange.providers.base import (
    FxProviderAuthenticationError,
    FxProviderError,
    FxProviderInvalidPayload,
    FxProviderRateLimited,
    FxProviderTimeout,
    FxProviderUnavailable,
    FxProviderUnsupportedPair,
)

DEFAULT_BASE_URL = "https://api.frankfurter.dev/v2"
MAX_RESPONSE_BYTES = 64 * 1024
MAX_SERIES_RESPONSE_BYTES = 2 * 1024 * 1024
RETRYABLE_HTTP_STATUSES = frozenset({408, 500, 502, 503, 504})
logger = logging.getLogger("cultural_currency.exchange")
_NON_DAILY_PROVIDER_GRANULARITY = {
    "hmrc": ObservationGranularity.MONTHLY,
    "ust": ObservationGranularity.QUARTERLY,
}


def _observation_granularity(policy: FxSourcePolicy) -> ObservationGranularity:
    if policy.mode is ProviderPolicyMode.BLEND:
        return ObservationGranularity.DAILY
    return _NON_DAILY_PROVIDER_GRANULARITY.get(
        policy.provider_key or "",
        ObservationGranularity.DAILY,
    )


def _currency_code(value: Any) -> str:
    code = str(value or "").upper().strip()
    if len(code) != 3 or not code.isascii() or not code.isalpha():
        raise FxProviderInvalidPayload("Frankfurter returned an invalid currency code.")
    return code


def _provider_keys(payload: dict[str, Any], policy: FxSourcePolicy) -> tuple[str, ...]:
    raw_providers = payload.get("providers")
    if raw_providers is None:
        raw_providers = []
        if policy.mode is ProviderPolicyMode.PINNED and policy.include_attribution:
            raise FxProviderInvalidPayload(
                "Frankfurter omitted attribution for a pinned-provider quote."
            )
    if not isinstance(raw_providers, list):
        raise FxProviderInvalidPayload("Frankfurter provider attribution must be an array.")

    normalized: list[str] = []
    for raw_provider in raw_providers:
        excluded = False
        if isinstance(raw_provider, str):
            raw_key = raw_provider
        elif isinstance(raw_provider, dict):
            raw_key_value = raw_provider.get("key")
            if not isinstance(raw_key_value, str):
                raise FxProviderInvalidPayload(
                    "Frankfurter provider attribution object must contain a string key."
                )
            raw_key = raw_key_value
            raw_excluded = raw_provider.get("excluded", False)
            if not isinstance(raw_excluded, bool):
                raise FxProviderInvalidPayload(
                    "Frankfurter provider attribution excluded flag must be boolean."
                )
            excluded = raw_excluded
        else:
            raise FxProviderInvalidPayload(
                "Frankfurter provider attribution must contain identifiers or provider objects."
            )

        key = raw_key.lower().strip()
        if key and not excluded:
            normalized.append(key)

    provider_keys = tuple(normalized)
    if policy.mode is ProviderPolicyMode.PINNED:
        requested_provider = (policy.provider_key or "").lower().strip()
        if policy.include_attribution and not provider_keys:
            raise FxProviderInvalidPayload(
                "Frankfurter omitted attribution for a pinned-provider quote."
            )
        if provider_keys and requested_provider not in provider_keys:
            raise FxProviderInvalidPayload(
                "Frankfurter returned attribution for a different pinned provider."
            )
        if not provider_keys:
            provider_keys = (requested_provider,)
    return provider_keys


def _rate_decimal(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise FxProviderInvalidPayload("Frankfurter returned an invalid rate.")
    try:
        rate = value if isinstance(value, Decimal) else Decimal(str(value))
    except (ArithmeticError, ValueError) as exc:
        raise FxProviderInvalidPayload("Frankfurter returned a non-decimal rate.") from exc
    try:
        return validate_rate_decimal(rate)
    except FxDomainError as exc:
        raise FxProviderInvalidPayload(str(exc)) from exc


def parse_rate_payload(
    payload: Any,
    *,
    expected_base: str,
    expected_quote: str,
    requested_date: date | None,
    policy: FxSourcePolicy,
    fetched_at: datetime,
) -> RateQuote:
    if not isinstance(payload, dict):
        raise FxProviderInvalidPayload("Frankfurter rate response must be an object.")

    base = _currency_code(payload.get("base"))
    quote = _currency_code(payload.get("quote"))
    if base != expected_base.upper() or quote != expected_quote.upper():
        raise FxProviderInvalidPayload("Frankfurter returned a different currency pair.")

    rate = _rate_decimal(payload.get("rate"))

    try:
        effective_date = date.fromisoformat(str(payload.get("date")))
    except ValueError as exc:
        raise FxProviderInvalidPayload("Frankfurter returned an invalid observation date.") from exc

    provider_keys = _provider_keys(payload, policy)

    try:
        return RateQuote(
            base_currency=base,
            quote_currency=quote,
            rate=rate,
            requested_date=requested_date,
            effective_date=effective_date,
            fetched_at=fetched_at,
            provider_policy=policy,
            provider_keys=provider_keys,
            historical=requested_date is not None,
            observation_granularity=_observation_granularity(policy),
        )
    except FxDomainError as exc:
        raise FxProviderInvalidPayload(str(exc)) from exc


def parse_series_payload(
    payload: Any,
    *,
    expected_base: str,
    expected_quote: str,
    start_date: date,
    end_date: date,
    grouping: RateSeriesGrouping,
    policy: FxSourcePolicy,
    fetched_at: datetime,
) -> RateSeries:
    if not isinstance(payload, list):
        raise FxProviderInvalidPayload("Frankfurter series response must be an array.")

    points: list[RateSeriesPoint] = []
    seen_dates: set[date] = set()
    for row in payload:
        if not isinstance(row, dict):
            raise FxProviderInvalidPayload("Frankfurter series row must be an object.")
        base = _currency_code(row.get("base"))
        quote = _currency_code(row.get("quote"))
        if base != expected_base.upper() or quote != expected_quote.upper():
            raise FxProviderInvalidPayload("Frankfurter series returned a different currency pair.")
        try:
            observation_date = date.fromisoformat(str(row.get("date")))
        except ValueError as exc:
            raise FxProviderInvalidPayload(
                "Frankfurter series returned an invalid observation date."
            ) from exc
        if not start_date <= observation_date <= end_date:
            raise FxProviderInvalidPayload(
                "Frankfurter series returned an observation outside the requested range."
            )
        if observation_date in seen_dates:
            raise FxProviderInvalidPayload(
                "Frankfurter series returned duplicate observation dates."
            )
        seen_dates.add(observation_date)
        points.append(
            RateSeriesPoint(
                observation_date=observation_date,
                rate=_rate_decimal(row.get("rate")),
                provider_keys=_provider_keys(row, policy),
            )
        )

    points.sort(key=lambda point: point.observation_date)
    try:
        return RateSeries(
            base_currency=expected_base,
            quote_currency=expected_quote,
            start_date=start_date,
            end_date=end_date,
            grouping=grouping,
            points=tuple(points),
            fetched_at=fetched_at,
            provider_policy=policy,
            observation_granularity=_observation_granularity(policy),
        )
    except FxDomainError as exc:
        raise FxProviderInvalidPayload(str(exc)) from exc


def _log_invalid_payload(*, operation: str, exc: FxProviderInvalidPayload) -> None:
    logger.warning(
        "fx_provider_payload_invalid",
        extra={
            "provider": "frankfurter",
            "operation": operation,
            "outcome": "invalid_payload",
            "error_code": exc.__class__.__name__,
        },
    )


class FrankfurterProvider:
    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: float = 3.0,
        max_attempts: int = 2,
    ):
        if timeout_seconds <= 0:
            raise ValueError("Frankfurter timeout must be positive.")
        if max_attempts not in {1, 2}:
            raise ValueError("Frankfurter max_attempts must be 1 or 2.")
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts

    def latest_quote(self, base: str, quote: str, policy: FxSourcePolicy) -> RateQuote:
        return self._fetch_quote(base, quote, requested_date=None, policy=policy)

    def historical_quote(
        self,
        base: str,
        quote: str,
        requested_date: date,
        policy: FxSourcePolicy,
    ) -> RateQuote:
        return self._fetch_quote(base, quote, requested_date=requested_date, policy=policy)

    def rate_series(
        self,
        base: str,
        quote: str,
        start_date: date,
        end_date: date,
        grouping: RateSeriesGrouping,
        policy: FxSourcePolicy,
    ) -> RateSeries:
        try:
            base_code = normalize_currency_code(base)
            quote_code = normalize_currency_code(quote)
        except FxDomainError as exc:
            raise FxProviderUnsupportedPair("Invalid currency code for Frankfurter query.") from exc

        params: dict[str, str] = {
            "from": start_date.isoformat(),
            "to": end_date.isoformat(),
            "base": base_code,
            "quotes": quote_code,
        }
        if grouping is not RateSeriesGrouping.DAILY:
            params["group"] = grouping.value
        if policy.mode is ProviderPolicyMode.PINNED:
            params["providers"] = policy.provider_key or ""
        if policy.include_attribution:
            params["expand"] = "providers"

        request = Request(
            f"{self.base_url}/rates?{urlencode(params)}",
            headers={"Accept": "application/json", "User-Agent": "cultural-currency-converter/0.1"},
        )
        payload = self._request_json(
            request,
            max_response_bytes=MAX_SERIES_RESPONSE_BYTES,
            operation="rate_series",
        )
        try:
            return parse_series_payload(
                payload,
                expected_base=base_code,
                expected_quote=quote_code,
                start_date=start_date,
                end_date=end_date,
                grouping=grouping,
                policy=policy,
                fetched_at=datetime.now(UTC),
            )
        except FxProviderInvalidPayload as exc:
            _log_invalid_payload(operation="rate_series", exc=exc)
            raise

    def _fetch_quote(
        self,
        base: str,
        quote: str,
        *,
        requested_date: date | None,
        policy: FxSourcePolicy,
    ) -> RateQuote:
        try:
            base_code = normalize_currency_code(base)
            quote_code = normalize_currency_code(quote)
        except FxDomainError as exc:
            raise FxProviderUnsupportedPair("Invalid currency code for Frankfurter query.") from exc
        params: dict[str, str] = {}
        if requested_date is not None:
            params["date"] = requested_date.isoformat()
        if policy.mode is ProviderPolicyMode.PINNED:
            params["providers"] = policy.provider_key or ""
        if policy.include_attribution:
            params["expand"] = "providers"

        query = f"?{urlencode(params)}" if params else ""
        request = Request(
            f"{self.base_url}/rate/{base_code}/{quote_code}{query}",
            headers={"Accept": "application/json", "User-Agent": "cultural-currency-converter/0.1"},
        )
        payload = self._request_json(
            request,
            max_response_bytes=MAX_RESPONSE_BYTES,
            operation="historical_quote" if requested_date is not None else "latest_quote",
        )
        fetched_at = datetime.now(UTC)

        operation = "historical_quote" if requested_date is not None else "latest_quote"
        try:
            return parse_rate_payload(
                payload,
                expected_base=base_code,
                expected_quote=quote_code,
                requested_date=requested_date,
                policy=policy,
                fetched_at=fetched_at,
            )
        except FxProviderInvalidPayload as exc:
            _log_invalid_payload(operation=operation, exc=exc)
            raise

    def _request_json(
        self,
        request: Request,
        *,
        max_response_bytes: int,
        operation: str,
    ) -> Any:
        started = time.perf_counter()
        attempts_used = 0
        try:
            raw: bytes | None = None
            last_transient_error: Exception | None = None
            for attempt in range(self.max_attempts):
                attempts_used = attempt + 1
                try:
                    with urlopen(request, timeout=self.timeout_seconds) as response:
                        raw = response.read(max_response_bytes + 1)
                    if len(raw) > max_response_bytes:
                        raise FxProviderInvalidPayload(
                            "Frankfurter response exceeded the size limit."
                        )
                    break
                except HTTPError as exc:
                    if exc.code == 429:
                        raise FxProviderRateLimited("Frankfurter rate limit reached.") from exc
                    if exc.code in {401, 403}:
                        raise FxProviderAuthenticationError(
                            "Frankfurter authentication or authorization failed."
                        ) from exc
                    if exc.code in {400, 404, 422}:
                        raise FxProviderUnsupportedPair(
                            "Frankfurter does not support this rate query."
                        ) from exc
                    if exc.code not in RETRYABLE_HTTP_STATUSES:
                        raise FxProviderUnavailable(
                            f"Frankfurter returned HTTP {exc.code}."
                        ) from exc
                    last_transient_error = exc
                    if attempt + 1 == self.max_attempts:
                        raise FxProviderUnavailable(
                            f"Frankfurter returned HTTP {exc.code}."
                        ) from exc
                except TimeoutError as exc:
                    last_transient_error = exc
                    if attempt + 1 == self.max_attempts:
                        raise FxProviderTimeout("Frankfurter request timed out.") from exc
                except URLError as exc:
                    if isinstance(exc.reason, TimeoutError):
                        last_transient_error = exc
                        if attempt + 1 == self.max_attempts:
                            raise FxProviderTimeout("Frankfurter request timed out.") from exc
                        continue
                    last_transient_error = exc
                    if attempt + 1 == self.max_attempts:
                        raise FxProviderUnavailable("Frankfurter request failed.") from exc
                except (HTTPException, OSError) as exc:
                    last_transient_error = exc
                    if attempt + 1 == self.max_attempts:
                        raise FxProviderUnavailable("Frankfurter request failed.") from exc

            if raw is None:
                raise FxProviderUnavailable("Frankfurter request failed.") from last_transient_error

            try:
                payload = json.loads(raw, parse_float=Decimal, parse_int=Decimal)
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise FxProviderInvalidPayload("Frankfurter returned malformed JSON.") from exc
        except FxProviderError as exc:
            logger.warning(
                "fx_provider_transport",
                extra={
                    "provider": "frankfurter",
                    "operation": operation,
                    "outcome": "failure",
                    "attempts": attempts_used or 1,
                    "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                    "error_code": exc.__class__.__name__,
                },
            )
            raise

        logger.info(
            "fx_provider_transport",
            extra={
                "provider": "frankfurter",
                "operation": operation,
                "outcome": "success",
                "attempts": attempts_used,
                "latency_ms": round((time.perf_counter() - started) * 1000, 3),
            },
        )
        return payload
