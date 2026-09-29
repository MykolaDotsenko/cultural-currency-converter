import logging
from datetime import UTC, date, datetime
from decimal import Decimal
from http.client import HTTPException
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import pytest

from apps.exchange.domain import (
    DEFAULT_SOURCE_POLICY,
    FxSourcePolicy,
    ObservationGranularity,
    ProviderPolicyMode,
    RateSeriesGrouping,
)
from apps.exchange.providers.base import (
    FxProviderAuthenticationError,
    FxProviderInvalidPayload,
    FxProviderRateLimited,
    FxProviderTimeout,
    FxProviderUnavailable,
    FxProviderUnsupportedPair,
)
from apps.exchange.providers.frankfurter import (
    MAX_RESPONSE_BYTES,
    MAX_SERIES_RESPONSE_BYTES,
    FrankfurterProvider,
    parse_rate_payload,
    parse_series_payload,
)


def test_frankfurter_v2_rate_normalizes_decimal_and_attribution():
    result = parse_rate_payload(
        {
            "date": "2026-09-18",
            "base": "EUR",
            "quote": "JPY",
            "rate": Decimal("174.50"),
            "providers": ["ECB", "BOJ"],
        },
        expected_base="EUR",
        expected_quote="JPY",
        requested_date=None,
        policy=DEFAULT_SOURCE_POLICY,
        fetched_at=datetime(2026, 9, 20, tzinfo=UTC),
    )

    assert result.rate == Decimal("174.50")
    assert result.provider_keys == ("boj", "ecb")
    assert result.effective_date == date(2026, 9, 18)
    assert result.observation_granularity is ObservationGranularity.DAILY


@pytest.mark.parametrize(
    "payload",
    [
        {"date": "2026-09-18", "base": "USD", "quote": "JPY", "rate": Decimal("174.5")},
        {"date": "2026-09-18", "base": "EUR", "quote": "JPY", "rate": Decimal("0")},
        {"date": "2026-09-18", "base": "EUR", "quote": "JPY", "rate": Decimal("NaN")},
        {"date": "2026-09-18", "base": "EUR", "quote": "JPY", "rate": Decimal("Infinity")},
        {"date": "not-a-date", "base": "EUR", "quote": "JPY", "rate": Decimal("174.5")},
        {"date": "2026-09-18", "base": "EUR", "quote": "JPY", "rate": True},
    ],
)
def test_malformed_or_wrong_pair_payload_is_rejected(payload):
    with pytest.raises(FxProviderInvalidPayload):
        parse_rate_payload(
            payload,
            expected_base="EUR",
            expected_quote="JPY",
            requested_date=None,
            policy=DEFAULT_SOURCE_POLICY,
            fetched_at=datetime(2026, 9, 20, tzinfo=UTC),
        )


def test_future_dated_latest_observation_is_rejected():
    with pytest.raises(FxProviderInvalidPayload, match="after fetch date"):
        parse_rate_payload(
            {
                "date": "2026-09-21",
                "base": "EUR",
                "quote": "JPY",
                "rate": Decimal("174.5"),
            },
            expected_base="EUR",
            expected_quote="JPY",
            requested_date=None,
            policy=DEFAULT_SOURCE_POLICY,
            fetched_at=datetime(2026, 9, 20, 23, 59, tzinfo=UTC),
        )


def test_pinned_quote_retains_identity_when_attribution_expansion_is_disabled():
    policy = FxSourcePolicy(
        mode=ProviderPolicyMode.PINNED,
        provider_key="ecb",
        include_attribution=False,
    )
    result = parse_rate_payload(
        {"date": "2026-09-18", "base": "EUR", "quote": "JPY", "rate": Decimal("174.5")},
        expected_base="EUR",
        expected_quote="JPY",
        requested_date=None,
        policy=policy,
        fetched_at=datetime(2026, 9, 20, tzinfo=UTC),
    )
    assert result.provider_keys == ("ecb",)


class FakeResponse:
    def __init__(self, payload: bytes):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, size=-1):
        return self.payload if size < 0 else self.payload[:size]


