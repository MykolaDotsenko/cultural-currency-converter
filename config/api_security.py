"""Explicit trusted-proxy boundary for security-sensitive API quotas.

No forwarded client address is trusted unless the deployment operator
configures exact reverse-proxy IP ranges. This is separate from Django's
HTTPS-forwarding setting.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping

from config.environment import ConfigurationError

ProxyNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network


def load_trusted_proxy_networks(environ: Mapping[str, str]) -> tuple[ProxyNetwork, ...]:
    raw = environ.get("API_TRUSTED_PROXY_CIDRS", "").strip()
    if not raw:
        return ()

    entries = raw.split(",")
    if len(entries) > 16 or any(not entry.strip() for entry in entries):
        raise ConfigurationError("API_TRUSTED_PROXY_CIDRS must contain 1–16 nonempty CIDRs.")

    networks: list[ProxyNetwork] = []
    for entry in entries:
        try:
            network = ipaddress.ip_network(entry.strip(), strict=True)
        except ValueError as exc:
            raise ConfigurationError(
                "API_TRUSTED_PROXY_CIDRS entries must be valid canonical IP networks."
            ) from exc
        if network.prefixlen == 0:
            raise ConfigurationError("API_TRUSTED_PROXY_CIDRS must not trust the entire internet.")
        if network not in networks:
            networks.append(network)
    return tuple(networks)
