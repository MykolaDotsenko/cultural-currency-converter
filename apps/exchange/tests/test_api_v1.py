from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.urls import reverse

from apps.countries.models import City, Country, CountryCurrency, Currency
from apps.exchange.api_quota import ConversionQuota, ConversionQuotaUnavailable
from apps.exchange.domain import DEFAULT_SOURCE_POLICY, ObservationGranularity, RateQuote
from apps.exchange.providers.base import FxProviderUnavailable


class FakeLatestGateway:
    def __init__(self, *, stale: bool = False):
        self.stale = stale
        self.calls: list[tuple[object, ...]] = []

    def get(self, base, quote, policy, *, now):
        self.calls.append((base, quote, policy, now))
        return (
            RateQuote(
                base_currency=base,
                quote_currency=quote,
                rate=Decimal("174.50"),
                requested_date=None,
                effective_date=date(2026, 9, 18),
                fetched_at=datetime(2026, 9, 20, 8, tzinfo=UTC),
                provider_policy=DEFAULT_SOURCE_POLICY,
                provider_keys=("ecb",),
                historical=False,
            ),
            self.stale,
        )


class FakeHistoricalGateway:
    def __init__(self):
        self.calls: list[tuple[object, ...]] = []

    def get(self, base, quote, requested_date, policy):
        self.calls.append((base, quote, requested_date, policy))
        return RateQuote(
            base_currency=base,
            quote_currency=quote,
            rate=Decimal("170.25"),
            requested_date=requested_date,
            effective_date=requested_date,
            fetched_at=datetime(2026, 9, 20, 8, tzinfo=UTC),
            provider_policy=DEFAULT_SOURCE_POLICY,
            provider_keys=("ecb",),
            historical=True,
            observation_granularity=ObservationGranularity.DAILY,
        )


class UnavailableGateway:
    def get(self, *args, **kwargs):
        raise FxProviderUnavailable("down")


@pytest.fixture
def api_reference_data(db):
    finland = Country.objects.create(
        iso2="FI",
        iso3="FIN",
        name="Finland",
        region="Europe",
        subregion="Northern Europe",
    )
    japan = Country.objects.create(
        iso2="JP",
        iso3="JPN",
        name="Japan",
        region="Asia",
        subregion="Eastern Asia",
    )
    eur = Currency.objects.create(code="EUR", name="Euro", symbol="€", minor_units=2)
    jpy = Currency.objects.create(code="JPY", name="Japanese yen", symbol="¥", minor_units=0)
    CountryCurrency.objects.create(
        country=finland,
        currency=eur,
        is_primary=True,
        source="test",
    )
    CountryCurrency.objects.create(
        country=japan,
        currency=jpy,
        is_primary=True,
        source="test",
    )
    tokyo = City.objects.create(
        country=japan,
        slug="tokyo",
        name="Tokyo",
        region="Kanto",
    )
    return finland, japan, eur, jpy, tokyo


def _latest_payload(**overrides):
    payload = {
        "amount": "100.00",
        "sourceCountry": "FI",
        "sourceCurrency": "EUR",
        "destinationCountry": "JP",
        "destinationCurrency": "JPY",
        "destinationCitySlug": "tokyo",
        "rateMode": "latest",
    }
    payload.update(overrides)
    return payload


def _post_json(client, payload):
    return client.post(
        reverse("api_v1_conversion"),
        data=json.dumps(payload),
        content_type="application/json",
    )


def test_api_v1_root_is_versioned_and_public(client):
    response = client.get(reverse("api_v1_root"))

    assert response.status_code == 200
    assert response["X-API-Version"] == "1"
    assert response["Cache-Control"] == "public, max-age=300"
    assert response.json() == {
        "schemaVersion": "1",
        "data": {
            "apiVersion": "1",
            "capabilities": [
                "reference_metadata",
                "canonical_conversion",
                "money_context",
                "historical_conversion",
                "shopping_estimate",
            ],
            "accountMutationApi": False,
        },
    }