def test_transient_network_failure_retries_at_most_once(caplog):
    payload = b'{"date":"2026-09-18","base":"EUR","quote":"JPY","rate":174.5,"providers":["ECB"]}'
    attempts = [URLError("temporary"), FakeResponse(payload)]

    def fake_urlopen(*args, **kwargs):
        result = attempts.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    provider = FrankfurterProvider(max_attempts=2)
    with (
        caplog.at_level(logging.INFO, logger="cultural_currency.exchange"),
        patch("apps.exchange.providers.frankfurter.urlopen", side_effect=fake_urlopen) as mocked,
    ):
        result = provider.latest_quote("EUR", "JPY", DEFAULT_SOURCE_POLICY)

    assert mocked.call_count == 2
    assert result.rate == Decimal("174.5")
    record = next(record for record in caplog.records if record.msg == "fx_provider_transport")
    assert record.provider == "frankfurter"
    assert record.operation == "latest_quote"
    assert record.outcome == "success"
    assert record.attempts == 2
    assert record.latency_ms >= 0
    assert not hasattr(record, "url")


def test_rate_limit_is_not_retried():
    error = HTTPError(
        url="https://api.frankfurter.dev/v2/rate/EUR/JPY",
        code=429,
        msg="Too Many Requests",
        hdrs=None,
        fp=None,
    )
    provider = FrankfurterProvider(max_attempts=2)

    with patch("apps.exchange.providers.frankfurter.urlopen", side_effect=error) as mocked:
        with pytest.raises(FxProviderRateLimited):
            provider.latest_quote("EUR", "JPY", DEFAULT_SOURCE_POLICY)

    assert mocked.call_count == 1


def test_invalid_currency_code_is_rejected_before_network_call():
    provider = FrankfurterProvider()

    with patch("apps.exchange.providers.frankfurter.urlopen") as mocked:
        with pytest.raises(FxProviderUnsupportedPair):
            provider.latest_quote("EUR/USD", "JPY", DEFAULT_SOURCE_POLICY)

    mocked.assert_not_called()


def test_blended_pegged_rate_may_omit_provider_attribution():
    result = parse_rate_payload(
        {"date": "2026-09-18", "base": "USD", "quote": "HKD", "rate": Decimal("7.8")},
        expected_base="USD",
        expected_quote="HKD",
        requested_date=None,
        policy=DEFAULT_SOURCE_POLICY,
        fetched_at=datetime(2026, 9, 20, tzinfo=UTC),
    )

    assert result.provider_keys == ()


def test_pinned_quote_missing_requested_attribution_is_rejected():
    policy = FxSourcePolicy(mode=ProviderPolicyMode.PINNED, provider_key="ecb")
    with pytest.raises(FxProviderInvalidPayload, match="pinned-provider"):
        parse_rate_payload(
            {"date": "2026-09-18", "base": "EUR", "quote": "JPY", "rate": Decimal("174.5")},
            expected_base="EUR",
            expected_quote="JPY",
            requested_date=None,
            policy=policy,
            fetched_at=datetime(2026, 9, 20, tzinfo=UTC),
        )


@pytest.mark.parametrize(
    ("status", "error_type"),
    [(401, FxProviderAuthenticationError), (403, FxProviderAuthenticationError)],
)
def test_authentication_failures_are_not_retried(status, error_type):
    error = HTTPError(
        url="https://api.frankfurter.dev/v2/rate/EUR/JPY",
        code=status,
        msg="auth failure",
        hdrs=None,
        fp=None,
    )
    provider = FrankfurterProvider(max_attempts=2)

    with patch("apps.exchange.providers.frankfurter.urlopen", side_effect=error) as mocked:
        with pytest.raises(error_type):
            provider.latest_quote("EUR", "JPY", DEFAULT_SOURCE_POLICY)

    assert mocked.call_count == 1


def test_non_retryable_unexpected_4xx_is_not_retried():
    error = HTTPError(
        url="https://api.frankfurter.dev/v2/rate/EUR/JPY",
        code=418,
        msg="client error",
        hdrs=None,
        fp=None,
    )
    provider = FrankfurterProvider(max_attempts=2)

    with patch("apps.exchange.providers.frankfurter.urlopen", side_effect=error) as mocked:
        with pytest.raises(FxProviderUnavailable):
            provider.latest_quote("EUR", "JPY", DEFAULT_SOURCE_POLICY)

    assert mocked.call_count == 1


def test_timeout_is_normalized_after_bounded_retry(caplog):
    provider = FrankfurterProvider(max_attempts=2)

    with (
        caplog.at_level(logging.WARNING, logger="cultural_currency.exchange"),
        patch(
            "apps.exchange.providers.frankfurter.urlopen",
            side_effect=TimeoutError("slow"),
        ) as mocked,
    ):
        with pytest.raises(FxProviderTimeout):
            provider.latest_quote("EUR", "JPY", DEFAULT_SOURCE_POLICY)

    assert mocked.call_count == 2
    record = next(record for record in caplog.records if record.msg == "fx_provider_transport")
    assert record.provider == "frankfurter"
    assert record.operation == "latest_quote"
    assert record.outcome == "failure"
    assert record.attempts == 2
    assert record.error_code == "FxProviderTimeout"
    assert record.latency_ms >= 0


