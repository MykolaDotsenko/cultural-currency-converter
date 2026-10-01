from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.countries.models import City, Country, CountryCurrency, Currency
from apps.culture.models import CulturalProfile, TypicalPrice
from apps.exchange.domain import DEFAULT_SOURCE_POLICY, RateQuote
from apps.exchange.providers.base import FxProviderUnavailable


@pytest.fixture(autouse=True)
def use_vite_dev_mode(settings):
    settings.VITE_DEV_SERVER_ENABLED = True


class ComparisonGateway:
    def __init__(self, *, fail_quote: str = "") -> None:
        self.calls: list[tuple[str, str]] = []
        self.fail_quote = fail_quote

    def get(self, base, quote, policy, *, now):
        self.calls.append((base, quote))
        if quote == self.fail_quote:
            raise FxProviderUnavailable("upstream comparison test failure")

        rates = {
            "JPY": Decimal("174.50"),
            "NOK": Decimal("11.80"),
            "EUR": Decimal("1"),
        }
        return (
            RateQuote(
                base_currency=base,
                quote_currency=quote,
                rate=rates[quote],
                requested_date=None,
                effective_date=timezone.localdate(),
                fetched_at=now,
                provider_policy=DEFAULT_SOURCE_POLICY,
                provider_keys=("ecb",),
                historical=False,
            ),
            False,
        )


@pytest.fixture
def comparison_reference_data(db):
    fi = Country.objects.create(iso2="FI", iso3="FIN", name="Finland")
    jp = Country.objects.create(iso2="JP", iso3="JPN", name="Japan")
    no = Country.objects.create(iso2="NO", iso3="NOR", name="Norway")

    eur = Currency.objects.create(code="EUR", name="Euro", symbol="€", minor_units=2)
    jpy = Currency.objects.create(code="JPY", name="Japanese yen", symbol="¥", minor_units=0)
    nok = Currency.objects.create(code="NOK", name="Norwegian krone", symbol="kr", minor_units=2)

    for country, currency in ((fi, eur), (jp, jpy), (no, nok)):
        CountryCurrency.objects.create(
            country=country,
            currency=currency,
            is_primary=True,
            source="test",
        )

    tokyo = City.objects.create(country=jp, slug="tokyo", name="Tokyo")
    verified_at = timezone.now()
    observed_at = timezone.localdate() - timezone.timedelta(days=5)

    for country, summary in (
        (jp, "Cards are common in Tokyo; keep some cash for smaller situations."),
        (no, "Cards are widely used in Norway."),
    ):
        CulturalProfile.objects.create(
            country=country,
            summary=summary,
            cash_usage="Carry cash only when the local situation calls for it.",
            dcc_warning="If DCC is offered, review the local-currency option carefully.",
            source_name="Official payment source",
            source_url="https://example.com/payment-context",
            verified_at=verified_at,
            is_published=True,
        )

    japan_prices = (
        ("coffee", "Coffee", Decimal("500"), Decimal("700")),
        ("casual_meal", "Casual meal", Decimal("1200"), Decimal("1800")),
        ("transit", "Local transit", Decimal("180"), Decimal("300")),
    )
    norway_prices = (
        ("coffee", "Coffee", Decimal("45"), Decimal("65")),
        ("casual_meal", "Casual meal", Decimal("180"), Decimal("280")),
        ("transit", "Local transit", Decimal("40"), Decimal("60")),
    )

    for order, (category, label, low, high) in enumerate(japan_prices, start=1):
        TypicalPrice.objects.create(
            country=jp,
            city_ref=tokyo,
            category=category,
            label=label,
            amount_low=low,
            amount_high=high,
            currency=jpy,
            source_name="Tokyo price source",
            source_url="https://example.com/tokyo-prices",
            observed_at=observed_at,
            verified_at=verified_at,
            source_class="curated_factual",
            confidence="high",
            display_order=order,
            is_published=True,
        )

    for order, (category, label, low, high) in enumerate(norway_prices, start=1):
        TypicalPrice.objects.create(
            country=no,
            category=category,
            label=label,
            amount_low=low,
            amount_high=high,
            currency=nok,
            source_name="Norway price source",
            source_url="https://example.com/norway-prices",
            observed_at=observed_at,
            verified_at=verified_at,
            source_class="curated_factual",
            confidence="high",
            display_order=order,
            is_published=True,
        )

    return {
        "fi": fi,
        "jp": jp,
        "no": no,
        "eur": eur,
        "jpy": jpy,
        "nok": nok,
        "tokyo": tokyo,
    }


