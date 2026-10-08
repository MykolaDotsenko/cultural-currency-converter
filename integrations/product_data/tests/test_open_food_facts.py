from __future__ import annotations

from datetime import UTC, datetime

import pytest

from integrations.product_data.base import ProductDataSourceError, ProductNotFound
from integrations.product_data.open_food_facts import (
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
