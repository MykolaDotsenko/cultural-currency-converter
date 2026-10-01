from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from enum import StrEnum


class FxDomainError(ValueError):
    pass


class ConversionRepresentationError(FxDomainError):
    pass


class HistoricalConversionError(FxDomainError):
    pass


class HistoricalDateError(HistoricalConversionError):
    pass


class HistoricalObservationUnavailable(HistoricalConversionError):
    pass


class HistoricalCoverageReason(StrEnum):
    CURRENCY_NOT_YET_ACTIVE = "currency_not_yet_active"
    CURRENCY_RETIRED = "currency_retired"
    PROVIDER_COVERAGE_NOT_STARTED = "provider_coverage_not_started"
    PROVIDER_COVERAGE_ENDED = "provider_coverage_ended"


class HistoricalOutOfCoverage(HistoricalConversionError):
    def __init__(
        self,
        *,
        currency_code: str,
        requested_date: date,
        reason: HistoricalCoverageReason,
        boundary: date,
    ) -> None:
        self.currency_code = normalize_currency_code(currency_code)
        self.requested_date = requested_date
        self.reason = reason
        self.boundary = boundary
        super().__init__(
            f"{self.currency_code} is outside {reason.value} bounds for "
            f"{requested_date.isoformat()}."
        )


class ProviderPolicyMode(StrEnum):
    BLEND = "blend"
    PINNED = "pinned"


class ObservationGranularity(StrEnum):
    DAILY = "daily"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    UNKNOWN = "unknown"


class RateSeriesGrouping(StrEnum):
    DAILY = "daily"
    WEEK = "week"
    MONTH = "month"


class RateSeriesRangeError(FxDomainError):
    pass


@dataclass(frozen=True)
class FxSourcePolicy:
    mode: ProviderPolicyMode = ProviderPolicyMode.BLEND
    provider_key: str | None = None
    include_attribution: bool = True

    def __post_init__(self) -> None:
        provider = self.provider_key.lower().strip() if self.provider_key else None
        if self.mode is ProviderPolicyMode.PINNED and not provider:
            raise FxDomainError("Pinned FX policy requires a provider key.")
        if self.mode is ProviderPolicyMode.BLEND and provider:
            raise FxDomainError("Blend FX policy cannot carry a pinned provider key.")
        object.__setattr__(self, "provider_key", provider)

    @property
    def cache_identity(self) -> str:
        provider = self.provider_key or "all"
        attribution = "attr" if self.include_attribution else "noattr"
        return f"{provider}:{attribution}"


DEFAULT_SOURCE_POLICY = FxSourcePolicy()

# Provider attribution is external provenance, so keep it bounded consistently
# across signed snapshots and durable saved-scenario observations.
MAX_PROVIDER_KEYS = 128
MAX_PROVIDER_KEY_LENGTH = 80


def normalize_provider_keys(values: Iterable[object]) -> tuple[str, ...]:
    materialized = tuple(values)
    if len(materialized) > MAX_PROVIDER_KEYS:
        raise FxDomainError("FX provider attribution exceeds supported entry limits.")

    normalized: set[str] = set()
    for value in materialized:
        if not isinstance(value, str):
            raise FxDomainError("FX provider attribution must contain text identifiers.")
        key = value.lower().strip()
        if not key or len(key) > MAX_PROVIDER_KEY_LENGTH:
            raise FxDomainError("FX provider attribution contains an invalid identifier.")
        normalized.add(key)
    return tuple(sorted(normalized))


MAX_RATE_SIGNIFICANT_DIGITS = 64
MAX_RATE_ABS_ADJUSTED_EXPONENT = 100


def validate_rate_decimal(value: Decimal, *, label: str = "FX rate") -> Decimal:
    if not isinstance(value, Decimal):
        raise FxDomainError(f"{label} must be a Decimal.")
    if not value.is_finite() or value <= 0:
        raise FxDomainError(f"{label} must be a finite positive Decimal.")
    if (
        len(value.as_tuple().digits) > MAX_RATE_SIGNIFICANT_DIGITS
        or abs(value.adjusted()) > MAX_RATE_ABS_ADJUSTED_EXPONENT
    ):
        raise FxDomainError(f"{label} exceeds supported numeric representation limits.")
    return value


