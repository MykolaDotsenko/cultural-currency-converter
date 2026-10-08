"""Read-only Open Prices observations; never a reference price or financial input."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from http.client import HTTPException
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request

from integrations.http_transport import is_trusted_https_url, make_pinned_https_urlopen
from integrations.product_data import canonical_open_food_facts_barcode

BASE_URL = "https://prices.openfoodfacts.org/api/v1/prices"
urlopen = make_pinned_https_urlopen("prices.openfoodfacts.org")
MAX_RESPONSE_BYTES = 256 * 1024
_MAX_PROVIDER_ITEMS = 20
_MAX_OBSERVATIONS = 5
_MAX_AGE_DAYS = 365
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_COUNTRY_RE = re.compile(r"^[A-Z]{2}$")


class OpenPricesSourceError(RuntimeError):
    pass


class OpenPricesRateLimited(OpenPricesSourceError):
    pass


@dataclass(frozen=True, slots=True)
class PublicPriceObservation:
    product_code: str
    amount: Decimal
    currency: str
    observed_at: date
    country_code: str
    location_label: str
    discounted: bool
    proof_id: int
    source_url: str
    retrieved_at: datetime


def _clean_label(raw: Any) -> str:
    if not isinstance(raw, str):
        return ""
    return " ".join(raw.split())[:100]


def _parse_item(
    raw: Any,
    *,
    expected_code: str,
    retrieved_at: datetime,
    today: date,
) -> PublicPriceObservation | None:
    if not isinstance(raw, dict) or raw.get("type") != "PRODUCT":
        return None
    if raw.get("duplicate_of") is not None or raw.get("price_per") != "UNIT":
        return None
    code = raw.get("product_code")
    if not isinstance(code, str):
        return None
    try:
        if canonical_open_food_facts_barcode(code) != expected_code:
            return None
    except ValueError:
        return None

    row_id, proof_id = raw.get("id"), raw.get("proof_id")
    if type(row_id) is not int or row_id <= 0 or type(proof_id) is not int or proof_id <= 0:
        return None

    amount = raw.get("price")
    if isinstance(amount, bool) or not isinstance(amount, (int, Decimal, str)):
        return None
    try:
        decimal_amount = Decimal(str(amount))
    except (InvalidOperation, ValueError):
        return None
    if not decimal_amount.is_finite() or not Decimal("0") < decimal_amount <= Decimal("100000"):
        return None

    currency = raw.get("currency")
    if not isinstance(currency, str) or not _CURRENCY_RE.fullmatch(currency):
        return None

    try:
        observation_date = date.fromisoformat(str(raw.get("date") or ""))
    except ValueError:
        return None
    if observation_date > today or observation_date < today - timedelta(days=_MAX_AGE_DAYS):
        return None

    location = raw.get("location")
    if not isinstance(location, dict):
        return None
    raw_country = location.get("osm_address_country_code")
    if not isinstance(raw_country, str):
        return None
    country_code = raw_country.upper()
    if not _COUNTRY_RE.fullmatch(country_code):
        return None
    # The expanded relationship IDs must agree with their top-level foreign
    # keys when populated; never attach a different store/proof/product.
    for linked_key, embedded_key in (
        ("location_id", "location"),
        ("proof_id", "proof"),
        ("product_id", "product"),
    ):
        embedded = raw.get(embedded_key)
        if not isinstance(embedded, dict):
            continue
        embedded_id = embedded.get("id")
        outer_id = raw.get(linked_key)
        if (
            embedded_id is not None
            and outer_id is not None
            and (
                type(embedded_id) is not int or type(outer_id) is not int or embedded_id != outer_id
            )
        ):
            return None
    embedded_product = raw.get("product")
    if isinstance(embedded_product, dict) and embedded_product.get("code") is not None:
        raw_embedded_code = embedded_product["code"]
        if not isinstance(raw_embedded_code, str):
            return None
        try:
            if canonical_open_food_facts_barcode(raw_embedded_code) != expected_code:
                return None
        except ValueError:
            return None

    location_label = (
        _clean_label(location.get("osm_display_name"))
        or _clean_label(location.get("osm_name"))
        or _clean_label(location.get("osm_address_city"))
    )
    if not location_label:
        return None

    return PublicPriceObservation(
        product_code=expected_code,
        amount=decimal_amount,
        currency=currency,
        observed_at=observation_date,
        country_code=country_code,
        location_label=location_label,
        discounted=raw.get("price_is_discounted") is True,
        proof_id=proof_id,
        source_url=f"{BASE_URL}/{row_id}",
        retrieved_at=retrieved_at,
    )


def parse_open_prices(
    payload: Any,
    *,
    barcode: str,
    retrieved_at: datetime,
    today: date,
) -> tuple[PublicPriceObservation, ...]:
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise OpenPricesSourceError("Open Prices response has invalid pagination.")
    rows = payload["items"]
    if len(rows) > _MAX_PROVIDER_ITEMS:
        raise OpenPricesSourceError("Open Prices response exceeded the requested page size.")

    try:
        expected_code = canonical_open_food_facts_barcode(barcode)
    except ValueError as exc:
        raise OpenPricesSourceError("Requested product identity is invalid.") from exc
    if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
        raise OpenPricesSourceError("Observation retrieval time must be timezone-aware.")

    normalized = [
        candidate
        for row in rows
        if (
            candidate := _parse_item(
                row,
                expected_code=expected_code,
                retrieved_at=retrieved_at,
                today=today,
            )
        )
        is not None
    ]
    normalized.sort(key=lambda row: (row.observed_at, row.source_url), reverse=True)
    return tuple(normalized[:_MAX_OBSERVATIONS])


class OpenPricesClient:
    def __init__(self, *, timeout_seconds: float = 5.0):
        if not 0 < timeout_seconds <= 15:
            raise ValueError("Open Prices timeout must be > 0 and <= 15 seconds.")
        self.timeout_seconds = timeout_seconds

    def fetch_prices(self, barcode: str) -> tuple[PublicPriceObservation, ...]:
        normalized = canonical_open_food_facts_barcode(barcode)
        query = urlencode(
            {
                "product_code": normalized,
                "type": "PRODUCT",
                "size": _MAX_PROVIDER_ITEMS,
                "order_by": "-date",
            }
        )
        url = f"{BASE_URL}?{query}"
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
        retrieved_at = datetime.now(UTC)
        return parse_open_prices(
            self._fetch_json(request),
            barcode=normalized,
            retrieved_at=retrieved_at,
            today=retrieved_at.date(),
        )

    def _fetch_json(self, request: Request) -> Any:
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                if not is_trusted_https_url(response.geturl(), "prices.openfoodfacts.org"):
                    raise OpenPricesSourceError("Open Prices resolved to an unexpected source.")
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            if exc.code == 429:
                raise OpenPricesRateLimited(
                    "Open Prices is temporarily throttling requests."
                ) from exc
            raise OpenPricesSourceError("Open Prices request failed.") from exc
        except (URLError, HTTPException, TimeoutError, OSError) as exc:
            raise OpenPricesSourceError("Open Prices request failed.") from exc

        if len(raw) > MAX_RESPONSE_BYTES:
            raise OpenPricesSourceError("Open Prices response exceeded size limit.")
        try:
            return json.loads(raw, parse_float=Decimal)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise OpenPricesSourceError("Open Prices response is malformed JSON.") from exc
