from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from http.client import HTTPException
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request

from integrations.http_transport import make_pinned_https_urlopen

_BASE_URL = "https://www.wikidata.org/w/rest.php/wikibase/v1"
urlopen = make_pinned_https_urlopen("www.wikidata.org")
_MAX_RESPONSE_BYTES = 1024 * 1024
_QID_RE = re.compile(r"^Q[1-9]\d{0,15}$")


class WikidataSourceError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class WikidataItem:
    item_id: str
    label: str
    description: str
    source_url: str
    retrieved_at: datetime


def normalize_wikidata_item(payload: Any, *, retrieved_at: datetime) -> WikidataItem:
    if not isinstance(payload, dict):
        raise WikidataSourceError("Wikidata item response must be an object.")

    item_id = str(payload.get("id") or "").upper()
    if not _QID_RE.fullmatch(item_id):
        raise WikidataSourceError("Wikidata item response has an invalid entity ID.")

    label = _language_text(payload.get("labels"), "en")
    description = _language_text(payload.get("descriptions"), "en")
    if not label:
        raise WikidataSourceError("Wikidata item has no usable English label.")
    if not description:
        raise WikidataSourceError("Wikidata item has no usable English description.")

    return WikidataItem(
        item_id=item_id,
        label=label[:240],
        description=description,
        source_url=f"https://www.wikidata.org/wiki/{item_id}",
        retrieved_at=retrieved_at,
    )


def _language_text(value: Any, language: str) -> str:
    if not isinstance(value, dict):
        return ""
    candidate = value.get(language)
    if isinstance(candidate, str):
        return " ".join(candidate.split())
    if isinstance(candidate, dict):
        raw = candidate.get("value")
        if isinstance(raw, str):
            return " ".join(raw.split())
    return ""


class WikidataItemClient:
    def __init__(self, *, timeout_seconds: float = 10.0):
        if not 0 < timeout_seconds <= 30:
            raise ValueError("Wikidata timeout must be > 0 and <= 30 seconds.")
        self.timeout_seconds = timeout_seconds

    def get_item(self, item_id: str) -> WikidataItem:
        normalized_id = item_id.strip().upper()
        if not _QID_RE.fullmatch(normalized_id):
            raise ValueError("Wikidata item ID must look like Q123.")

        request = Request(
            f"{_BASE_URL}/entities/items/{normalized_id}",
            headers={
                "Accept": "application/json",
                "User-Agent": (
                    "CulturalCurrencyConverter/0.1 "
                    "(editorial-story-ingestion; contact via repository)"
                ),
            },
        )
        payload = self._request_json(request)
        return normalize_wikidata_item(payload, retrieved_at=datetime.now(UTC))

    def _request_json(self, request: Request) -> Any:
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read(_MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            if exc.code == 404:
                raise WikidataSourceError("Wikidata item does not exist.") from exc
            if exc.code == 429:
                raise WikidataSourceError("Wikidata rate limit reached.") from exc
            raise WikidataSourceError(f"Wikidata returned HTTP {exc.code}.") from exc
        except (URLError, HTTPException, TimeoutError) as exc:
            raise WikidataSourceError("Wikidata request failed.") from exc

        if len(raw) > _MAX_RESPONSE_BYTES:
            raise WikidataSourceError("Wikidata response exceeded the size limit.")
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise WikidataSourceError("Wikidata returned malformed JSON.") from exc
