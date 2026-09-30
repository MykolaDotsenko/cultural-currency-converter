from __future__ import annotations

import re
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from apps.countries.models import Country, CountryCurrency, Currency
from apps.culture.models import (
    TypicalPrice,
    TypicalPriceConfidence,
    TypicalPriceSourceClass,
)
from apps.culture.services import DestinationContext
from apps.exchange.budget_snapshot import build_budget_context_snapshot_token
from apps.exchange.domain import DEFAULT_SOURCE_POLICY, ConversionResult, RateQuote
from apps.exchange.money_context import MoneyContext, MoneyContextState


User = get_user_model()


class FakeGateway:
    def get(self, base, quote, policy, *, now):
        return (
            RateQuote(
                base_currency=base,
                quote_currency=quote,
                rate=Decimal("174.50"),
                requested_date=None,
                effective_date=timezone.localdate(),
                fetched_at=timezone.now(),
                provider_policy=DEFAULT_SOURCE_POLICY,
                provider_keys=("ecb",),
                historical=False,
            ),
            False,
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

    for category, label, low, high, order in (
        ("coffee", "Cup of coffee", "100", "600", 10),
        ("casual_meal", "Casual meal", "500", "1000", 20),
    ):
        TypicalPrice.objects.create(
            country=jp,
            category=category,
            label=label,
            amount_low=Decimal(low),
            amount_high=Decimal(high),
            currency=jpy,
            source_name="Sourced travel context",
            source_url=f"https://example.com/{category}",
            observed_at=timezone.localdate(),
            verified_at=timezone.now(),
            source_class=TypicalPriceSourceClass.APPROXIMATE_CONTEXTUAL,
            confidence=TypicalPriceConfidence.MEDIUM,
            display_order=order,
            is_published=True,
        )

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


def _extract_budget_token(content: bytes) -> str:
    match = re.search(rb'name="budget_context_token"\s+value="([^"]+)"', content)
    assert match is not None
    return match.group(1).decode()


def _signed_budget_context() -> str:
    quote = RateQuote(
        base_currency="EUR",
        quote_currency="JPY",
        rate=Decimal("174.50"),
        requested_date=None,
        effective_date=timezone.localdate(),
        fetched_at=timezone.now(),
        provider_policy=DEFAULT_SOURCE_POLICY,
        provider_keys=("ecb",),
        historical=False,
    )
    conversion = ConversionResult(
        input_amount=Decimal("100.00"),
        output_amount=Decimal("17450"),
        quote=quote,
        stale=False,
    )
    destination = DestinationContext(
        country_code="JP",
        country_name="Japan",
        as_of=timezone.localdate(),
        payment=None,
        prices=(),
    )
    context = MoneyContext(
        conversion=conversion,
        destination_country_code="JP",
        as_of=timezone.localdate(),
        destination_context=destination,
        destination_state=MoneyContextState.EMPTY,
    )
    return build_budget_context_snapshot_token(context)


@pytest.mark.django_db
def test_current_conversion_offers_budget_interpretation_from_sourced_anchors(
    client,
    reference_data,
):
    with patch("apps.exchange.views.build_latest_quote_gateway", return_value=FakeGateway()):
        response = client.post(reverse("converter"), _payload(), HTTP_HX_REQUEST="true")

    assert response.status_code == 200
    assert b"Put this amount against a small daily reference basket" in response.content
    assert b"Cup of coffee per person / day" in response.content
    assert b"Casual meal per person / day" in response.content
    assert b"Transit per person / day" not in response.content
    assert _extract_budget_token(response.content)
    converter_close = response.content.index(b"</form>")
    budget_heading = response.content.index(b"Budget interpretation")
    assert converter_close < budget_heading


@pytest.mark.django_db
def test_budget_interpretation_uses_signed_conversion_and_explicit_basket(
    client,
    reference_data,
):
    response = client.post(
        reverse("budget_interpretation"),
        {
            "budget_context_token": _signed_budget_context(),
            "duration_days": "10",
            "travelers": "1",
            "units_coffee": "1",
            "units_casual_meal": "2",
            "reference_amount": "999999999",
        },
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    assert b"Within this reference range" in response.content
    assert b"17450 JPY" in response.content
    assert b"1745 JPY" in response.content
    assert b"11000" in response.content
    assert b"26000" in response.content
    assert b"999999999" not in response.content
    assert b"not a full trip-cost forecast" in response.content


@pytest.mark.django_db
def test_valid_budget_interpretation_exposes_account_save_payload(
    client,
    reference_data,
):
    user = User.objects.create_user(username="owner", password="StrongPass-482!")
    client.force_login(user)

    response = client.post(
        reverse("budget_interpretation"),
        {
            "budget_context_token": _signed_budget_context(),
            "duration_days": "4",
            "travelers": "2",
            "units_coffee": "1",
            "units_casual_meal": "2",
        },
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    assert b"Save this budget scenario" in response.content
    assert b'action="/saved/scenarios/budget/create/"' in response.content
    assert b'name="duration_days" value="4"' in response.content
    assert b'name="travelers" value="2"' in response.content
    assert b'name="units_coffee" value="1"' in response.content
    assert b'name="units_casual_meal" value="2"' in response.content


@pytest.mark.django_db
def test_anonymous_budget_interpretation_keeps_save_opt_in(
    client,
    reference_data,
):
    response = client.post(
        reverse("budget_interpretation"),
        {
            "budget_context_token": _signed_budget_context(),
            "duration_days": "4",
            "travelers": "1",
            "units_coffee": "1",
        },
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    assert b"Sign in to save" in response.content
    assert b"not uploaded automatically" in response.content
    assert b'action="/saved/scenarios/budget/create/"' not in response.content


@pytest.mark.django_db
def test_budget_interpretation_rejects_tampered_context_token(client, reference_data):
    response = client.post(
        reverse("budget_interpretation"),
        {
            "budget_context_token": "tampered",
            "duration_days": "3",
            "travelers": "1",
            "units_coffee": "1",
        },
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 422
    assert b"no longer valid" in response.content


@pytest.mark.django_db
def test_budget_interpretation_requires_at_least_one_visible_reference_item(
    client,
    reference_data,
):
    response = client.post(
        reverse("budget_interpretation"),
        {
            "budget_context_token": _signed_budget_context(),
            "duration_days": "3",
            "travelers": "1",
            "units_coffee": "",
            "units_casual_meal": "",
        },
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 422
    assert b"Keep at least one daily reference item" in response.content
    assert b"Reference-basket comparison" not in response.content


@pytest.mark.django_db
def test_non_javascript_budget_interpretation_returns_full_page(client, reference_data):
    response = client.post(
        reverse("budget_interpretation"),
        {
            "budget_context_token": _signed_budget_context(),
            "duration_days": "3",
            "travelers": "1",
            "units_coffee": "1",
            "units_casual_meal": "2",
        },
    )

    assert response.status_code == 200
    assert b"<html" in response.content
    assert b"A transparent reference basket, not a guessed travel budget" in response.content
    assert b"Above this reference basket" in response.content


@pytest.mark.django_db
def test_budget_interpretation_preserves_requested_category_when_source_row_disappears(
    client,
    reference_data,
):
    with patch("apps.exchange.views.build_latest_quote_gateway", return_value=FakeGateway()):
        conversion_response = client.post(
            reverse("converter"),
            _payload(),
            HTTP_HX_REQUEST="true",
        )

    token = _extract_budget_token(conversion_response.content)
    TypicalPrice.objects.filter(category="casual_meal").delete()

    response = client.post(
        reverse("budget_interpretation"),
        {
            "budget_context_token": token,
            "duration_days": "3",
            "travelers": "1",
            "units_coffee": "1",
            "units_casual_meal": "2",
        },
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    assert b"Insufficient current data" in response.content
    assert b"Missing: Casual Meal" in response.content
    assert b"Within this reference range" not in response.content