@dataclass(frozen=True)
class HistoricalCurrencyMetadata:
    code: str
    active_from: date | None = None
    active_to: date | None = None
    coverage_from: date | None = None
    coverage_to: date | None = None
    coverage_to_is_terminal: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", normalize_currency_code(self.code))
        if self.active_from and self.active_to and self.active_to < self.active_from:
            raise FxDomainError("Currency active range is invalid.")
        if self.coverage_from and self.coverage_to and self.coverage_to < self.coverage_from:
            raise FxDomainError("Currency provider coverage range is invalid.")


def validate_historical_currency_metadata(
    metadata: HistoricalCurrencyMetadata,
    requested_date: date,
) -> None:
    if metadata.active_from and requested_date < metadata.active_from:
        raise HistoricalOutOfCoverage(
            currency_code=metadata.code,
            requested_date=requested_date,
            reason=HistoricalCoverageReason.CURRENCY_NOT_YET_ACTIVE,
            boundary=metadata.active_from,
        )
    if metadata.active_to and requested_date > metadata.active_to:
        raise HistoricalOutOfCoverage(
            currency_code=metadata.code,
            requested_date=requested_date,
            reason=HistoricalCoverageReason.CURRENCY_RETIRED,
            boundary=metadata.active_to,
        )
    if metadata.coverage_from and requested_date < metadata.coverage_from:
        raise HistoricalOutOfCoverage(
            currency_code=metadata.code,
            requested_date=requested_date,
            reason=HistoricalCoverageReason.PROVIDER_COVERAGE_NOT_STARTED,
            boundary=metadata.coverage_from,
        )
    if (
        metadata.coverage_to
        and metadata.coverage_to_is_terminal
        and requested_date > metadata.coverage_to
    ):
        raise HistoricalOutOfCoverage(
            currency_code=metadata.code,
            requested_date=requested_date,
            reason=HistoricalCoverageReason.PROVIDER_COVERAGE_ENDED,
            boundary=metadata.coverage_to,
        )


def normalize_currency_code(value: str) -> str:
    if not isinstance(value, str):
        raise FxDomainError("Currency code must be text.")
    code = value.upper().strip()
    if len(code) != 3 or not code.isascii() or not code.isalpha():
        raise FxDomainError("Currency code must be three ASCII letters.")
    return code


@dataclass(frozen=True)
class RateQuote:
    base_currency: str
    quote_currency: str
    rate: Decimal
    requested_date: date | None
    effective_date: date
    fetched_at: datetime
    provider_policy: FxSourcePolicy
    provider_keys: tuple[str, ...]
    historical: bool
    observation_granularity: ObservationGranularity = ObservationGranularity.DAILY

    def __post_init__(self) -> None:
        base = normalize_currency_code(self.base_currency)
        quote = normalize_currency_code(self.quote_currency)
        validate_rate_decimal(self.rate)
        if self.fetched_at.tzinfo is None:
            raise FxDomainError("FX fetched_at must be timezone-aware.")
        providers = normalize_provider_keys(self.provider_keys)
        exact_identity_quote = (
            base == quote
            and self.rate == Decimal("1")
            and not providers
            and self.provider_policy == DEFAULT_SOURCE_POLICY
            and self.historical
            and self.requested_date == self.effective_date
        )
        fetched_date = self.fetched_at.astimezone(UTC).date()
        latest_allowed_effective_date = (
            fetched_date + timedelta(days=1) if exact_identity_quote else fetched_date
        )
        if self.effective_date > latest_allowed_effective_date:
            raise FxDomainError("FX effective date cannot be after fetch date.")
        if (
            self.provider_policy.mode is ProviderPolicyMode.PINNED
            and self.provider_policy.provider_key not in providers
        ):
            raise FxDomainError("Pinned FX quote must attribute the pinned provider.")
        if self.requested_date and self.effective_date > self.requested_date:
            raise FxDomainError("Historical effective date cannot be after the requested date.")
        if self.historical != (self.requested_date is not None):
            raise FxDomainError("Historical flag must match requested-date semantics.")
        object.__setattr__(self, "base_currency", base)
        object.__setattr__(self, "quote_currency", quote)
        object.__setattr__(self, "provider_keys", providers)

    @property
    def used_previous_observation(self) -> bool:
        return bool(
            self.historical
            and self.requested_date is not None
            and self.effective_date < self.requested_date
        )


@dataclass(frozen=True)
class RateSeriesPoint:
    observation_date: date
    rate: Decimal
    provider_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        validate_rate_decimal(self.rate, label="FX series rate")
        providers = normalize_provider_keys(self.provider_keys)
        object.__setattr__(self, "provider_keys", providers)


