"""Source-trust, user-visible and fail-closed contract for country money guides."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from io import StringIO
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest
from django.core.management import call_command
from django.urls import reverse

from apps.countries.models import City, Country, CountryCurrency, Currency
from apps.culture.country_profile import (
    build_country_money_profile,
    build_country_money_profile_component,
)
from apps.culture.models import EconomicObservation, PublicHolidayObservation


@pytest.fixture(autouse=True)
def use_vite_dev_mode(settings):
    settings.VITE_DEV_SERVER_ENABLED = True


@pytest.fixture
def reviewed_country_data(db):
    call_command("seed_reference_data", stdout=StringIO())
    call_command("seed_destination_context", stdout=StringIO())


@pytest.mark.django_db
def test_country_guide_reuses_canonical_current_currency_and_evidence(reviewed_country_data):
    profile = build_country_money_profile(country_code="jp", as_of=date(2026, 10, 9))
    assert profile is not None
    assert profile.country_name == "Japan"
    assert profile.currency_code == "JPY"
    assert profile.payment is not None
    assert profile.prices
    assert all(item.currency_code == "JPY" for item in profile.prices)
    result = build_country_money_profile_component(profile)
    assert result["payment"]["source_url"].startswith("https://")
    assert result["prices"]
    assert all(item["source_url"].startswith("https://") for item in result["prices"])
    converter_query = parse_qs(urlparse(result["converter_url"]).query)
    assert converter_query["destination_country"] == ["JP"]
    assert converter_query["destination_currency"] == ["JPY"]
    assert parse_qs(urlparse(result["budget_url"]).query)["destination"] == ["JP"]
    assert parse_qs(urlparse(result["compare_url"]).query)["left_destination"] == ["JP"]


@pytest.mark.django_db
def test_country_guide_never_promotes_city_price_into_national_average(reviewed_country_data):
    profile = build_country_money_profile(country_code="JP", as_of=date(2026, 10, 9))
    assert profile is not None
    component = build_country_money_profile_component(profile)
    for raw, displayed in zip(profile.prices, component["prices"], strict=True):
        assert displayed["is_national"] is (not bool(raw.city or raw.city_slug))
        assert displayed["scope"] == raw.scope_label
    city_rows = [row for row in component["prices"] if not row["is_national"]]
    assert city_rows
    assert all("Tokyo" in row["scope"] for row in city_rows)
    assert component["reviewed_cities"] == (
        {
            "name": "Tokyo",
            "scope": "Tokyo",
            "profile_url": reverse("city_money_profile", args=("JP", "tokyo")),
        },
    )


@pytest.mark.django_db
def test_country_guide_renders_macro_and_holiday_evidence_without_external_fx(
    client, reviewed_country_data
):
    country = Country.objects.get(iso2="JP")
    EconomicObservation.objects.create(
        country=country,
        source="world_bank",
        indicator="inflation_yoy",
        category="all_items",
        value=Decimal("2.3"),
        unit="percent",
        period_start=date(2026, 1, 1),
        frequency="annual",
        observation_status="unknown",
        source_dataset="FP.CPI.TOTL.ZG",
        source_name="World Bank",
        source_url="https://example.org/japan-economy",
        source_retrieved_at=datetime(2026, 10, 8, tzinfo=UTC),
        is_published=True,
    )
    PublicHolidayObservation.objects.create(
        country=country,
        date=date(2026, 10, 16),
        name="Reviewed country holiday",
        national_holiday=True,
        subdivision_codes=[],
        holiday_types=["Public"],
        source_name="Nager.Date",
        source_url="https://example.org/japan-holidays",
        source_retrieved_at=datetime(2026, 10, 8, tzinfo=UTC),
        is_published=True,
    )
    with (
        patch("apps.culture.country_profile.timezone.localdate", return_value=date(2026, 10, 9)),
        patch("apps.exchange.views.build_latest_quote_gateway") as gateway_factory,
    ):
        response = client.get(reverse("country_money_profile", args=("JP",)))
    assert response.status_code == 200
    assert b"Money in Japan" in response.content
    assert b"2.3%" in response.content
    assert b"Source: World Bank" in response.content
    assert b"Reviewed country holiday" in response.content
    assert b"Source: Nager.Date" in response.content
    assert b"Regional dates are not included" in response.content
    assert b"without requesting an exchange rate" in response.content
    gateway_factory.assert_not_called()


@pytest.mark.django_db
def test_country_guide_excludes_stale_economy_and_non_national_holidays(
    client, reviewed_country_data
):
    country = Country.objects.get(iso2="JP")
    EconomicObservation.objects.create(
        country=country,
        source="world_bank",
        indicator="inflation_yoy",
        category="all_items",
        value=Decimal("99.9"),
        unit="percent",
        period_start=date(2018, 1, 1),
        frequency="annual",
        observation_status="unknown",
        source_dataset="old",
        source_name="World Bank",
        source_url="https://example.org/old",
        source_retrieved_at=datetime(2026, 10, 8, tzinfo=UTC),
        is_published=True,
    )
    PublicHolidayObservation.objects.create(
        country=country,
        date=date(2026, 10, 16),
        name="Regional-only day",
        national_holiday=False,
        subdivision_codes=["JP-01"],
        holiday_types=["Public"],
        source_name="Nager.Date",
        source_url="https://example.org/regional",
        source_retrieved_at=datetime(2026, 10, 8, tzinfo=UTC),
        is_published=True,
    )
    with patch(
        "apps.culture.country_profile.timezone.localdate",
        return_value=date(2026, 10, 9),
    ):
        response = client.get(reverse("country_money_profile", args=("JP",)))
    assert response.status_code == 200
    assert b"99.9%" not in response.content
    assert b"Regional-only day" not in response.content
    assert b"country-profile-economy-title" not in response.content
    assert b"country-profile-calendar-title" not in response.content


@pytest.mark.django_db
def test_country_guide_does_not_publish_unknown_or_unreviewed_context(
    client, reviewed_country_data
):
    assert client.get(reverse("country_money_profile", args=("ZZ",))).status_code == 404
    country = Country.objects.create(iso2="XZ", iso3="XZZ", name="Example unreviewed")
    currency = Currency.objects.get(code="EUR")
    CountryCurrency.objects.create(
        country=country,
        currency=currency,
        is_primary=True,
        source="test",
    )
    assert client.get(reverse("country_money_profile", args=("XZ",))).status_code == 404


@pytest.mark.django_db
def test_explore_country_card_and_region_link_to_reviewed_country_guide(
    client, reviewed_country_data
):
    response = client.get(reverse("explore"))
    assert response.status_code == 200
    href = reverse("country_money_profile", args=("JP",))
    assert href.encode() in response.content
    assert (
        b"View country money guide" in response.content
        or b"Country money guide" in response.content
    )


@pytest.mark.django_db
def test_country_guide_links_only_reviewed_canonical_city_evidence(client, reviewed_country_data):
    with patch("apps.exchange.views.build_latest_quote_gateway") as fx_gateway:
        response = client.get(reverse("country_money_profile", args=("JP",)))
    assert response.status_code == 200
    city_url = reverse("city_money_profile", args=("JP", "tokyo"))
    assert city_url.encode() in response.content
    assert b"Explore Tokyo city money profile" in response.content
    assert b"City profiles open the reviewed evidence" in response.content
    assert client.get(city_url).status_code == 200
    fx_gateway.assert_not_called()


@pytest.mark.django_db
def test_country_city_navigation_never_links_free_text_or_national_price(reviewed_country_data):
    profile = build_country_money_profile(country_code="JP", as_of=date(2026, 10, 9))
    assert profile is not None and profile.prices
    national_only = replace(
        profile,
        prices=(replace(profile.prices[0], city="", city_slug=""),),
    )
    assert build_country_money_profile_component(national_only)["reviewed_cities"] == ()

    # Unresolved legacy city labels cannot manufacture a canonical route.
    unlinked_city = replace(
        profile,
        prices=(replace(profile.prices[0], city="Unreviewed city", city_slug=""),),
    )
    assert build_country_money_profile_component(unlinked_city)["reviewed_cities"] == ()


@pytest.mark.django_db
def test_country_city_navigation_deduplicates_reviewed_city_links(reviewed_country_data):
    profile = build_country_money_profile(country_code="JP", as_of=date(2026, 10, 9))
    assert profile is not None
    city_price = next(price for price in profile.prices if price.city_slug == "tokyo")
    repeated = replace(profile, prices=(city_price, city_price, city_price))
    cities = build_country_money_profile_component(repeated)["reviewed_cities"]
    assert len(cities) == 1
    assert cities[0]["profile_url"] == reverse("city_money_profile", args=("JP", "tokyo"))


@pytest.mark.django_db
def test_country_guide_does_not_link_deactivated_city_price_history(reviewed_country_data):
    city = City.objects.get(country__iso2="JP", slug="tokyo")
    city.is_active = False
    city.save(update_fields=("is_active",))

    profile = build_country_money_profile(country_code="JP", as_of=date(2026, 10, 9))
    assert profile is not None
    assert any(price.city_slug == "tokyo" for price in profile.prices)
    assert profile.active_city_slugs == frozenset()
    component = build_country_money_profile_component(profile)
    assert component["reviewed_cities"] == ()


@pytest.mark.django_db
def test_country_guide_evidence_map_has_only_real_targets_without_fx(client, reviewed_country_data):
    from html.parser import HTMLParser

    class GuideMapParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.ids = set()
            self.links = []

        def handle_starttag(self, tag, attrs):
            data = dict(attrs)
            if "id" in data:
                self.ids.add(data["id"])
            if tag == "a" and data.get("class") == "qa-guide-map__link":
                self.links.append(data.get("href", ""))

    with patch("apps.exchange.views.build_latest_quote_gateway") as gateway_factory:
        response = client.get(reverse("country_money_profile", args=("JP",)))

    assert response.status_code == 200
    page = response.content.decode()
    assert 'data-guide-evidence-map="country"' in page
    parser = GuideMapParser()
    parser.feed(page)
    assert parser.links
    assert "#country-profile-payment-title" in parser.links
    assert "#country-profile-prices-title" in parser.links
    assert "#country-profile-next-title" in parser.links
    assert all(link.startswith("#") and link[1:] in parser.ids for link in parser.links)
    gateway_factory.assert_not_called()
