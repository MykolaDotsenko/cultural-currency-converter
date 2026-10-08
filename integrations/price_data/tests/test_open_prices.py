from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request

import pytest

from integrations.price_data import (
    OpenPricesClient,
    OpenPricesRateLimited,
    OpenPricesSourceError,
    parse_open_prices,
)

_NOW = datetime(2026, 10, 8, 10, tzinfo=UTC)
_TODAY = date(2026, 10, 8)


def _item(**changes):
    row = {
        "id": 123,
        "type": "PRODUCT",
        "product_code": "0034000470693",
        "price": Decimal("4.29"),
        "currency": "EUR",
        "date": "2026-09-30",
        "price_per": "UNIT",
        "proof_id": 998,
        "price_is_discounted": False,
        "duplicate_of": None,
        "location": {
            "osm_display_name": "Example Market Helsinki",
            "osm_address_country_code": "FI",
        },
    }
    row.update(changes)
    return row


def test_parser_preserves_decimal_provenance_place_and_canonical_code():
    result = parse_open_prices(
        {"items": [_item(price=Decimal("4.2900"))]},
        barcode="034000470693",
        retrieved_at=_NOW,
        today=_TODAY,
    )
    assert len(result) == 1
    item = result[0]
    assert format(item.amount, "f") == "4.2900"
    assert item.currency == "EUR"
    assert item.observed_at == date(2026, 9, 30)
    assert item.product_code == "0034000470693"
    assert item.country_code == "FI"
    assert item.location_label == "Example Market Helsinki"
    assert item.proof_id == 998
    assert item.source_url == "https://prices.openfoodfacts.org/api/v1/prices/123"
    assert item.retrieved_at == _NOW


@pytest.mark.parametrize(
    "row",
    [
        _item(product_code="3017624010702"),
        _item(price=Decimal("NaN")),
        _item(price=-2),
        _item(price=0),
        _item(price=Decimal("100000.01")),
        _item(currency="EU"),
        _item(date="2027-01-01"),
        _item(date="2020-01-01"),
        _item(date="not-a-date"),
        _item(price_per="KILOGRAM"),
        _item(proof_id=None),
        _item(location=None),
        _item(location={"osm_address_country_code": "FI"}),
        _item(location={"osm_display_name": "Store", "osm_address_country_code": "bad"}),
        _item(duplicate_of=100),
        _item(type="CATEGORY"),
        _item(id=True),
    ],
)
def test_parser_excludes_incompatible_or_unverifiable_price_evidence(row):
    assert (
        parse_open_prices(
            {"items": [row]},
            barcode="034000470693",
            retrieved_at=_NOW,
            today=_TODAY,
        )
        == ()
    )


def test_parser_rejects_invalid_envelope_and_unaware_retrieval():
    with pytest.raises(OpenPricesSourceError, match="pagination"):
        parse_open_prices({}, barcode="034000470693", retrieved_at=_NOW, today=_TODAY)
    with pytest.raises(OpenPricesSourceError, match="page size"):
        parse_open_prices(
            {"items": [_item()] * 21},
            barcode="034000470693",
            retrieved_at=_NOW,
            today=_TODAY,
        )
    with pytest.raises(OpenPricesSourceError, match="timezone-aware"):
        parse_open_prices(
            {"items": []},
            barcode="034000470693",
            retrieved_at=datetime(2026, 10, 8),
            today=_TODAY,
        )


def test_parser_limits_to_five_dates_without_price_ranking():
    rows = [_item(id=i + 1, date=f"2026-09-{i + 1:02d}") for i in range(10)]
    result = parse_open_prices(
        {"items": rows},
        barcode="034000470693",
        retrieved_at=_NOW,
        today=_TODAY,
    )
    assert len(result) == 5
    assert result[0].observed_at == date(2026, 9, 10)


class _Response:
    def __init__(self, url, data):
        self.url = url
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def geturl(self):
        return self.url

    def read(self, size):
        return self.data[:size]


