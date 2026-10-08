from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.test import RequestFactory

from apps.exchange.api_quota import ConversionQuotaUnavailable, consume_conversion_quota


@pytest.fixture(autouse=True)
def reset_conversion_quota_cache():
    cache.clear()
    yield
    cache.clear()


def _request(remote_addr: str, *, forwarded_for: str = ""):
    return RequestFactory().post(
        "/api/v1/conversions/",
        REMOTE_ADDR=remote_addr,
        HTTP_X_FORWARDED_FOR=forwarded_for,
    )


def test_quota_is_per_server_peer_and_forwarded_headers_cannot_bypass_it():
    first = _request("203.0.113.8")
    spoofed = _request("203.0.113.8", forwarded_for="198.51.100.100")
    independent = _request("203.0.113.9")

    with patch("apps.exchange.api_quota._MAX_CONVERSIONS_PER_MINUTE", 1):
        assert consume_conversion_quota(first).allowed is True
        assert consume_conversion_quota(spoofed).allowed is False
        assert consume_conversion_quota(independent).allowed is True


def test_equivalent_ipv6_addresses_share_one_origin_budget():
    first = _request("2001:db8::1")
    same = _request("2001:0db8:0:0:0:0:0:1")
    with patch("apps.exchange.api_quota._MAX_CONVERSIONS_PER_MINUTE", 1):
        assert consume_conversion_quota(first).allowed is True
        assert consume_conversion_quota(same).allowed is False


def test_quota_resets_in_next_utc_minute_and_retry_after_is_bounded():
    request = _request("192.0.2.7")
    with (
        patch("apps.exchange.api_quota._MAX_CONVERSIONS_PER_MINUTE", 1),
        patch("apps.exchange.api_quota.timezone.now") as now,
    ):
        now.return_value = datetime(2026, 10, 8, 10, 10, 21, tzinfo=UTC)
        assert consume_conversion_quota(request).retry_after == 39
        assert consume_conversion_quota(request).allowed is False
        now.return_value = datetime(2026, 10, 8, 10, 11, tzinfo=UTC)
        fresh = consume_conversion_quota(request)

    assert fresh.allowed is True
    assert fresh.retry_after == 60


def test_cache_keys_do_not_expose_raw_client_ip():
    request = _request("203.0.113.123")
    with patch("apps.exchange.api_quota.cache.add", wraps=cache.add) as add:
        assert consume_conversion_quota(request).allowed is True

    key = add.call_args.args[0]
    assert key.startswith("api:v1:conversion-quota:")
    assert "203.0.113.123" not in key


def test_quota_fails_closed_on_cache_outage():
    with (
        patch("apps.exchange.api_quota.cache.add", side_effect=OSError("down")),
        pytest.raises(ConversionQuotaUnavailable),
    ):
        consume_conversion_quota(_request("192.0.2.1"))


def test_quota_fails_closed_on_missing_counter_during_race():
    with (
        patch("apps.exchange.api_quota.cache.add", return_value=False),
        patch("apps.exchange.api_quota.cache.incr", side_effect=ValueError("gone")),
        pytest.raises(ConversionQuotaUnavailable),
    ):
        consume_conversion_quota(_request("192.0.2.2"))