def _payload(**overrides):
    values = {
        "amount": "500",
        "source_currency": "EUR",
        "left_destination": "JP:tokyo",
        "right_destination": "NO",
        "duration_days": "3",
        "travelers": "1",
        "units_coffee": "1",
        "units_casual_meal": "2",
        "units_transit": "2",
    }
    values.update(overrides)
    return values


@pytest.mark.django_db
def test_comparison_get_is_provider_free(client, comparison_reference_data):
    with patch("apps.exchange.views.build_latest_quote_gateway") as provider_factory:
        response = client.get(reverse("destination_comparison"))

    assert response.status_code == 200
    assert b"Same money. Two places. Visible assumptions." in response.content
    assert b"Tokyo, Japan" in response.content
    assert b"Norway" in response.content
    assert b"Rates are requested only after you submit." in response.content
    provider_factory.assert_not_called()


@pytest.mark.django_db
def test_comparison_post_uses_two_trusted_conversions_and_preserves_scope(
    client,
    comparison_reference_data,
):
    gateway = ComparisonGateway()

    with patch(
        "apps.exchange.views.build_latest_quote_gateway",
        return_value=gateway,
    ) as provider_factory:
        response = client.post(reverse("destination_comparison"), _payload())

    assert response.status_code == 200
    assert provider_factory.call_count == 1
    assert gateway.calls == [("EUR", "JPY"), ("EUR", "NOK")]

    body = response.content
    assert b"Tokyo, Japan" in body
    assert b"Norway" in body
    assert b"87250" in body
    assert b"5900.00" in body
    assert body.count(b"ECB") >= 2
    assert b"Tokyo price source" in body
    assert b"Norway price source" in body
    assert b"City scope" in body
    assert b"Country scope" in body
    assert b"No winner is calculated." in body
    assert b"purchasing-power-parity" in body


@pytest.mark.django_db
def test_comparison_partial_coverage_keeps_known_rows_and_names_missing_category(
    client,
    comparison_reference_data,
):
    TypicalPrice.objects.filter(
        country=comparison_reference_data["no"],
        category="transit",
    ).delete()
    gateway = ComparisonGateway()

    with patch("apps.exchange.views.build_latest_quote_gateway", return_value=gateway):
        response = client.post(reverse("destination_comparison"), _payload())

    assert response.status_code == 200
    assert b"Coverage is partial." in response.content
    assert b"Missing: Transit" in response.content
    assert b"Norway price source" in response.content


@pytest.mark.django_db
def test_same_destination_is_rejected_before_any_rate_request(
    client,
    comparison_reference_data,
):
    with patch("apps.exchange.views.build_latest_quote_gateway") as provider_factory:
        response = client.post(
            reverse("destination_comparison"),
            _payload(right_destination="JP:tokyo"),
        )

    assert response.status_code == 422
    assert b"Choose a different destination scope." in response.content
    provider_factory.assert_not_called()


@pytest.mark.django_db
def test_comparison_uses_source_currency_precision_before_rate_request(
    client,
    comparison_reference_data,
):
    with patch("apps.exchange.views.build_latest_quote_gateway") as provider_factory:
        response = client.post(
            reverse("destination_comparison"),
            _payload(amount="1.001"),
        )

    assert response.status_code == 422
    assert b"This amount is ambiguous" in response.content
    provider_factory.assert_not_called()


@pytest.mark.django_db
def test_second_rate_failure_returns_neutral_error_without_leaking_provider_detail(
    client,
    comparison_reference_data,
):
    gateway = ComparisonGateway(fail_quote="NOK")

    with patch("apps.exchange.views.build_latest_quote_gateway", return_value=gateway):
        response = client.post(reverse("destination_comparison"), _payload())

    assert response.status_code == 503
    assert gateway.calls == [("EUR", "JPY"), ("EUR", "NOK")]
    assert b"Destination B reference rate is unavailable" in response.content
    assert b"Nothing has been inferred for the unavailable side" in response.content
    assert b"upstream comparison test failure" not in response.content
    assert b"Side-by-side context" not in response.content


@pytest.mark.django_db
def test_comparison_field_descriptions_have_rendered_targets(
    client,
    comparison_reference_data,
):
    response = client.get(reverse("destination_comparison"))

    assert response.status_code == 200
    assert b'aria-describedby="units_coffee-hint"' in response.content
    assert b'id="units_coffee-hint"' in response.content
    assert b'id="duration_days-hint"' in response.content
    assert b'id="travelers-hint"' in response.content
