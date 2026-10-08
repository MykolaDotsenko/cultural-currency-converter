"""Open Prices transport rejects ambiguous upstream financial evidence."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch
from urllib.request import Request

import pytest

from integrations.price_data import OpenPricesClient, OpenPricesSourceError

_URL = "https://prices.openfoodfacts.org/api/v1/prices"


class RawPriceResponse:
    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def geturl(self):
        return _URL

    def read(self, _limit):
        return self.body


@pytest.mark.parametrize(
    "body",
    [
        b'{"items":[],"items":[{"price":9999}]}',
        b'{"items":[{"price":4.29,"price":9999}]}',
        b'{"items":[],"meta":{"revision":1,"revision":2}}',
        b'{"items":[{"price":NaN}]}',
        b'{"items":[{"price":Infinity}]}',
        b'{"items":[{"price":-Infinity}]}',
        b'{"items":',
        b'{"items":' + b"[" * 1100 + b"0" + b"]" * 1100 + b"}",
    ],
)
def test_open_prices_rejects_ambiguous_or_nonstandard_json_before_parsing(body):
    client = OpenPricesClient()
    with (
        patch(
            "integrations.price_data.open_prices.urlopen",
            return_value=RawPriceResponse(body),
        ),
        pytest.raises(OpenPricesSourceError, match="malformed JSON"),
    ):
        client._fetch_json(Request(_URL))


def test_open_prices_json_preserves_precise_decimal_scale():
    client = OpenPricesClient()
    body = b'{"items":[{"price":4.2900,"currency":"EUR","meta":{"trusted":true}}]}'
    with patch(
        "integrations.price_data.open_prices.urlopen",
        return_value=RawPriceResponse(body),
    ):
        result = client._fetch_json(Request(_URL))

    assert isinstance(result["items"][0]["price"], Decimal)
    assert str(result["items"][0]["price"]) == "4.2900"
    assert result["items"][0]["meta"] == {"trusted": True}
