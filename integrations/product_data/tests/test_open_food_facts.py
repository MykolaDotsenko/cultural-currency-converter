from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import patch
from urllib.request import Request

import pytest

from integrations.product_data.base import ProductDataSourceError, ProductNotFound
from integrations.product_data.open_food_facts import (
    OpenFoodFactsClient,
    normalize_barcode,
    parse_open_food_facts_product,
)


def test_open_food_facts_parser_extracts_identity_only():
    product = parse_open_food_facts_product(
        {
            "status": "success",
            "code": "3017624010701",
            "product": {
                "code": "3017624010701",
                "product_name": "Hazelnut cocoa spread",
                "brands": "Example Brand, Parent Brand",
                "quantity": "400 g",
                "categories": "Spreads, Hazelnut spreads",
                "nutriments": {"energy-kcal_100g": 500},
                "stores": "Example supermarket",
            },
        },
        requested_barcode="3017624010701",
        retrieved_at=datetime(2026, 10, 8, tzinfo=UTC),
    )

    assert product.barcode == "3017624010701"
    assert product.product_name == "Hazelnut cocoa spread"
    assert product.brands == ("Example Brand", "Parent Brand")
    assert product.quantity == "400 g"
    assert product.categories == ("Spreads", "Hazelnut spreads")
    assert product.source_name == "Open Food Facts"
    assert product.source_url.endswith("/product/3017624010701")
    assert not hasattr(product, "price")
    assert not hasattr(product, "nutriments")


def test_open_food_facts_not_found_is_normalized():
    with pytest.raises(ProductNotFound):
        parse_open_food_facts_product(
            {"status": 0, "code": "12345678"},
            requested_barcode="12345678",
            retrieved_at=datetime(2026, 10, 8, tzinfo=UTC),
        )


def test_open_food_facts_missing_product_name_fails_closed():
    with pytest.raises(ProductDataSourceError, match="product name"):
        parse_open_food_facts_product(
            {"status": "success", "product": {"code": "12345678"}},
            requested_barcode="12345678",
            retrieved_at=datetime(2026, 10, 8, tzinfo=UTC),
        )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("3017624010701", "3017624010701"),
        (" 3017624010701 ", "3017624010701"),
        ("1234567", "1234567"),
        ("12345678901234", "12345678901234"),
    ],
)
def test_barcode_normalization_accepts_bounded_numeric_codes(raw, expected):
    assert normalize_barcode(raw) == expected


@pytest.mark.parametrize("raw", ["", "123", "123456789012345", "ABC12345", "1234-5678"])
def test_barcode_normalization_rejects_non_consumer_codes(raw):
    with pytest.raises(ValueError):
        normalize_barcode(raw)


@pytest.mark.parametrize(
    ("requested", "returned", "canonical"),
    [
        ("034000470693", "0034000470693", "0034000470693"),
        ("0034000470693", "034000470693", "0034000470693"),
        ("1234567", "01234567", "01234567"),
        ("01234567", "1234567", "01234567"),
        ("3017624010701", "3017624010701", "3017624010701"),
        ("12345678901234", "12345678901234", "12345678901234"),
    ],
)
def test_open_food_facts_accepts_only_canonical_barcode_equivalence(requested, returned, canonical):
    identity = parse_open_food_facts_product(
        {
            "status": "success",
            "code": requested,
            "product": {"code": returned, "product_name": "Example food"},
        },
        requested_barcode=requested,
        retrieved_at=datetime(2026, 10, 8, tzinfo=UTC),
    )

    assert identity.barcode == canonical
    assert identity.source_url == f"https://world.openfoodfacts.org/product/{canonical}"


@pytest.mark.parametrize(
    "payload",
    [
        {"code": "3017624010702", "product": {"code": "3017624010702", "product_name": "Wrong"}},
        {
            "code": "3017624010701",
            "product": {"code": "3017624010702", "product_name": "Conflicting"},
        },
        {"code": "not-a-code", "product": {"product_name": "Malformed"}},
        {"product": {"product_name": "Missing code"}},
        {"code": 3017624010701, "product": {"product_name": "Numeric identity"}},
        {"code": "0000000000000", "product": {"product_name": "Invalid zero code"}},
    ],
)
def test_open_food_facts_rejects_mismatched_or_unverifiable_product_identity(payload):
    with pytest.raises(ProductDataSourceError, match=r"barcode|identity"):
        parse_open_food_facts_product(
            {"status": "success", **payload},
            requested_barcode="3017624010701",
            retrieved_at=datetime(2026, 10, 8, tzinfo=UTC),
        )


class _Response:
    def __init__(self, url: str):
        self.url = url

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def geturl(self):
        return self.url

    def read(self, _size):
        return json.dumps(
            {
                "code": "3017624010701",
                "product": {"code": "3017624010701", "product_name": "Food"},
            }
        ).encode()


def test_product_client_allows_only_expected_provenance_origin():
    request = Request("https://world.openfoodfacts.org/api/v3.6/product/3017624010701.json")
    client = OpenFoodFactsClient()

    with patch(
        "integrations.product_data.open_food_facts.urlopen",
        return_value=_Response(
            "https://world.openfoodfacts.org/api/v3.6/product/3017624010701.json"
        ),
    ):
        assert client._fetch_json(request)["product"]["product_name"] == "Food"

    with (
        patch(
            "integrations.product_data.open_food_facts.urlopen",
            return_value=_Response(
                "https://world.openbeautyfacts.org/api/v3.6/product/3017624010701.json"
            ),
        ),
        pytest.raises(ProductDataSourceError, match="unexpected source"),
    ):
        client._fetch_json(request)
