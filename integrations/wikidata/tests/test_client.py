from __future__ import annotations

import json
from datetime import UTC, datetime
from urllib.error import HTTPError

import pytest

from integrations.wikidata import client as client_module
from integrations.wikidata.client import (
    WikidataItemClient,
    WikidataSourceError,
    normalize_wikidata_item,
)

NOW = datetime(2026, 9, 21, tzinfo=UTC)


class FakeResponse:
    def __init__(self, payload: bytes):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, amount: int) -> bytes:
        return self.payload[:amount]


def test_normalize_wikidata_item_supports_rest_language_maps():
    item = normalize_wikidata_item(
        {
            "id": "Q4916",
            "labels": {"en": "euro"},
            "descriptions": {"en": "currency of the eurozone"},
        },
        retrieved_at=NOW,
    )

    assert item.item_id == "Q4916"
    assert item.label == "euro"
    assert item.description == "currency of the eurozone"
    assert item.source_url == "https://www.wikidata.org/wiki/Q4916"


def test_normalize_wikidata_item_supports_value_objects():
    item = normalize_wikidata_item(
        {
            "id": "Q123",
            "labels": {"en": {"language": "en", "value": "Example"}},
            "descriptions": {"en": {"language": "en", "value": "Example description"}},
        },
        retrieved_at=NOW,
    )

    assert item.label == "Example"


def test_client_uses_fixed_versioned_endpoint_and_user_agent(monkeypatch):
    payload = json.dumps(
        {
            "id": "Q4916",
            "labels": {"en": "euro"},
            "descriptions": {"en": "currency of the eurozone"},
        }
    ).encode()
    seen = {}

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["timeout"] = timeout
        seen["ua"] = request.headers["User-agent"]
        return FakeResponse(payload)

    monkeypatch.setattr(client_module, "urlopen", fake_urlopen)

    item = WikidataItemClient(timeout_seconds=4).get_item("q4916")

    assert item.item_id == "Q4916"
    assert seen["url"].endswith("/entities/items/Q4916")
    assert seen["url"].startswith("https://www.wikidata.org/w/rest.php/wikibase/v1/")
    assert seen["timeout"] == 4
    assert "CulturalCurrencyConverter" in seen["ua"]


@pytest.mark.parametrize("item_id", ["", "P31", "Q0", "QABC", "../../Q1"])
def test_client_rejects_invalid_qid_before_network(item_id):
    with pytest.raises(ValueError, match="Q123"):
        WikidataItemClient().get_item(item_id)


def test_client_normalizes_404_and_429(monkeypatch):
    def not_found(request, timeout):
        raise HTTPError(request.full_url, 404, "missing", {}, None)

    monkeypatch.setattr(client_module, "urlopen", not_found)
    with pytest.raises(WikidataSourceError, match="does not exist"):
        WikidataItemClient().get_item("Q1")

    def limited(request, timeout):
        raise HTTPError(request.full_url, 429, "limited", {}, None)

    monkeypatch.setattr(client_module, "urlopen", limited)
    with pytest.raises(WikidataSourceError, match="rate limit"):
        WikidataItemClient().get_item("Q1")


def test_client_rejects_malformed_json(monkeypatch):
    monkeypatch.setattr(
        client_module,
        "urlopen",
        lambda request, timeout: FakeResponse(b"{bad"),
    )

    with pytest.raises(WikidataSourceError, match="malformed"):
        WikidataItemClient().get_item("Q1")