def test_semantically_invalid_payload_is_distinct_from_transport_success(caplog):
    payload = b'{"date":"2026-09-18","base":"USD","quote":"JPY","rate":174.5,"providers":["ECB"]}'
    provider = FrankfurterProvider(max_attempts=1)

    with (
        caplog.at_level(logging.INFO, logger="cultural_currency.exchange"),
        patch(
            "apps.exchange.providers.frankfurter.urlopen",
            return_value=FakeResponse(payload),
        ),
    ):
        with pytest.raises(FxProviderInvalidPayload):
            provider.latest_quote("EUR", "JPY", DEFAULT_SOURCE_POLICY)

    transport = next(record for record in caplog.records if record.msg == "fx_provider_transport")
    semantic = next(
        record for record in caplog.records if record.msg == "fx_provider_payload_invalid"
    )
    assert transport.outcome == "success"
    assert transport.attempts == 1
    assert semantic.provider == "frankfurter"
    assert semantic.operation == "latest_quote"
    assert semantic.outcome == "invalid_payload"
    assert semantic.error_code == "FxProviderInvalidPayload"


def test_oversized_single_rate_response_is_rejected_before_json_parsing():
    provider = FrankfurterProvider(max_attempts=1)
    response = FakeResponse(b"x" * (MAX_RESPONSE_BYTES + 1))

    with patch("apps.exchange.providers.frankfurter.urlopen", return_value=response):
        with pytest.raises(FxProviderInvalidPayload, match="size limit"):
            provider.latest_quote("EUR", "JPY", DEFAULT_SOURCE_POLICY)


@pytest.mark.parametrize(
    ("provider_key", "expected"),
    [
        ("hmrc", ObservationGranularity.MONTHLY),
        ("ust", ObservationGranularity.QUARTERLY),
        ("ecb", ObservationGranularity.DAILY),
    ],
)
def test_pinned_provider_frequency_is_normalized(provider_key, expected):
    policy = FxSourcePolicy(
        mode=ProviderPolicyMode.PINNED,
        provider_key=provider_key,
        include_attribution=False,
    )
    result = parse_rate_payload(
        {"date": "2026-09-18", "base": "EUR", "quote": "JPY", "rate": Decimal("174.5")},
        expected_base="EUR",
        expected_quote="JPY",
        requested_date=date(2026, 9, 20),
        policy=policy,
        fetched_at=datetime(2026, 9, 20, tzinfo=UTC),
    )

    assert result.observation_granularity is expected


def test_series_payload_sorts_observations_and_preserves_missing_dates():
    result = parse_series_payload(
        [
            {
                "date": "2026-01-05",
                "base": "EUR",
                "quote": "JPY",
                "rate": Decimal("181.2"),
                "providers": ["ECB"],
            },
            {
                "date": "2026-01-02",
                "base": "EUR",
                "quote": "JPY",
                "rate": Decimal("179.8"),
                "providers": ["ECB"],
            },
        ],
        expected_base="EUR",
        expected_quote="JPY",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 7),
        grouping=RateSeriesGrouping.DAILY,
        policy=DEFAULT_SOURCE_POLICY,
        fetched_at=datetime(2026, 1, 8, tzinfo=UTC),
    )

    assert [point.observation_date for point in result.points] == [
        date(2026, 1, 2),
        date(2026, 1, 5),
    ]
    assert [point.rate for point in result.points] == [
        Decimal("179.8"),
        Decimal("181.2"),
    ]


def test_series_payload_rejects_duplicate_observation_date():
    payload = [
        {
            "date": "2026-01-02",
            "base": "EUR",
            "quote": "JPY",
            "rate": Decimal("179.8"),
            "providers": ["ECB"],
        },
        {
            "date": "2026-01-02",
            "base": "EUR",
            "quote": "JPY",
            "rate": Decimal("180.0"),
            "providers": ["ECB"],
        },
    ]

    with pytest.raises(FxProviderInvalidPayload, match="duplicate"):
        parse_series_payload(
            payload,
            expected_base="EUR",
            expected_quote="JPY",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 7),
            grouping=RateSeriesGrouping.DAILY,
            policy=DEFAULT_SOURCE_POLICY,
            fetched_at=datetime(2026, 1, 8, tzinfo=UTC),
        )