@dataclass(frozen=True)
class RateSeries:
    base_currency: str
    quote_currency: str
    start_date: date
    end_date: date
    grouping: RateSeriesGrouping
    points: tuple[RateSeriesPoint, ...]
    fetched_at: datetime
    provider_policy: FxSourcePolicy
    observation_granularity: ObservationGranularity = ObservationGranularity.DAILY

    def __post_init__(self) -> None:
        base = normalize_currency_code(self.base_currency)
        quote = normalize_currency_code(self.quote_currency)
        if self.end_date < self.start_date:
            raise RateSeriesRangeError("FX series end date cannot precede start date.")
        if not isinstance(self.grouping, RateSeriesGrouping):
            raise FxDomainError("FX series grouping must be a RateSeriesGrouping.")
        if not isinstance(self.observation_granularity, ObservationGranularity):
            raise FxDomainError(
                "FX series observation granularity must be an ObservationGranularity."
            )
        if self.fetched_at.tzinfo is None:
            raise FxDomainError("FX series fetched_at must be timezone-aware.")

        previous_date: date | None = None
        for point in self.points:
            if not self.start_date <= point.observation_date <= self.end_date:
                raise FxDomainError("FX series observation falls outside requested range.")
            if previous_date is not None and point.observation_date <= previous_date:
                raise FxDomainError("FX series observations must be strictly date-ordered.")
            if (
                self.provider_policy.mode is ProviderPolicyMode.PINNED
                and self.provider_policy.provider_key not in point.provider_keys
            ):
                raise FxDomainError(
                    "Pinned FX series observation must attribute the pinned provider."
                )
            previous_date = point.observation_date

        object.__setattr__(self, "base_currency", base)
        object.__setattr__(self, "quote_currency", quote)

    @property
    def minimum_point(self) -> RateSeriesPoint | None:
        return min(self.points, key=lambda point: point.rate, default=None)

    @property
    def maximum_point(self) -> RateSeriesPoint | None:
        return max(self.points, key=lambda point: point.rate, default=None)


@dataclass(frozen=True)
class RateSeriesResult:
    series: RateSeries
    stale: bool


@dataclass(frozen=True)
class ConversionResult:
    input_amount: Decimal
    output_amount: Decimal
    quote: RateQuote
    stale: bool


@dataclass(frozen=True)
class ThenNowComparison:
    historical: ConversionResult
    latest: ConversionResult
    rate_difference_percent: Decimal

    def __post_init__(self) -> None:
        if self.historical.input_amount != self.latest.input_amount:
            raise FxDomainError("Then & now comparisons require the same input amount.")
        if (
            self.historical.quote.base_currency != self.latest.quote.base_currency
            or self.historical.quote.quote_currency != self.latest.quote.quote_currency
        ):
            raise FxDomainError(
                "Then & now comparisons require the same directional currency pair."
            )
        if not self.historical.quote.historical:
            raise FxDomainError("Then & now historical side must use a historical quote.")
        if self.latest.quote.historical:
            raise FxDomainError("Then & now latest side must use a latest quote.")
        if not self.rate_difference_percent.is_finite():
            raise FxDomainError("Then & now rate difference must be finite.")


def convert_amount(amount: Decimal, quote: RateQuote, *, minor_units: int) -> Decimal:
    if not isinstance(amount, Decimal):
        raise FxDomainError("Amount must be a Decimal.")
    if not amount.is_finite():
        raise FxDomainError("Amount must be a finite Decimal.")
    if isinstance(minor_units, bool) or not isinstance(minor_units, int):
        raise FxDomainError("Minor units must be an integer.")
    if not 0 <= minor_units <= 6:
        raise FxDomainError("Minor units must be between 0 and 6.")
    quantum = Decimal(1).scaleb(-minor_units)
    try:
        return (amount * quote.rate).quantize(quantum, rounding=ROUND_HALF_EVEN)
    except InvalidOperation as exc:
        raise ConversionRepresentationError(
            "Conversion cannot be represented at the requested precision."
        ) from exc


def same_currency_quote(
    currency: str,
    *,
    fetched_at: datetime,
    requested_date: date | None = None,
) -> RateQuote:
    code = normalize_currency_code(currency)
    return RateQuote(
        base_currency=code,
        quote_currency=code,
        rate=Decimal("1"),
        requested_date=requested_date,
        effective_date=requested_date or fetched_at.date(),
        fetched_at=fetched_at,
        provider_policy=DEFAULT_SOURCE_POLICY,
        provider_keys=(),
        historical=requested_date is not None,
    )
