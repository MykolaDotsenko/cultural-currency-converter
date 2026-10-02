from __future__ import annotations

from datetime import timedelta
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


class SameAmountGateway:
    def __init__(self, *, fail_quote: str = "") -> None:
        self.calls: list[tuple[str, str]] = []
        self.fail_quote = fail_quote

    def get(self, base, quote, policy, *, now):
        self.calls.append((base, quote))
        if quote == self.fail_quote:
            raise FxProviderUnavailable("upstream same-amount test failure")

        rates = {
            "JPY": Decimal("174.50"),
            "CAD": Decimal("1.51"),
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
def same_amount_reference_data(db):
    fi = Country.objects.create(iso2="FI", iso3="FIN", name="Finland")
    jp = Country.objects.create(iso2="JP", iso3="JPN", name="Japan")
    ca = Country.objects.create(iso2="CA", iso3="CAN", name="Canada")
    no = Country.objects.create(iso2="NO", iso3="NOR", name="Norway")

    eur = Currency.objects.create(code="EUR", name="Euro", symbol="€", minor_units=2)
    jpy = Currency.objects.create(code="JPY", name="Japanese yen", symbol="¥", minor_units=0)
    cad = Currency.objects.create(code="CAD", name="Canadian dollar", symbol="$", minor_units=2)
    nok = Currency.objects.create(code="NOK", name="Norwegian krone", symbol="kr", minor_units=2)

    for country, currency in ((fi, eur), (jp, jpy), (ca, cad), (no, nok)):
        CountryCurrency.objects.create(
            country=country,
            currency=currency,
            is_primary=True,
            source="https://example.com/currency",
        )

    tokyo = City.objects.create(country=jp, slug="tokyo", name="Tokyo")
    toronto = City.objects.create(country=ca, slug="toronto", name="Toronto")
    observed_at = timezone.localdate() - timedelta(days=5)
    verified_at = timezone.now()

    for country, summary in (
        (jp, "Cards are common in Japan; keep some cash for smaller situations."),
        (ca, "Cards are widely used in Canada."),
        (no, "Cards are widely used in Norway."),
    ):
        CulturalProfile.objects.create(
            country=country,
            summary=summary,
            cash_usage="Carry cash when the local situation calls for it.",
            dcc_warning="Review any dynamic currency conversion offer carefully.",
            source_name="Reviewed payment source",
            source_url="https://example.com/payment-context",
            verified_at=verified_at,
            is_published=True,
        )

    prices = (
        (jp, tokyo, jpy, "Tokyo coffee", Decimal("500"), Decimal("700")),
        (ca, toronto, cad, "Toronto coffee", Decimal("4"), Decimal("7")),
        (no, None, nok, "Norway coffee", Decimal("45"), Decimal("65")),
    )
    for order, (country, city, currency, label, low, high) in enumerate(prices, start=1):
        TypicalPrice.objects.create(
            country=country,
            city_ref=city,
            category="coffee",
            label=label,
            amount_low=low,
            amount_high=high,
            currency=currency,
            source_name=f"{label} source",
            source_url=f"https://example.com/{country.iso2.lower()}-prices",
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
        "ca": ca,
        "no": no,
        "eur": eur,
        "jpy": jpy,
        "cad": cad,
        "nok": nok,
        "tokyo": tokyo,
        "toronto": toronto,
    }


def _payload(**overrides):
    values = {
        "amount": "100",
        "source_currency": "EUR",
        "destinations": ["CA:toronto", "JP:tokyo", "NO"],
    }
    values.update(overrides)
    return values


@pytest.mark.django_db
def test_same_amount_get_is_provider_free_and_exposes_premium_contract(
    client,
    same_amount_reference_data,
):
    with patch("apps.exchange.views.build_latest_quote_gateway") as provider_factory:
        response = client.get(reverse("same_amount_destinations"))

    assert response.status_code == 200
    assert b"One amount. Several places. No artificial winner." in response.content
    assert b"Choose two to four destinations." in response.content
    assert b"View across destinations" in response.content
    assert b"Tokyo, Japan" in response.content
    assert b"Toronto, Canada" in response.content
    provider_factory.assert_not_called()


@pytest.mark.django_db
def test_same_amount_post_preserves_selection_order_and_independent_fx_semantics(
    client,
    same_amount_reference_data,
):
    gateway = SameAmountGateway()
    with patch(
        "apps.exchange.views.build_latest_quote_gateway",
        return_value=gateway,
    ) as provider_factory:
        response = client.post(reverse("same_amount_destinations"), _payload())

    assert response.status_code == 200
    assert provider_factory.call_count == 1
    assert gateway.calls == [("EUR", "CAD"), ("EUR", "JPY"), ("EUR", "NOK")]

    body = response.content
    toronto_index = body.index(b"Toronto, Canada")
    tokyo_index = body.index(b"Tokyo, Japan")
    norway_index = body.index(b"Norway")
    assert toronto_index < tokyo_index < norway_index

    assert b"151.00" in body
    assert b"17450" in body
    assert b"1180.00" in body
    assert body.count(b"ECB") >= 3
    assert b"Toronto coffee source" in body
    assert b"Tokyo coffee source" in body
    assert b"Norway coffee source" in body
    assert b"Reviewed payment source" in body
    assert b"No winner is calculated." in body
    assert b"cost-of-living index" in body
    assert b"PPP estimate" in body


@pytest.mark.django_db
def test_same_amount_partial_provider_failure_keeps_successful_destinations(
    client,
    same_amount_reference_data,
):
    gateway = SameAmountGateway(fail_quote="JPY")

    with patch("apps.exchange.views.build_latest_quote_gateway", return_value=gateway):
        response = client.post(reverse("same_amount_destinations"), _payload())

    assert response.status_code == 200
    assert gateway.calls == [("EUR", "CAD"), ("EUR", "JPY"), ("EUR", "NOK")]
    assert b"Toronto, Canada" in response.content
    assert b"Norway" in response.content
    assert b"Tokyo, Japan" in response.content
    assert b"Reference rate unavailable" in response.content
    assert b"The other selected destinations remain valid." in response.content
    assert b"upstream same-amount test failure" not in response.content
    assert b"Part of the view is unavailable." in response.content


@pytest.mark.django_db
def test_same_amount_all_provider_failures_return_service_unavailable_without_inference(
    client,
    same_amount_reference_data,
):
    class AllFailGateway(SameAmountGateway):
        def get(self, base, quote, policy, *, now):
            self.calls.append((base, quote))
            raise FxProviderUnavailable("do not leak me")

    gateway = AllFailGateway()
    with patch("apps.exchange.views.build_latest_quote_gateway", return_value=gateway):
        response = client.post(
            reverse("same_amount_destinations"),
            _payload(destinations=["CA:toronto", "JP:tokyo"]),
        )

    assert response.status_code == 503
    assert b"Reference rate unavailable" in response.content
    assert b"151.00" not in response.content
    assert b"17450" not in response.content
    assert b"do not leak me" not in response.content


@pytest.mark.django_db
@pytest.mark.parametrize(
    "destinations",
    [
        ["JP:tokyo"],
        ["CA:toronto", "JP:tokyo", "NO", "CA", "JP"],
    ],
)
def test_same_amount_rejects_out_of_bounds_destination_count_before_provider_call(
    client,
    same_amount_reference_data,
    destinations,
):
    with patch("apps.exchange.views.build_latest_quote_gateway") as provider_factory:
        response = client.post(
            reverse("same_amount_destinations"),
            _payload(destinations=destinations),
        )

    assert response.status_code == 422
    assert b"Choose between 2 and 4 destinations." in response.content
    provider_factory.assert_not_called()


@pytest.mark.django_db
def test_same_amount_uses_source_currency_precision_before_provider_call(
    client,
    same_amount_reference_data,
):
    with patch("apps.exchange.views.build_latest_quote_gateway") as provider_factory:
        response = client.post(
            reverse("same_amount_destinations"),
            _payload(amount="1.001", destinations=["CA:toronto", "JP:tokyo"]),
        )

    assert response.status_code == 422
    assert b"This amount is ambiguous" in response.content
    provider_factory.assert_not_called()


@pytest.mark.django_db
def test_same_amount_get_deep_link_prefills_destinations_without_provider_call(
    client,
    same_amount_reference_data,
):
    with patch("apps.exchange.views.build_latest_quote_gateway") as provider_factory:
        response = client.get(
            reverse("same_amount_destinations"),
            {
                "amount": "250",
                "source_currency": "EUR",
                "destination": ["JP:tokyo", "CA:toronto"],
            },
        )

    assert response.status_code == 200
    body = response.content
    assert b'value="250"' in body
    assert tuple(response.context["form"]["destinations"].value()) == (
        "JP:tokyo",
        "CA:toronto",
    )
    provider_factory.assert_not_called()


@pytest.mark.django_db
def test_explore_links_to_same_amount_surface(client, same_amount_reference_data):
    response = client.get(reverse("explore"))

    assert response.status_code == 200
    assert reverse("same_amount_destinations").encode() in response.content
    assert b"One amount" in response.content
    assert b"View the same amount" in response.content