@pytest.mark.parametrize(
    "payload",
    [
        [{"date": "2026-01-02", "base": "USD", "quote": "JPY", "rate": 180}],
        [{"date": "2025-12-31", "base": "EUR", "quote": "JPY", "rate": 180}],
        [{"date": "2026-01-02", "base": "EUR", "quote": "JPY", "rate": 0}],
        [{"date": "bad-date", "base": "EUR", "quote": "JPY", "rate": 180}],
    ],
)
def test_series_payload_rejects_wrong_identity_range_or_value(payload):
    with pytest.raises(FxProviderInvalidPayload):
        parse_series_payload(
            payload,
            expected_base="EUR",
            expected_quote="JPY",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 7),
            grouping=RateSeriesGrouping.DAILY,
            policy=FxSourcePolicy(include_attribution=False),
            fetched_at=datetime(2026, 1, 8, tzinfo=UTC),
        )


def test_rate_series_builds_bounded_monthly_query():
    payload = b'[{"date":"2025-01-31","base":"EUR","quote":"JPY","rate":161.2,"providers":["ECB"]}]'
    provider = FrankfurterProvider(base_url="https://example.test/v2", max_attempts=1)

    with patch(
        "apps.exchange.providers.frankfurter.urlopen", return_value=FakeResponse(payload)
    ) as mocked:
        result = provider.rate_series(
            "EUR",
            "JPY",
            date(2025, 1, 1),
            date(2025, 12, 31),
            RateSeriesGrouping.MONTH,
            DEFAULT_SOURCE_POLICY,
        )

    request = mocked.call_args.args[0]
    assert request.full_url.startswith("https://example.test/v2/rates?")
    assert "from=2025-01-01" in request.full_url
    assert "to=2025-12-31" in request.full_url
    assert "base=EUR" in request.full_url
    assert "quotes=JPY" in request.full_url
    assert "group=month" in request.full_url
    assert "expand=providers" in request.full_url
    assert result.grouping is RateSeriesGrouping.MONTH


def test_daily_rate_series_omits_group_query_parameter():
    payload = b'[{"date":"2026-01-02","base":"EUR","quote":"JPY","rate":179.8,"providers":["ECB"]}]'
    provider = FrankfurterProvider(base_url="https://example.test/v2", max_attempts=1)

    with patch(
        "apps.exchange.providers.frankfurter.urlopen", return_value=FakeResponse(payload)
    ) as mocked:
        provider.rate_series(
            "EUR",
            "JPY",
            date(2026, 1, 1),
            date(2026, 1, 7),
            RateSeriesGrouping.DAILY,
            DEFAULT_SOURCE_POLICY,
        )

    request = mocked.call_args.args[0]
    assert "group=" not in request.full_url


def test_oversized_series_response_is_rejected_before_json_parsing():
    provider = FrankfurterProvider(max_attempts=1)
    response = FakeResponse(b"x" * (MAX_SERIES_RESPONSE_BYTES + 1))

    with patch("apps.exchange.providers.frankfurter.urlopen", return_value=response):
        with pytest.raises(FxProviderInvalidPayload, match="size limit"):
            provider.rate_series(
                "EUR",
                "JPY",
                date(2026, 1, 1),
                date(2026, 1, 7),
                RateSeriesGrouping.DAILY,
                DEFAULT_SOURCE_POLICY,
            )


def test_series_keeps_requested_grouping_separate_from_provider_cadence():
    policy = FxSourcePolicy(
        mode=ProviderPolicyMode.PINNED,
        provider_key="hmrc",
        include_attribution=False,
    )
    result = parse_series_payload(
        [
            {
                "date": "2026-01-01",
                "base": "EUR",
                "quote": "GBP",
                "rate": Decimal("0.84"),
            }
        ],
        expected_base="EUR",
        expected_quote="GBP",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        grouping=RateSeriesGrouping.MONTH,
        policy=policy,
        fetched_at=datetime(2027, 1, 1, tzinfo=UTC),
    )

    assert result.grouping is RateSeriesGrouping.MONTH
    assert result.observation_granularity is ObservationGranularity.MONTHLY
    assert result.points[0].provider_keys == ("hmrc",)


def test_frankfurter_provider_requires_bounded_constructor_settings():
    with pytest.raises(ValueError, match="timeout must be positive"):
        FrankfurterProvider(timeout_seconds=0)

    with pytest.raises(ValueError, match="max_attempts must be 1 or 2"):
        FrankfurterProvider(max_attempts=3)


