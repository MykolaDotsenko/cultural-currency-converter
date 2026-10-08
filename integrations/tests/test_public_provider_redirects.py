"""Every public-data provider must use a pre-redirect origin-pinned opener."""

from __future__ import annotations

from importlib import import_module
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request

import pytest


@pytest.mark.parametrize(
    ("module", "host"),
    [
        ("integrations.economic_data.eurostat", "ec.europa.eu"),
        ("integrations.economic_data.world_bank", "api.worldbank.org"),
        ("integrations.economic_data.oecd", "sdmx.oecd.org"),
        ("integrations.holidays.nager", "nagerholidays.com"),
        ("integrations.wikidata.client", "www.wikidata.org"),
        ("integrations.product_data.open_food_facts", "world.openfoodfacts.org"),
        ("integrations.price_data.open_prices", "prices.openfoodfacts.org"),
    ],
)
def test_public_provider_cannot_send_initial_request_to_another_origin(module, host):
    provider = import_module(module)

    with patch("urllib.request.OpenerDirector.open") as outgoing:
        with pytest.raises(HTTPError, match="Unexpected public-data request origin"):
            provider.urlopen(Request("https://169.254.169.254/latest/meta-data"), timeout=2)
        outgoing.assert_not_called()

        expected = Request(f"https://{host}/api/example")
        provider.urlopen(expected, timeout=2)
        outgoing.assert_called_once_with(expected, timeout=2)
