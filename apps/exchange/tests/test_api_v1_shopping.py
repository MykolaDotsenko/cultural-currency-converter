from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.urls import reverse

from apps.countries.models import Country, CountryCurrency, Currency
from apps.exchange.api_quota import ConversionQuota, ConversionQuotaUnavailable
from apps.exchange.domain import DEFAULT_SOURCE_POLICY, RateQuote
from apps.exchange.providers.base import FxProviderInvalidPayload, FxProviderUnavailable


class ShoppingGateway:
    def __init__(self, *, stale: bool = False):
        self.calls: list[tuple[object, ...]] = []
        self.stale = stale

    def get(self, base, quote, policy, *, now):
        self.calls.append((base, quote, policy, now))
        return (
            RateQuote(
                base_currency=base,
                quote_currency=quote,
                rate=Decimal("0.90"),
                requested_date=None,
                effective_date=date(2026, 10, 1),
                fetched_at=datetime(2026, 10, 2, 8, tzinfo=UTC),
                provider_policy=DEFAULT_SOURCE_POLICY,
                provider_keys=("ecb",),
                historical=False,
            ),
            self.stale,
        )


class BrokenGateway:
    def __init__(self, exc):
        self.exc = exc

    def get(self, *_args, **_kwargs):
        raise self.exc


@pytest.fixture
def shopping_reference_data(db):
    us = Country.objects.create(iso2="US", iso3="USA", name="United States")
    fi = Country.objects.create(iso2="FI", iso3="FIN", name="Finland")
    usd = Currency.objects.create(code="USD", name="US Dollar", symbol="$", minor_units=2)
    eur = Currency.objects.create(code="EUR", name="Euro", symbol="€", minor_units=2)
    CountryCurrency.objects.create(country=us, currency=usd, is_primary=True, source="test")
    CountryCurrency.objects.create(country=fi, currency=eur, is_primary=True, source="test")


def _payload(**overrides):
    result = {
        "purchaseCountry": "US",
        "purchaseCurrency": "USD",
        "homeCurrency": "EUR",
        "itemPrice": "100.00",
        "shipping": "20.00",
        "knownFees": "10.00",
        "fxMarkupPercent": "2.50",
    }
    result.update(overrides)
    return result


def _post(client, payload):
    return client.post(
        reverse("api_v1_shopping_estimate"),
        data=json.dumps(payload),
        content_type="application/json",
    )


@pytest.mark.django_db
def test_shopping_api_reuses_canonical_domain_and_exposes_decimal_source_truth(
    client, shopping_reference_data
):
    gateway = ShoppingGateway(stale=True)
    with patch(
        "apps.exchange.api_v1_shopping.build_latest_quote_gateway",
        return_value=gateway,
    ):
        response = _post(client, _payload())

    assert response.status_code == 200
    assert response["X-API-Version"] == "1"
    assert response["Cache-Control"] == "private, no-store"
    data = response.json()["data"]
    assert data["purchaseCountry"] == "US"
    assert data["purchaseCurrency"] == "USD"
    assert data["homeCurrency"] == "EUR"
    assert data["assumptions"] == {
        "itemPrice": "100.00",
        "shipping": "20.00",
        "knownFees": "10.00",
        "fxMarkupPercent": "2.50",
    }
    assert data["purchaseTotal"] == "130.00"
    assert data["referenceHomeCost"] == "117.00"
    assert data["estimatedHomeCost"] == "119.92"
    assert data["fxMarkupCost"] == "2.92"
    assert set(data["unknownCosts"]) == {
        "duties not explicitly entered",
        "taxes not explicitly entered",
        "issuer or merchant fees not explicitly entered",
    }
    assert data["conversion"]["rate"] == "0.90"
    assert data["conversion"]["providerKeys"] == ["ecb"]
    assert data["conversion"]["effectiveDate"] == "2026-10-01"
    assert data["conversion"]["fetchedAt"] == "2026-10-02T08:00:00+00:00"
    assert data["conversion"]["stale"] is True
    assert gateway.calls and gateway.calls[0][:2] == ("USD", "EUR")


@pytest.mark.django_db
def test_shopping_api_matches_existing_web_shopping_costs(client, shopping_reference_data):
    gateway = ShoppingGateway()
    with (
        patch("apps.exchange.views.build_latest_quote_gateway", return_value=gateway),
        patch("apps.exchange.api_v1_shopping.build_latest_quote_gateway", return_value=gateway),
    ):
        web = client.post(
            reverse("shopping_calculation"),
            {
                "purchase_country": "US",
                "purchase_currency": "USD",
                "home_currency": "EUR",
                "item_price": "100.00",
                "shipping": "20.00",
                "known_fees": "10.00",
                "fx_markup_percent": "2.50",
            },
        )
        api = _post(client, _payload())

    assert web.status_code == api.status_code == 200
    assert b"119.92" in web.content
    assert api.json()["data"]["estimatedHomeCost"] == "119.92"
    assert len(gateway.calls) == 2


