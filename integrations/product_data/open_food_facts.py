from __future__ import annotations

import json
import re
import socket
from datetime import UTC, datetime
from http.client import HTTPException
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request

from integrations.http_transport import is_trusted_https_url, make_pinned_https_urlopen

from integrations.product_data.base import (
    ProductDataSourceError,
    ProductIdentity,
    ProductNotFound,
    ProductSourceRateLimited,
)

BASE_URL = "https://world.openfoodfacts.org/api/v3.6/product"
urlopen = make_pinned_https_urlopen("world.openfoodfacts.org")
MAX_RESPONSE_BYTES = 512 * 1024
_BARCODE_RE = re.compile(r"^\d{7,14}$")
_FIELDS = "code,product_name,brands,quantity,categories"


def normalize_barcode(value: str) -> str:
    barcode = "".join(value.split())
    if not _BARCODE_RE.fullmatch(barcode):
        raise ValueError("Barcode must contain 7–14 digits.")
    return barcode


def canonical_open_food_facts_barcode(value: str) -> str:
    """Mirror Open Food Facts' leading-zero normalization for trusted identity.

    7 or fewer significant digits become EAN-8; 9–12 become EAN-13.
    EAN-8, EAN-13 and GTIN-14 retain their significant length. Never compare
    raw provider and scanner strings without this normalization.
    """
    barcode = normalize_barcode(value)
    significant = barcode.lstrip("0")
    if not significant:
        raise ValueError("Barcode cannot be all zeroes.")
    if len(significant) <= 7:
        return significant.zfill(8)
    if 9 <= len(significant) <= 12:
        return significant.zfill(13)
    return significant


def _verified_product_barcode(
    payload: dict[str, Any],
    product: dict[str, Any],
    *,
    requested_barcode: str,
) -> str:
    """A provider response must identify the *requested* product, not another."""
    try:
        expected = canonical_open_food_facts_barcode(requested_barcode)
    except ValueError as exc:
        raise ProductDataSourceError("Requested product barcode is invalid.") from exc

    returned_codes = [
        raw for raw in (payload.get("code"), product.get("code")) if raw is not None
    ]
    if not returned_codes:
        raise ProductDataSourceError("Open Food Facts product identity is missing.")
    for returned in returned_codes:
        if not isinstance(returned, str):
            raise ProductDataSourceError("Open Food Facts product barcode is invalid.")
        try:
            verified = canonical_open_food_facts_barcode(returned)
        except ValueError as exc:
            raise ProductDataSourceError("Open Food Facts product barcode is invalid.") from exc
        if verified != expected:
            raise ProductDataSourceError(
                "Open Food Facts returned a different product barcode."
            )
    return expected


def _text(value: Any, *, max_length: int) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:max_length]


def _csv_parts(value: Any, *, max_items: int = 8) -> tuple[str, ...]:
    text = _text(value, max_length=1000)
    if not text:
        return ()
    values = [" ".join(part.split()) for part in text.split(",")]
    return tuple(dict.fromkeys(value for value in values if value))[:max_items]


def parse_open_food_facts_product(
    payload: Any,
    *,
    requested_barcode: str,
    retrieved_at: datetime,
) -> ProductIdentity:
    if not isinstance(payload, dict):
        raise ProductDataSourceError("Open Food Facts response must be an object.")

    status = payload.get("status")
    if status in {0, "0", "not_found"}:
        raise ProductNotFound("Product is not available in Open Food Facts.")

    product = payload.get("product")
    if not isinstance(product, dict):
        errors = payload.get("errors")
        if isinstance(errors, list) and errors:
            raise ProductNotFound("Product is not available in Open Food Facts.")
        raise ProductDataSourceError("Open Food Facts response is missing product data.")

    product_name = _text(product.get("product_name"), max_length=240)
    if not product_name:
        raise ProductDataSourceError("Open Food Facts product has no usable product name.")

    barcode = _verified_product_barcode(
        payload,
        product,
        requested_barcode=requested_barcode,
    )
    brands = _csv_parts(product.get("brands"), max_items=6)
    quantity = _text(product.get("quantity"), max_length=120)
    categories = _csv_parts(product.get("categories"), max_items=6)

    return ProductIdentity(
        barcode=barcode,
        product_name=product_name,
        brands=brands,
        quantity=quantity,
        categories=categories,
        source_name="Open Food Facts",
        source_url=f"https://world.openfoodfacts.org/product/{barcode}",
        retrieved_at=retrieved_at,
    )


class OpenFoodFactsClient:
    def __init__(self, *, timeout_seconds: float = 6.0):
        if not 0 < timeout_seconds <= 20:
            raise ValueError("Open Food Facts timeout must be > 0 and <= 20 seconds.")
        self.timeout_seconds = timeout_seconds

    def fetch_product(self, barcode: str) -> ProductIdentity:
        normalized = normalize_barcode(barcode)
        params = urlencode({"fields": _FIELDS})
        url = f"{BASE_URL}/{normalized}.json?{params}"
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": (
                    "CulturalCurrencyConverter/0.1 "
                    "(https://github.com/MykolaDotsenko/cultural-currency-converter)"
                ),
            },
        )
        payload = self._fetch_json(request)
        return parse_open_food_facts_product(
            payload,
            requested_barcode=normalized,
            retrieved_at=datetime.now(UTC),
        )

    def _fetch_json(self, request: Request) -> Any:
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                if not is_trusted_https_url(response.geturl(), "world.openfoodfacts.org"):
                    raise ProductDataSourceError(
                        "Open Food Facts request resolved to an unexpected source."
                    )
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            if exc.code == 404:
                raise ProductNotFound("Product is not available in Open Food Facts.") from exc
            if exc.code == 429:
                raise ProductSourceRateLimited("Open Food Facts lookup limit reached.") from exc
            raise ProductDataSourceError(
                f"Open Food Facts returned HTTP {exc.code}."
            ) from exc
        except (URLError, HTTPException, TimeoutError, socket.timeout, OSError) as exc:
            raise ProductDataSourceError("Open Food Facts request failed.") from exc

        if len(raw) > MAX_RESPONSE_BYTES:
            raise ProductDataSourceError("Open Food Facts response exceeded the size limit.")
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ProductDataSourceError("Open Food Facts returned malformed JSON.") from exc