@pytest.mark.django_db
def test_reference_api_exposes_active_currency_and_destination_identity(
    client,
    api_reference_data,
):
    response = client.get(reverse("api_v1_reference"))

    assert response.status_code == 200
    assert response["X-API-Version"] == "1"
    assert response["Cache-Control"] == "public, max-age=300"
    payload = response.json()
    assert payload["schemaVersion"] == "1"
    assert payload["data"]["currencies"] == [
        {"code": "EUR", "name": "Euro", "symbol": "€", "minorUnits": 2},
        {"code": "JPY", "name": "Japanese yen", "symbol": "¥", "minorUnits": 0},
    ]
    assert payload["data"]["destinations"][1] == {
        "countryCode": "JP",
        "countryName": "Japan",
        "region": "Asia",
        "subregion": "Eastern Asia",
        "currencyCode": "JPY",
        "cities": [{"slug": "tokyo", "name": "Tokyo", "region": "Kanto"}],
    }


@pytest.mark.django_db
def test_conversion_api_reuses_canonical_application_path_and_preserves_trust_fields(
    client,
    api_reference_data,
):
    gateway = FakeLatestGateway(stale=True)
    with patch("apps.exchange.api_v1.build_latest_quote_gateway", return_value=gateway):
        response = _post_json(client, _latest_payload())

    assert response.status_code == 200
    assert response["Cache-Control"] == "private, no-store"
    assert response["X-API-Version"] == "1"
    body = response.json()
    conversion = body["data"]["conversion"]
    assert conversion == {
        "inputAmount": "100.00",
        "outputAmount": "17450",
        "baseCurrency": "EUR",
        "quoteCurrency": "JPY",
        "rate": "174.50",
        "requestedDate": None,
        "effectiveDate": "2026-09-18",
        "fetchedAt": "2026-09-20T08:00:00+00:00",
        "historical": False,
        "observationGranularity": "daily",
        "providerKeys": ["ecb"],
        "stale": True,
        "exact": False,
    }
    money_context = body["data"]["moneyContext"]
    assert money_context["state"] == "empty"
    assert money_context["countryCode"] == "JP"
    assert money_context["citySlug"] == "tokyo"
    assert money_context["destination"] == {
        "countryCode": "JP",
        "countryName": "Japan",
        "citySlug": "tokyo",
        "cityName": "Tokyo",
        "asOf": money_context["asOf"],
        "prices": [],
        "economic": None,
        "calendar": None,
        "payment": None,
    }
    assert gateway.calls and gateway.calls[0][0:2] == ("EUR", "JPY")


@pytest.mark.django_db
def test_historical_api_preserves_requested_and_effective_date_semantics(
    client,
    api_reference_data,
):
    gateway = FakeHistoricalGateway()
    with patch("apps.exchange.api_v1.build_historical_quote_gateway", return_value=gateway):
        response = _post_json(
            client,
            _latest_payload(
                destinationCitySlug="",
                rateMode="historical",
                requestedDate="2025-01-15",
            ),
        )

    assert response.status_code == 200
    conversion = response.json()["data"]["conversion"]
    assert conversion["historical"] is True
    assert conversion["requestedDate"] == "2025-01-15"
    assert conversion["effectiveDate"] == "2025-01-15"
    assert conversion["rate"] == "170.25"
    assert conversion["providerKeys"] == ["ecb"]
    assert response.json()["data"]["moneyContext"]["state"] == "not_applicable"
    assert gateway.calls[0][2] == date(2025, 1, 15)