@pytest.mark.django_db
def test_shopping_api_validates_currency_and_precision_before_provider(
    client, shopping_reference_data
):
    with patch("apps.exchange.api_v1_shopping.build_latest_quote_gateway") as factory:
        invalid = _post(client, _payload(itemPrice="100.001"))
        mismatched = _post(client, _payload(purchaseCurrency="EUR"))
        same = _post(client, _payload(homeCurrency="USD"))
        oversized = _post(client, _payload(itemPrice="999999999999"))

    assert all(response.status_code == 422 for response in (invalid, mismatched, same, oversized))
    assert "item_price" in invalid.json()["error"]["fields"]
    assert "purchase_currency" in mismatched.json()["error"]["fields"]
    assert "home_currency" in same.json()["error"]["fields"]
    factory.assert_not_called()


@pytest.mark.django_db
def test_shopping_api_rejects_bad_types_unknown_fields_and_oversized_body(
    client, shopping_reference_data
):
    numeric = _post(client, _payload(itemPrice=100))
    unknown = _post(client, {**_payload(), "estimatedHomeCost": "1"})
    large = _post(client, {**_payload(), "padding": "x" * (17 * 1024)})
    assert numeric.status_code == 400
    assert numeric.json()["error"]["code"] == "invalid_request"
    assert unknown.status_code == 400
    assert unknown.json()["error"]["code"] == "unknown_fields"
    assert large.status_code == 413
    assert large.json()["error"]["code"] == "payload_too_large"


@pytest.mark.django_db
def test_shopping_api_defaults_only_optional_assumptions(client, shopping_reference_data):
    gateway = ShoppingGateway()
    with patch("apps.exchange.api_v1_shopping.build_latest_quote_gateway", return_value=gateway):
        response = _post(
            client,
            {"purchaseCurrency": "USD", "homeCurrency": "EUR", "itemPrice": "5.00"},
        )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["purchaseCountry"] is None
    assert data["purchaseTotal"] == "5.00"
    assert data["assumptions"]["fxMarkupPercent"] == "0"
    assert data["assumptions"]["knownFees"] == "0"
    assert data["assumptions"]["shipping"] == "0"


@pytest.mark.django_db
def test_shopping_api_guards_fx_work_before_gateway(client, shopping_reference_data):
    with (
        patch(
            "apps.exchange.api_v1.consume_conversion_quota",
            return_value=ConversionQuota(allowed=False, retry_after=19),
        ),
        patch("apps.exchange.api_v1_shopping.build_latest_quote_gateway") as factory,
    ):
        response = _post(client, _payload())
    assert response.status_code == 429
    assert response["Retry-After"] == "19"
    assert response.json()["error"]["code"] == "rate_limited"
    factory.assert_not_called()

    with (
        patch(
            "apps.exchange.api_v1.consume_conversion_quota",
            side_effect=ConversionQuotaUnavailable,
        ),
        patch("apps.exchange.api_v1_shopping.build_latest_quote_gateway") as factory,
    ):
        unavailable = _post(client, _payload())
    assert unavailable.status_code == 503
    assert unavailable.json()["error"]["code"] == "quota_unavailable"
    factory.assert_not_called()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("failure", "expected_status", "code"),
    [
        (FxProviderUnavailable("sensitive downstream detail"), 503, "provider_unavailable"),
        (FxProviderInvalidPayload("sensitive downstream detail"), 502, "provider_invalid_payload"),
    ],
)
def test_shopping_api_maps_provider_errors_safely(
    client, shopping_reference_data, failure, expected_status, code
):
    with patch(
        "apps.exchange.api_v1_shopping.build_latest_quote_gateway",
        return_value=BrokenGateway(failure),
    ):
        response = _post(client, _payload())
    assert response.status_code == expected_status
    assert response.json()["error"]["code"] == code
    assert b"sensitive downstream detail" not in response.content


@pytest.mark.django_db
def test_shopping_api_rejects_non_json_content_type(client, shopping_reference_data):
    response = client.post(
        reverse("api_v1_shopping_estimate"), data="itemPrice=100", content_type="text/plain"
    )
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_media_type"
