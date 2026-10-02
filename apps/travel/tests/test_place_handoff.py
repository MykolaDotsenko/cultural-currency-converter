from __future__ import annotations

import pytest
from django.urls import reverse

from apps.countries.models import City, Country, CountryCurrency, Currency


@pytest.fixture(autouse=True)
def use_vite_dev_mode(settings):
    settings.VITE_DEV_SERVER_ENABLED = True


@pytest.fixture
def place_reference_data(db):
    japan = Country.objects.create(iso2="JP", iso3="JPN", name="Japan")
    jpy = Currency.objects.create(code="JPY", name="Japanese yen", minor_units=0)
    CountryCurrency.objects.create(
        country=japan,
        currency=jpy,
        is_primary=True,
        source="https://example.org/jpy",
    )
    City.objects.create(country=japan, slug="tokyo", name="Tokyo")


@pytest.mark.django_db
def test_saved_state_accepts_canonical_city_place_intent_without_persisting_it(
    client,
    place_reference_data,
):
    response = client.get(reverse("saved_state"), {"place": "JP:tokyo"})

    assert response.status_code == 200
    selected = response.context["selected_place_intent"]
    assert selected["token"] == "JP:tokyo"
    assert selected["scope_label"] == "Tokyo, Japan"
    assert selected["currency_code"] == "JPY"
    assert b"Selected from Explore" in response.content
    assert b"does not silently" in response.content
    assert b"Create budget / trip" in response.content


@pytest.mark.django_db
def test_saved_state_accepts_country_place_intent(place_reference_data, client):
    response = client.get(reverse("saved_state"), {"place": "JP"})

    assert response.status_code == 200
    assert response.context["selected_place_intent"]["scope_label"] == "Japan"


@pytest.mark.django_db
@pytest.mark.parametrize("token", ["", "XX", "JP:missing", "not-a-country"])
def test_saved_state_invalid_place_intent_fails_closed(client, place_reference_data, token):
    response = client.get(reverse("saved_state"), {"place": token})

    assert response.status_code == 200
    assert response.context["selected_place_intent"] is None
    assert b"Selected from Explore" not in response.content
