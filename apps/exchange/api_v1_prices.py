"""Read-only public API v1 adapter for historical Open Prices observations."""

from __future__ import annotations

from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET

from apps.exchange.api_v1 import _api_error, _api_response, _provider_quota_error
from apps.exchange.open_prices_context import lookup_public_price_observations
from integrations.price_data import OpenPricesRateLimited, OpenPricesSourceError
from integrations.product_data import canonical_open_food_facts_barcode


@require_GET
def api_v1_public_price_observations(request: HttpRequest, barcode: str) -> JsonResponse:
    """Return dated, bounded evidence: never a live price or financial input."""
    try:
        normalized = canonical_open_food_facts_barcode(barcode)
    except ValueError:
        return _api_error(
            code="invalid_barcode",
            message="Barcode must contain 7–14 digits and cannot be all zeroes.",
            status=400,
        )

    # All mobile GET requests (including cache hits) consume the existing
    # per-peer API budget; the provider service caps upstream calls separately.
    quota_error = _provider_quota_error(request)
    if quota_error is not None:
        return quota_error

    try:
        observations = lookup_public_price_observations(normalized)
    except OpenPricesRateLimited:
        return _api_error(
            code="price_lookup_busy",
            message="Community price lookup is temporarily busy.",
            status=429,
        )
    except OpenPricesSourceError:
        return _api_error(
            code="price_source_unavailable",
            message="Community price observations are temporarily unavailable.",
            status=503,
        )

    return _api_response(
        {
            "schemaVersion": "1",
            "data": {
                "barcode": normalized,
                "evidenceType": "historical_community_unit_price_observations",
                "livePrice": None,
                "source": {
                    "name": "Open Prices",
                    "url": "https://prices.openfoodfacts.org/",
                    "databaseLicense": "Open Database License (ODbL)",
                },
                "sampling": {
                    "bounded": True,
                    "providerPageSize": 20,
                    "maxObservations": 5,
                    "maxObservationAgeDays": 365,
                    "representsMarketAverage": False,
                },
                "observations": [
                    {
                        "productBarcode": item.product_code,
                        "amount": format(item.amount, "f"),
                        "currency": item.currency,
                        "unit": "UNIT",
                        "observedAt": item.observed_at.isoformat(),
                        "countryCode": item.country_code,
                        "locationLabel": item.location_label,
                        "discounted": item.discounted,
                        "proofId": item.proof_id,
                        "recordUrl": item.source_url,
                        "retrievedAt": item.retrieved_at.isoformat(),
                    }
                    for item in observations
                ],
            },
        }
    )
