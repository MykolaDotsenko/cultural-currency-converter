"""Mobile Open Prices contracts must never become canonical Shopping prices."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.urls import reverse

from apps.exchange.api_v1 import _api_error
from integrations.price_data import (
    OpenPricesRateLimited,
    OpenPricesSourceError,
    PublicPriceObservation,
)


def _observation(
    *,
    amount: str = "3.9500",
    code: str = "0034000470693",
) -> PublicPriceObservation:
    return PublicPriceObservation(
        product_code=code,
        amount=Decimal(amount),
        currency="EUR",
        observed_at=date(2026, 9, 15),
        country_code="FI",
        location_label="Example Market Helsinki",
        discounted=False,
        proof_id=48,
        source_url="https://prices.openfoodfacts.org/api/v1/prices/18",
        retrieved_at=datetime(2026, 10, 8, 12, tzinfo=UTC),
    )


@pytest.fixture
def price_url():
    return reverse(
        "api_v1_public_price_observations",
        kwargs={"barcode": "034000470693"},
    )


@pytest.mark.django_db
def test_public_prices_api_has_lossless_decimal_and_explicit_provenance(
    client, price_url
):
    with (
        patch("apps.exchange.api_v1_prices._provider_quota_error", return_value=None) as quota,
        patch(
            "apps.exchange.api_v1_prices.lookup_public_price_observations",
            return_value=(_observation(),),
        ) as lookup,
        patch("apps.exchange.api_v1_prices.lookup_product_identity_cached", create=True) as identity,
        patch("apps.exchange.api_v1_shopping.build_latest_quote_gateway") as fx,
    ):
        response = client.get(price_url)

    assert response.status_code == 200
    assert response["X-API-Version"] == "1"
    assert response["Cache-Control"] == "private, no-store"
    assert response["X-Content-Type-Options"] == "nosniff"
    data = response.json()
    assert data["schemaVersion"] == "1"
    assert data["data"]["barcode"] == "0034000470693"
    assert data["data"]["evidenceType"] == "historical_community_unit_price_observations"
    assert data["data"]["livePrice"] is None
    assert data["data"]["source"]["databaseLicense"] == "Open Database License (ODbL)"
    assert data["data"]["sampling"] == {
        "bounded": True,
        "providerPageSize": 20,
        "maxObservations": 5,
        "maxObservationAgeDays": 365,
        "representsMarketAverage": False,
    }
    assert data["data"]["observations"] == [
        {
            "productBarcode": "0034000470693",
            "amount": "3.9500",
            "currency": "EUR",
            "unit": "UNIT",
            "observedAt": "2026-09-15",
            "countryCode": "FI",
            "locationLabel": "Example Market Helsinki",
            "discounted": False,
            "proofId": 48,
            "recordUrl": "https://prices.openfoodfacts.org/api/v1/prices/18",
            "retrievedAt": "2026-10-08T12:00:00+00:00",
        }
    ]
    quota.assert_called_once()
    lookup.assert_called_once_with("0034000470693")
    identity.assert_not_called()
    fx.assert_not_called()


@pytest.mark.django_db
@pytest.mark.parametrize("barcode", ["bad-barcode", "00000000", "123", "123456789012345"])
def test_invalid_barcode_is_rejected_before_quota_or_upstream(client, barcode):
    with (
        patch("apps.exchange.api_v1_prices._provider_quota_error") as quota,
        patch("apps.exchange.api_v1_prices.lookup_public_price_observations") as lookup,
    ):
        response = client.get(
            reverse("api_v1_public_price_observations", kwargs={"barcode": barcode})
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_barcode"
    assert response["Cache-Control"] == "private, no-store"
    quota.assert_not_called()
    lookup.assert_not_called()


@pytest.mark.django_db
def test_public_prices_api_rejects_post_without_looking_up_anything(client, price_url):
    with patch("apps.exchange.api_v1_prices.lookup_public_price_observations") as lookup:
        response = client.post(price_url, data={})

    assert response.status_code == 405
    lookup.assert_not_called()


@pytest.mark.django_db
def test_empty_bounded_sample_does_not_imply_market_price_absence(client, price_url):
    with (
        patch("apps.exchange.api_v1_prices._provider_quota_error", return_value=None),
        patch("apps.exchange.api_v1_prices.lookup_public_price_observations", return_value=()),
    ):
        response = client.get(price_url)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["observations"] == []
    assert data["sampling"]["bounded"] is True
    assert data["livePrice"] is None


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("failure", "status", "code"),
    [
        (OpenPricesRateLimited("private upstream detail"), 429, "price_lookup_busy"),
        (OpenPricesSourceError("private upstream detail"), 503, "price_source_unavailable"),
    ],
)
def test_public_prices_api_maps_provider_failure_without_leaking_secrets(
    client, price_url, failure, status, code
):
    with (
        patch("apps.exchange.api_v1_prices._provider_quota_error", return_value=None),
        patch(
            "apps.exchange.api_v1_prices.lookup_public_price_observations",
            side_effect=failure,
        ),
    ):
        response = client.get(price_url)

    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert response["Cache-Control"] == "private, no-store"
    assert b"private upstream detail" not in response.content


@pytest.mark.django_db
def test_per_peer_quota_blocks_even_cached_public_observations_before_lookup(
    client, price_url
):
    quota_error = _api_error(
        code="rate_limited",
        message="Too many conversions. Please retry shortly.",
        status=429,
    )
    quota_error["Retry-After"] = "33"

    with (
        patch("apps.exchange.api_v1_prices._provider_quota_error", return_value=quota_error),
        patch("apps.exchange.api_v1_prices.lookup_public_price_observations") as lookup,
    ):
        response = client.get(price_url)

    assert response.status_code == 429
    assert response["Retry-After"] == "33"
    assert response.json()["error"]["code"] == "rate_limited"
    lookup.assert_not_called()


@pytest.mark.django_db
def test_api_root_advertises_community_evidence_without_provider_lookup(client):
    with patch("apps.exchange.api_v1_prices.lookup_public_price_observations") as lookup:
        response = client.get(reverse("api_v1_root"))

    assert response.status_code == 200
    assert "community_price_observations" in response.json()["data"]["capabilities"]
    lookup.assert_not_called()
