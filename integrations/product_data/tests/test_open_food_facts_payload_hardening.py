"""External product metadata must be schema-safe before entering trusted cache."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch
from urllib.request import Request

import pytest

from integrations.product_data import ProductDataSourceError, ProductNotFound
from integrations.product_data.open_food_facts import (
    OpenFoodFactsClient,
    parse_open_food_facts_product,
)

_BARCODE = "3017624010701"
_URL = f"https://world.openfoodfacts.org/api/v3.6/product/{_BARCODE}.json"


@pytest.mark.parametrize("status", [[], {}, [0], {"value": 1}, False, True, 0.0])
def test_untrusted_product_status_type_fails_as_optional_provider_error(status):
    payload = {
        "status": status,
        "code": _BARCODE,
        "product": {"code": _BARCODE, "product_name": "Test product"},
    }
    with pytest.raises(ProductDataSourceError, match="invalid product status"):
        parse_open_food_facts_product(
            payload,
            requested_barcode=_BARCODE,
            retrieved_at=datetime(2026, 10, 8, tzinfo=UTC),
        )


@pytest.mark.parametrize("status", [0, "0", "not_found"])
def test_known_missing_product_status_keeps_existing_contract(status):
    with pytest.raises(ProductNotFound):
        parse_open_food_facts_product(
            {"status": status},
            requested_barcode=_BARCODE,
            retrieved_at=datetime(2026, 10, 8, tzinfo=UTC),
        )


class RawProviderResponse:
    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def geturl(self):
        return _URL

    def read(self, _size):
        return self.body


@pytest.mark.parametrize(
    "body",
    [
        b'{"code":"3017624010701","code":"3017624010702","product":{"product_name":"Food"}}',
        b'{"code":"3017624010701","product":{"code":"3017624010701","code":"3017624010702","product_name":"Food"}}',
        b'{"code":"3017624010701","product":{"code":"3017624010701","product_name":"Food","nutriments":{"fat":NaN}}}',
        b'{"code":"3017624010701","product":{"code":"3017624010701","product_name":"Food","quantity":Infinity}}',
        b'{"code":"3017624010701","product":{"code":"3017624010701","product_name":"Food","quantity":-Infinity}}',
        b'{"code":"3017624010701","product":',
    ],
)
def test_external_product_json_rejects_duplicates_nonfinite_and_malformed_body(body):
    client = OpenFoodFactsClient()
    with (
        patch(
            "integrations.product_data.open_food_facts.urlopen",
            return_value=RawProviderResponse(body),
        ),
        pytest.raises(ProductDataSourceError, match="malformed JSON"),
    ):
        client._fetch_json(Request(_URL))


def test_strict_product_json_preserves_valid_optional_fields():
    body = (
        b'{"status":"success","code":"3017624010701",'
        b'"product":{"code":"3017624010701","product_name":"Food",'
        b'"nutriments":{"energy":250},"quantity":"100 g"}}'
    )
    client = OpenFoodFactsClient()
    with patch(
        "integrations.product_data.open_food_facts.urlopen",
        return_value=RawProviderResponse(body),
    ):
        payload = client._fetch_json(Request(_URL))

    product = parse_open_food_facts_product(
        payload,
        requested_barcode=_BARCODE,
        retrieved_at=datetime(2026, 10, 8, tzinfo=UTC),
    )
    assert product.barcode == _BARCODE
    assert product.product_name == "Food"
    assert product.quantity == "100 g"
    assert not hasattr(product, "nutriments")