def test_client_requests_bounded_canonical_product_page():
    def fetch(request, timeout):
        assert timeout == 5.0
        q = parse_qs(urlsplit(request.full_url).query)
        assert q["product_code"] == ["0034000470693"]
        assert q["type"] == ["PRODUCT"]
        assert q["size"] == ["20"]
        assert q["order_by"] == ["-date"]
        return _Response(
            request.full_url, json.dumps({"items": [_item(price="4.29")]}, default=str).encode()
        )

    with patch("integrations.price_data.open_prices.urlopen", side_effect=fetch):
        result = OpenPricesClient().fetch_prices("034000470693")
    assert result[0].amount == Decimal("4.29")


def test_client_fails_closed_on_redirect_or_invalid_json():
    client = OpenPricesClient()
    req = Request("https://prices.openfoodfacts.org/api/v1/prices")
    with patch(
        "integrations.price_data.open_prices.urlopen",
        return_value=_Response("https://unrelated.example/prices", b'{"items":[]}'),
    ):
        with pytest.raises(OpenPricesSourceError, match="unexpected source"):
            client._fetch_json(req)
    with patch(
        "integrations.price_data.open_prices.urlopen",
        return_value=_Response(req.full_url, b"invalid"),
    ):
        with pytest.raises(OpenPricesSourceError, match="malformed JSON"):
            client._fetch_json(req)


def test_client_handles_throttle_and_max_response_size():
    client = OpenPricesClient()
    req = Request("https://prices.openfoodfacts.org/api/v1/prices")
    with patch(
        "integrations.price_data.open_prices.urlopen",
        side_effect=HTTPError(req.full_url, 429, "busy", {}, BytesIO()),
    ):
        with pytest.raises(OpenPricesRateLimited):
            client._fetch_json(req)
    with patch(
        "integrations.price_data.open_prices.urlopen",
        return_value=_Response(req.full_url, b"x" * (256 * 1024 + 1)),
    ):
        with pytest.raises(OpenPricesSourceError, match="size limit"):
            client._fetch_json(req)


@pytest.mark.parametrize(
    "bad_row",
    [
        _item(
            location_id=5,
            location={
                "id": 6,
                "osm_display_name": "Incorrect shop",
                "osm_address_country_code": "FI",
            },
        ),
        _item(proof_id=998, proof={"id": 999}),
        _item(product_id=22, product={"id": 23, "code": "0034000470693"}),
        _item(product={"code": "3017624010702"}),
        _item(product={"code": "garbage"}),
        _item(
            location_id=5,
            location={
                "id": True,
                "osm_display_name": "Invalid link",
                "osm_address_country_code": "FI",
            },
        ),
    ],
)
def test_parser_rejects_crosslinked_product_location_and_proof_identity(bad_row):
    assert (
        parse_open_prices(
            {"items": [bad_row]},
            barcode="034000470693",
            retrieved_at=_NOW,
            today=_TODAY,
        )
        == ()
    )


def test_parser_accepts_equivalent_product_barcode_and_lowercase_osm_country():
    result = parse_open_prices(
        {
            "items": [
                _item(
                    product_code="034000470693",
                    product_id=15,
                    product={"id": 15, "code": "0034000470693"},
                    proof={"id": 998},
                    location_id=12,
                    location={
                        "id": 12,
                        "osm_display_name": "Market Helsinki",
                        "osm_address_country_code": "fi",
                    },
                )
            ]
        },
        barcode="0034000470693",
        retrieved_at=_NOW,
        today=_TODAY,
    )
    assert len(result) == 1
    assert result[0].country_code == "FI"
    assert result[0].product_code == "0034000470693"


def test_client_uses_same_utc_instant_for_retrieval_and_freshness_window():
    fixture_time = datetime(2026, 10, 9, 0, 1, tzinfo=UTC)
    with (
        patch("integrations.price_data.open_prices.datetime") as dt,
        patch("integrations.price_data.open_prices.parse_open_prices") as parser,
        patch.object(OpenPricesClient, "_fetch_json", return_value={"items": []}),
    ):
        dt.now.return_value = fixture_time
        parser.return_value = ()
        assert OpenPricesClient().fetch_prices("034000470693") == ()

    assert parser.call_args.kwargs["retrieved_at"] == fixture_time
    assert parser.call_args.kwargs["today"] == fixture_time.date()
