from __future__ import annotations

import re
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.urls import reverse

from apps.countries.models import Country, CountryCurrency, Currency
from apps.exchange.snapshot_tokens import build_conversion_snapshot_token
from apps.exchange.domain import DEFAULT_SOURCE_POLICY, ConversionResult, RateQuote


class FakeGateway:
    def get(self, base, quote, policy, *, now):
        return (
            RateQuote(
                base_currency=base,
                quote_currency=quote,
                rate=Decimal("174.50"),
                requested_date=None,
                effective_date=date(2026, 9, 18),
                fetched_at=datetime(2026, 9, 21, 8, tzinfo=UTC),
                provider_policy=DEFAULT_SOURCE_POLICY,
                provider_keys=("ecb",),
                historical=False,
            ),
            False,
        )


class FakeHistoricalGateway:
    def get(self, base, quote, requested_date, policy):
        return RateQuote(
            base_currency=base,
            quote_currency=quote,
            rate=Decimal("170.00"),
            requested_date=requested_date,
            effective_date=requested_date,
            fetched_at=datetime(2026, 9, 21, 8, tzinfo=UTC),
            provider_policy=DEFAULT_SOURCE_POLICY,
            provider_keys=("ecb",),
            historical=True,
        )


@pytest.fixture(autouse=True)
def use_vite_dev_mode(settings):
    settings.VITE_DEV_SERVER_ENABLED = True


@pytest.fixture
def reference_data(db):
    fi = Country.objects.create(iso2="FI", iso3="FIN", name="Finland")
    jp = Country.objects.create(iso2="JP", iso3="JPN", name="Japan")
    eur = Currency.objects.create(code="EUR", name="Euro", symbol="€", minor_units=2)
    jpy = Currency.objects.create(code="JPY", name="Japanese yen", symbol="¥", minor_units=0)
    CountryCurrency.objects.create(country=fi, currency=eur, is_primary=True, source="test")
    CountryCurrency.objects.create(country=jp, currency=jpy, is_primary=True, source="test")
    return fi, jp, eur, jpy


def _payload(**overrides):
    values = {
        "amount": "100.00",
        "source_country": "FI",
        "source_currency": "EUR",
        "destination_country": "JP",
        "destination_currency": "JPY",
    }
    values.update(overrides)
    return values


def _extract_payment_token(content: bytes) -> str:
    match = re.search(rb'name="payment_estimate_token"\s+value="([^"]+)"', content)
    assert match is not None
    return match.group(1).decode()


def _signed_snapshot() -> str:
    quote = RateQuote(
        base_currency="EUR",
        quote_currency="JPY",
        rate=Decimal("174.50"),
        requested_date=None,
        effective_date=date(2026, 9, 18),
        fetched_at=datetime(2026, 9, 21, 8, tzinfo=UTC),
        provider_policy=DEFAULT_SOURCE_POLICY,
        provider_keys=("ecb",),
        historical=False,
    )
    return build_conversion_snapshot_token(
        ConversionResult(
            input_amount=Decimal("100.00"),
            output_amount=Decimal("17450"),
            quote=quote,
            stale=False,
        )
    )


@pytest.mark.django_db
def test_current_conversion_offers_payment_estimate_without_ai_dependency(client, reference_data):
    with patch("apps.exchange.views.build_latest_quote_gateway", return_value=FakeGateway()):
        response = client.post(reverse("converter"), _payload(), HTTP_HX_REQUEST="true")

    assert response.status_code == 200
    assert b"Estimate what explicit fees may change" in response.content
    token = _extract_payment_token(response.content)
    assert token
    converter_close = response.content.index(b"</form>")
    payment_heading = response.content.index(b"Payment estimate")
    assert converter_close < payment_heading


@pytest.mark.django_db
def test_payment_estimate_uses_signed_reference_and_only_explicit_assumptions(
    client, reference_data
):
    response = client.post(
        reverse("payment_estimate"),
        {
            "payment_estimate_token": _signed_snapshot(),
            "fx_markup_percent": "2.00",
            "source_fixed_fee": "1.00",
            "destination_fixed_fee": "220",
            "reference_amount": "999999999",
        },
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    assert b"16717" in response.content
    assert b"733 JPY" in response.content
    assert b"17450 JPY" in response.content
    assert b"999999999" not in response.content
    assert b"not a bank/card/ATM quote" in response.content


@pytest.mark.django_db
def test_payment_estimate_rejects_tampered_token_before_calculation(client, reference_data):
    response = client.post(
        reverse("payment_estimate"),
        {
            "payment_estimate_token": "tampered",
            "fx_markup_percent": "2",
            "source_fixed_fee": "1",
            "destination_fixed_fee": "0",
        },
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 422
    assert b"no longer valid" in response.content


@pytest.mark.django_db
def test_invalid_assumptions_return_bound_form_without_estimate(client, reference_data):
    response = client.post(
        reverse("payment_estimate"),
        {
            "payment_estimate_token": _signed_snapshot(),
            "fx_markup_percent": "26",
            "source_fixed_fee": "1.0001",
            "destination_fixed_fee": "0",
        },
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 422
    assert b"Ensure this value is less than or equal to 25" in response.content
    assert b"at most 2 decimal places" in response.content
    assert b"Estimated destination value" not in response.content


@pytest.mark.django_db
def test_historical_conversion_does_not_offer_current_payment_estimate(client, reference_data):
    with patch(
        "apps.exchange.views.build_historical_quote_gateway",
        return_value=FakeHistoricalGateway(),
    ):
        response = client.get(
            reverse("converter"),
            {
                "convert": "1",
                "amount": "100.00",
                "source_country": "FI",
                "source_currency": "EUR",
                "destination_country": "JP",
                "destination_currency": "JPY",
                "rate_mode": "historical",
                "requested_date": "2026-09-18",
            },
        )

    assert response.status_code == 200
    assert b"Historical reference" in response.content
    assert b"Estimate what explicit fees may change" not in response.content


@pytest.mark.django_db
def test_same_currency_result_does_not_offer_fx_payment_estimate(client, reference_data):
    response = client.post(
        reverse("converter"),
        _payload(destination_country="FI", destination_currency="EUR"),
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    assert b"Estimate what explicit fees may change" not in response.content


@pytest.mark.django_db
def test_non_javascript_payment_estimate_returns_full_page(client, reference_data):
    response = client.post(
        reverse("payment_estimate"),
        {
            "payment_estimate_token": _signed_snapshot(),
            "fx_markup_percent": "0",
            "source_fixed_fee": "0",
            "destination_fixed_fee": "0",
        },
    )

    assert response.status_code == 200
    assert b"<html" in response.content
    assert b"Reference value, with your assumptions" in response.content
    assert b"17450 JPY" in response.content


@pytest.mark.django_db
def test_payment_estimate_endpoint_is_post_only(client, reference_data):
    response = client.get(reverse("payment_estimate"))

    assert response.status_code == 405