@pytest.mark.parametrize(
    "providers",
    [
        [],
        ["boe"],
    ],
)
def test_pinned_quote_rejects_missing_or_mismatched_expanded_attribution(providers):
    policy = FxSourcePolicy(
        mode=ProviderPolicyMode.PINNED,
        provider_key="ecb",
        include_attribution=True,
    )

    with pytest.raises(FxProviderInvalidPayload, match="attribution"):
        parse_rate_payload(
            {
                "date": "2026-09-18",
                "base": "EUR",
                "quote": "JPY",
                "rate": Decimal("174.5"),
                "providers": providers,
            },
            expected_base="EUR",
            expected_quote="JPY",
            requested_date=None,
            policy=policy,
            fetched_at=datetime(2026, 9, 20, tzinfo=UTC),
        )


def test_provider_attribution_rejects_non_string_identifiers():
    with pytest.raises(FxProviderInvalidPayload, match="string identifiers"):
        parse_rate_payload(
            {
                "date": "2026-09-18",
                "base": "EUR",
                "quote": "JPY",
                "rate": Decimal("174.5"),
                "providers": ["ECB", 123],
            },
            expected_base="EUR",
            expected_quote="JPY",
            requested_date=None,
            policy=DEFAULT_SOURCE_POLICY,
            fetched_at=datetime(2026, 9, 20, tzinfo=UTC),
        )


@pytest.mark.parametrize("status", [400, 404, 422])
def test_unsupported_query_http_statuses_are_not_retried(status):
    error = HTTPError(
        url="https://api.frankfurter.dev/v2/rate/EUR/JPY",
        code=status,
        msg="unsupported",
        hdrs=None,
        fp=None,
    )
    provider = FrankfurterProvider(max_attempts=2)

    with patch("apps.exchange.providers.frankfurter.urlopen", side_effect=error) as mocked:
        with pytest.raises(FxProviderUnsupportedPair):
            provider.latest_quote("EUR", "JPY", DEFAULT_SOURCE_POLICY)

    assert mocked.call_count == 1


@pytest.mark.parametrize("status", [408, 500, 502, 503, 504])
def test_retryable_http_failure_retries_once_then_raises_unavailable(status):
    error = HTTPError(
        url="https://api.frankfurter.dev/v2/rate/EUR/JPY",
        code=status,
        msg="temporary",
        hdrs=None,
        fp=None,
    )
    provider = FrankfurterProvider(max_attempts=2)

    with patch("apps.exchange.providers.frankfurter.urlopen", side_effect=error) as mocked:
        with pytest.raises(FxProviderUnavailable, match=f"HTTP {status}"):
            provider.latest_quote("EUR", "JPY", DEFAULT_SOURCE_POLICY)

    assert mocked.call_count == 2


def test_retryable_http_failure_can_recover_on_second_attempt():
    error = HTTPError(
        url="https://api.frankfurter.dev/v2/rate/EUR/JPY",
        code=503,
        msg="temporary",
        hdrs=None,
        fp=None,
    )
    payload = b'{"date":"2026-09-18","base":"EUR","quote":"JPY","rate":174.5,"providers":["ECB"]}'
    provider = FrankfurterProvider(max_attempts=2)

    with patch(
        "apps.exchange.providers.frankfurter.urlopen",
        side_effect=[error, FakeResponse(payload)],
    ) as mocked:
        result = provider.latest_quote("EUR", "JPY", DEFAULT_SOURCE_POLICY)

    assert mocked.call_count == 2
    assert result.rate == Decimal("174.5")


def test_urlerror_timeout_reason_is_normalized_as_timeout():
    provider = FrankfurterProvider(max_attempts=2)

    with patch(
        "apps.exchange.providers.frankfurter.urlopen",
        side_effect=URLError(TimeoutError("slow")),
    ) as mocked:
        with pytest.raises(FxProviderTimeout):
            provider.latest_quote("EUR", "JPY", DEFAULT_SOURCE_POLICY)

    assert mocked.call_count == 2


def test_non_timeout_urlerror_is_normalized_as_unavailable():
    provider = FrankfurterProvider(max_attempts=2)

    with patch(
        "apps.exchange.providers.frankfurter.urlopen",
        side_effect=URLError("dns"),
    ) as mocked:
        with pytest.raises(FxProviderUnavailable, match="request failed"):
            provider.latest_quote("EUR", "JPY", DEFAULT_SOURCE_POLICY)

    assert mocked.call_count == 2