@pytest.mark.django_db
def test_same_currency_api_is_provider_free(client, api_reference_data):
    gateway = FakeLatestGateway()
    with patch("apps.exchange.api_v1.build_latest_quote_gateway", return_value=gateway):
        response = _post_json(
            client,
            {
                "amount": "12.34",
                "sourceCurrency": "EUR",
                "destinationCurrency": "EUR",
                "rateMode": "latest",
            },
        )

    assert response.status_code == 200
    assert gateway.calls == []
    conversion = response.json()["data"]["conversion"]
    assert conversion["outputAmount"] == "12.34"
    assert conversion["rate"] == "1"
    assert conversion["providerKeys"] == []
    assert conversion["exact"] is True


@pytest.mark.django_db
def test_api_rejects_non_string_decimal_unknown_fields_and_bad_content_type(
    client,
    api_reference_data,
):
    numeric = _post_json(client, _latest_payload(amount=100))
    unknown = _post_json(client, {**_latest_payload(), "winner": True})
    wrong_type = client.post(
        reverse("api_v1_conversion"),
        data="amount=100",
        content_type="text/plain",
    )

    assert numeric.status_code == 400
    assert numeric.json()["error"]["code"] == "invalid_request"
    assert unknown.status_code == 400
    assert unknown.json()["error"] == {
        "code": "unknown_fields",
        "message": "Request contains unsupported fields.",
        "details": {"fields": ["winner"]},
    }
    assert wrong_type.status_code == 415
    assert wrong_type.json()["error"]["code"] == "unsupported_media_type"


@pytest.mark.django_db
def test_api_maps_validation_and_provider_failure_without_leaking_provider_details(
    client,
    api_reference_data,
):
    invalid = _post_json(client, _latest_payload(sourceCurrency="USD"))

    with patch(
        "apps.exchange.api_v1.build_latest_quote_gateway",
        return_value=UnavailableGateway(),
    ):
        unavailable = _post_json(client, _latest_payload())

    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "validation_error"
    assert "source_currency" in invalid.json()["error"]["fields"]

    assert unavailable.status_code == 503
    assert unavailable.json()["error"] == {
        "code": "provider_unavailable",
        "message": "Reference rates are temporarily unavailable.",
    }
    assert "down" not in unavailable.content.decode("utf-8")


@pytest.mark.django_db
def test_api_payload_size_is_bounded(client, api_reference_data):
    response = client.post(
        reverse("api_v1_conversion"),
        data=json.dumps({"amount": "1", "padding": "x" * (17 * 1024)}),
        content_type="application/json",
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


@pytest.mark.django_db
def test_provider_backed_api_conversion_rejects_exhausted_quota_before_fx(
    client,
    api_reference_data,
):
    with (
        patch(
            "apps.exchange.api_v1.consume_conversion_quota",
            return_value=ConversionQuota(allowed=False, retry_after=27),
        ),
        patch("apps.exchange.api_v1.run_converter_submission") as submit,
    ):
        response = _post_json(client, _latest_payload())

    assert response.status_code == 429
    assert response["Retry-After"] == "27"
    assert response["Cache-Control"] == "private, no-store"
    assert response.json()["error"]["code"] == "rate_limited"
    submit.assert_not_called()


@pytest.mark.django_db
def test_provider_backed_api_conversion_fails_closed_when_shared_quota_fails(
    client,
    api_reference_data,
):
    with (
        patch(
            "apps.exchange.api_v1.consume_conversion_quota",
            side_effect=ConversionQuotaUnavailable(),
        ),
        patch("apps.exchange.api_v1.run_converter_submission") as submit,
    ):
        response = _post_json(client, _latest_payload())

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "quota_unavailable"
    submit.assert_not_called()


@pytest.mark.django_db
def test_exact_same_currency_api_does_not_consume_upstream_quota(
    client,
    api_reference_data,
):
    with patch("apps.exchange.api_v1.consume_conversion_quota") as quota:
        response = _post_json(
            client,
            {"amount": "12.34", "sourceCurrency": "EUR", "destinationCurrency": "EUR"},
        )

    assert response.status_code == 200
    assert response.json()["data"]["conversion"]["exact"] is True
    quota.assert_not_called()
