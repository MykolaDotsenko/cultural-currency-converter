from __future__ import annotations

import ipaddress

import pytest

from config.api_security import load_trusted_proxy_networks
from config.environment import ConfigurationError


def test_trusted_proxies_default_to_off():
    assert load_trusted_proxy_networks({}) == ()
    assert load_trusted_proxy_networks({"API_TRUSTED_PROXY_CIDRS": " "}) == ()


def test_trusted_proxy_config_accepts_explicit_ipv4_ipv6_cidrs_and_deduplicates():
    config = load_trusted_proxy_networks(
        {"API_TRUSTED_PROXY_CIDRS": "10.42.0.0/16,2001:db8:1::/48,10.42.0.0/16"}
    )
    assert config == (
        ipaddress.ip_network("10.42.0.0/16"),
        ipaddress.ip_network("2001:db8:1::/48"),
    )


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("10.42.1.3/16", "canonical IP networks"),
        ("garbage", "canonical IP networks"),
        ("10.0.0.0/8,", "1–16 nonempty CIDRs"),
        (",10.0.0.0/8", "1–16 nonempty CIDRs"),
        ("0.0.0.0/0", "entire internet"),
        ("::/0", "entire internet"),
        (",".join(["10.42.0.1/32"] * 17), "1–16 nonempty CIDRs"),
    ],
)
def test_unsafe_or_malformed_trusted_proxy_config_fails_fast(value, message):
    with pytest.raises(ConfigurationError, match=message):
        load_trusted_proxy_networks({"API_TRUSTED_PROXY_CIDRS": value})