@pytest.mark.parametrize(
    "error",
    [
        HTTPException("truncated response"),
        ConnectionResetError("reset by peer"),
    ],
)
def test_read_transport_failure_retries_then_normalizes_unavailable(error):
    class FailingReadResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, size=-1):
            raise error

    provider = FrankfurterProvider(max_attempts=2)

    with patch(
        "apps.exchange.providers.frankfurter.urlopen",
        side_effect=lambda *args, **kwargs: FailingReadResponse(),
    ) as mocked:
        with pytest.raises(FxProviderUnavailable, match="request failed"):
            provider.latest_quote("EUR", "JPY", DEFAULT_SOURCE_POLICY)

    assert mocked.call_count == 2


@pytest.mark.parametrize("payload", [b"{not-json", b"\xff"])
def test_runtime_provider_rejects_malformed_json_and_unicode(payload):
    provider = FrankfurterProvider(max_attempts=1)

    with patch(
        "apps.exchange.providers.frankfurter.urlopen",
        return_value=FakeResponse(payload),
    ):
        with pytest.raises(FxProviderInvalidPayload, match="malformed JSON"):
            provider.latest_quote("EUR", "JPY", DEFAULT_SOURCE_POLICY)


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"date": "2026-09-18", "base": "EU", "quote": "JPY", "rate": 174.5},
        {"date": "2026-09-18", "base": "EUR", "quote": "JP1", "rate": 174.5},
        {"date": "2026-09-18", "base": "EUR", "quote": "JPY", "rate": "not-a-number"},
    ],
)
def test_rate_payload_rejects_additional_structural_failures(payload):
    with pytest.raises(FxProviderInvalidPayload):
        parse_rate_payload(
            payload,
            expected_base="EUR",
            expected_quote="JPY",
            requested_date=None,
            policy=DEFAULT_SOURCE_POLICY,
            fetched_at=datetime(2026, 9, 20, tzinfo=UTC),
        )


@pytest.mark.parametrize(
    "payload",
    [
        {},
        [None],
        [{"date": "2026-01-02", "base": "EU", "quote": "JPY", "rate": 180}],
        [
            {
                "date": "2026-01-02",
                "base": "EUR",
                "quote": "JPY",
                "rate": 180,
                "providers": "ECB",
            }
        ],
    ],
)
def test_series_payload_rejects_additional_structural_failures(payload):
    with pytest.raises(FxProviderInvalidPayload):
        parse_series_payload(
            payload,
            expected_base="EUR",
            expected_quote="JPY",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 7),
            grouping=RateSeriesGrouping.DAILY,
            policy=DEFAULT_SOURCE_POLICY,
            fetched_at=datetime(2026, 1, 8, tzinfo=UTC),
        )


def test_rate_series_rejects_invalid_currency_before_network_call():
    provider = FrankfurterProvider()

    with patch("apps.exchange.providers.frankfurter.urlopen") as mocked:
        with pytest.raises(FxProviderUnsupportedPair):
            provider.rate_series(
                "EUR/USD",
                "JPY",
                date(2026, 1, 1),
                date(2026, 1, 7),
                RateSeriesGrouping.DAILY,
                DEFAULT_SOURCE_POLICY,
            )

    mocked.assert_not_called()


def test_historical_pinned_quote_builds_date_provider_and_attribution_query():
    payload = b'{"date":"2026-01-02","base":"EUR","quote":"GBP","rate":0.84,"providers":["HMRC"]}'
    provider = FrankfurterProvider(base_url="https://example.test/v2/", max_attempts=1)
    policy = FxSourcePolicy(
        mode=ProviderPolicyMode.PINNED,
        provider_key="hmrc",
        include_attribution=True,
    )

    with patch(
        "apps.exchange.providers.frankfurter.urlopen",
        return_value=FakeResponse(payload),
    ) as mocked:
        result = provider.historical_quote(
            "EUR",
            "GBP",
            date(2026, 1, 2),
            policy,
        )

    request = mocked.call_args.args[0]
    assert request.full_url.startswith("https://example.test/v2/rate/EUR/GBP?")
    assert "date=2026-01-02" in request.full_url
    assert "providers=hmrc" in request.full_url
    assert "expand=providers" in request.full_url
    assert request.get_header("Accept") == "application/json"
    assert request.get_header("User-agent") == "cultural-currency-converter/0.1"
    assert result.provider_keys == ("hmrc",)
