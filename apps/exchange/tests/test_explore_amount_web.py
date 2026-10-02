from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from urllib.parse import parse_qs, urlparse
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


class ExploreAmountGateway:
    def __init__(self, *, fail_quote: str = "") -> None:
        self.calls: list[tuple[str, str]] = []
        self.fail_quote = fail_quote

    def get(self, base, quote, policy, *, now):
        self.calls.append((base, quote))
        if quote == self.fail_quote:
            raise FxProviderUnavailable("upstream same-amount test failure")

        rates = {
            "JPY": Decimal("174.50"),
            "NOK": Decimal("11.80"),
            "CAD": Decimal("1.60"),
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
def explore_amount_reference_data(db):
    fi = Country.objects.create(iso2="FI", iso3="FIN", name="Finland")
    jp = Country.objects.create(iso2="JP", iso3="JPN", name="Japan")
    no = Country.objects.create(iso2="NO", iso3="NOR", name="Norway")
    ca = Country.objects.create(iso2="CA", iso3="CAN", name="Canada")

    eur = Currency.objects.create(code="EUR", name="Euro", symbol="€", minor_units=2)
    jpy = Currency.objects.create(code="JPY", name="Japanese yen", symbol="¥", minor_units=0)
    nok = Currency.objects.create(code="NOK", name="Norwegian krone", symbol="kr", minor_units=2)
    cad = Currency.objects.create(code="CAD", name="Canadian dollar", symbol="$", minor_units=2)

    for country, currency in ((fi, eur), (jp, jpy), (no, nok), (ca, cad)):
        CountryCurrency.objects.create(
            country=country,
            currency=currency,
            is_primary=True,
            source="https://example.org/currency",
        )

    tokyo = City.objects.create(country=jp, slug="tokyo", name="Tokyo")
    verified_at = timezone.now()
    observed_at = timezone.localdate() - timedelta(days=5)

    for country in (jp, no, ca):
        CulturalProfile.objects.create(
            country=country,
            summary=f"Reviewed payment context for {country.name}.",
            cash_usage="Reviewed cash guidance.",
            source_name="Official payment source",
            source_url="https://example.org/payment",
            verified_at=verified_at,
            is_published=True,
        )

    for order, (category, label, low, high) in enumerate(
        (
            ("coffee", "Coffee", Decimal("500"), Decimal("700")),
            ("transit", "Transit", Decimal("180"), Decimal("300")),
        ),
        start=1,
    ):
        TypicalPrice.objects.create(
            country=jp,
            city_ref=tokyo,
            category=category,
            label=label,
            amount_low=low,
            amount_high=high,
            currency=jpy,
            source_name="Tokyo reviewed source",
            source_url="https://example.org/tokyo",
            observed_at=observed_at,
            verified_at=verified_at,
            source_class="curated_factual",
            confidence="high",
            display_order=order,
            is_published=True,
        )

    for country, currency, amount in (
        (no, nok, Decimal("45")),
        (ca, cad, Decimal("5")),
    ):
        TypicalPrice.objects.create(
            country=country,
            category="coffee",
            label=f"{country.name} coffee",
            amount_low=amount,
            currency=currency,
            source_name=f"{country.name} reviewed source",
            source_url=f"https://example.org/{country.iso2.lower()}",
            observed_at=observed_at,
            verified_at=verified_at,
            source_class="curated_factual",
            confidence="high",
            is_published=True,
        )

    return {"tokyo": tokyo}


@pytest.mark.django_db
def test_same_amount_get_is_provider_free(client, explore_amount_reference_data):
    with patch("apps.exchange.views.build_latest_quote_gateway") as provider_factory:
        response = client.get(reverse("explore_same_amount"))

    assert response.status_code == 200
    assert b"See the same amount in local money contexts." in response.content
    assert b"Choose 2" in response.content
    provider_factory.assert_not_called()


@pytest.mark.django_db
def test_same_amount_post_reuses_canonical_current_conversion_per_destination(
    client,
    explore_amount_reference_data,
):
    gateway = ExploreAmountGateway()

    with patch("apps.exchange.views.build_latest_quote_gateway", return_value=gateway):
        response = client.post(
            reverse("explore_same_amount"),
            {
                "amount": "100",
                "source_currency": "EUR",
                "destinations": ["JP:tokyo", "NO", "CA"],
            },
        )

    assert response.status_code == 200
    assert gateway.calls == [("EUR", "JPY"), ("EUR", "NOK"), ("EUR", "CAD")]
    assert response.context["successful_card_count"] == 3
    body = response.content
    assert b"Tokyo, Japan" in body
    assert b"Norway" in body
    assert b"Canada" in body
    assert b"17450" in body
    assert b"1180.00" in body
    assert b"160.00" in body
    assert body.count(b"ECB") >= 3
    assert b"Tokyo reviewed source" in body
    assert b"No winner" in body

    compare = urlparse(response.context["comparison_url"])
    query = parse_qs(compare.query)
    assert compare.path == reverse("destination_comparison")
    assert query["amount"] == ["100"]
    assert query["source_currency"] == ["EUR"]
    assert query["left_destination"] == ["JP:tokyo"]
    assert query["right_destination"] == ["NO"]


@pytest.mark.django_db
def test_same_amount_partial_provider_failure_keeps_other_destination_results(
    client,
    explore_amount_reference_data,
):
    gateway = ExploreAmountGateway(fail_quote="NOK")

    with patch("apps.exchange.views.build_latest_quote_gateway", return_value=gateway):
        response = client.post(
            reverse("explore_same_amount"),
            {
                "amount": "100",
                "source_currency": "EUR",
                "destinations": ["JP:tokyo", "NO", "CA"],
            },
        )

    assert response.status_code == 200
    assert response.context["successful_card_count"] == 2
    assert b"Tokyo, Japan" in response.content
    assert b"Canada" in response.content
    assert b"Reference unavailable" in response.content
    assert b"upstream same-amount test failure" not in response.content


@pytest.mark.django_db
@pytest.mark.parametrize(
    "destinations",
    [
        ["JP:tokyo"],
        ["JP:tokyo", "NO", "CA", "FI", "JP"],
    ],
)
def test_same_amount_rejects_destination_count_before_rate_request(
    client,
    explore_amount_reference_data,
    destinations,
):
    with patch("apps.exchange.views.build_latest_quote_gateway") as provider_factory:
        response = client.post(
            reverse("explore_same_amount"),
            {
                "amount": "100",
                "source_currency": "EUR",
                "destinations": destinations,
            },
        )

    assert response.status_code == 422
    provider_factory.assert_not_called()


@pytest.mark.django_db
def test_compare_handoff_prefills_both_destinations_amount_and_source(
    client,
    explore_amount_reference_data,
):
    response = client.get(
        reverse("destination_comparison"),
        {
            "amount": "250",
            "source_currency": "EUR",
            "left_destination": "JP:tokyo",
            "right_destination": "NO",
        },
    )

    assert response.status_code == 200
    form = response.context["form"]
    assert form.initial["amount"] == "250"
    assert form.initial["source_currency"] == "EUR"
    assert form.initial["left_destination"] == "JP:tokyo"
    assert form.initial["right_destination"] == "NO"
