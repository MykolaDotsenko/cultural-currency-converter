from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.accounts.models import AccountPreferences
from apps.countries.models import Country, CountryCurrency, Currency

User = get_user_model()


@pytest.fixture(autouse=True)
def use_vite_dev_mode(settings):
    settings.VITE_DEV_SERVER_ENABLED = True


@pytest.fixture
def personalized_currency_data(db):
    fi = Country.objects.create(iso2="FI", iso3="FIN", name="Finland")
    jp = Country.objects.create(iso2="JP", iso3="JPN", name="Japan")
    no = Country.objects.create(iso2="NO", iso3="NOR", name="Norway")
    eur = Currency.objects.create(code="EUR", name="Euro", minor_units=2)
    jpy = Currency.objects.create(code="JPY", name="Japanese yen", minor_units=0)
    nok = Currency.objects.create(code="NOK", name="Norwegian krone", minor_units=2)
    for country, currency in ((fi, eur), (jp, jpy), (no, nok)):
        CountryCurrency.objects.create(
            country=country,
            currency=currency,
            is_primary=True,
            source="test",
        )
    return fi, jp, no, eur, jpy, nok


@pytest.mark.django_db
def test_fresh_converter_uses_explicit_account_home_currency(
    client,
    personalized_currency_data,
):
    _fi, _jp, _no, _eur, _jpy, nok = personalized_currency_data
    user = User.objects.create_user(username="personalized-converter", password="secret")
    AccountPreferences.objects.create(user=user, home_currency=nok)
    client.force_login(user)

    response = client.get(reverse("converter"))

    assert response.status_code == 200
    assert response.context["form"].initial["source_currency"] == "NOK"


@pytest.mark.django_db
def test_converter_explicit_loaded_pair_beats_home_currency(
    client,
    personalized_currency_data,
):
    _fi, _jp, _no, _eur, _jpy, nok = personalized_currency_data
    user = User.objects.create_user(username="personalized-load", password="secret")
    AccountPreferences.objects.create(user=user, home_currency=nok)
    client.force_login(user)

    response = client.get(
        reverse("converter"),
        {
            "load": "1",
            "source_currency": "EUR",
            "destination_currency": "JPY",
        },
    )

    assert response.status_code == 200
    assert response.context["form"].initial["source_currency"] == "EUR"


@pytest.mark.django_db
def test_destination_mode_uses_explicit_account_home_currency(
    client,
    personalized_currency_data,
):
    _fi, _jp, _no, _eur, _jpy, nok = personalized_currency_data
    user = User.objects.create_user(username="personalized-destination", password="secret")
    AccountPreferences.objects.create(user=user, home_currency=nok)
    client.force_login(user)

    response = client.get(reverse("destination_mode"), {"destination": "JP"})

    assert response.status_code == 200
    assert response.context["form"].initial["source_currency"] == "NOK"
    assert response.context["form"].initial["destination"] == "JP"


@pytest.mark.django_db
def test_comparison_uses_home_currency_only_when_query_does_not_supply_one(
    client,
    personalized_currency_data,
):
    _fi, _jp, _no, _eur, _jpy, nok = personalized_currency_data
    user = User.objects.create_user(username="personalized-comparison", password="secret")
    AccountPreferences.objects.create(user=user, home_currency=nok)
    client.force_login(user)

    preferred = client.get(reverse("destination_comparison"))
    explicit = client.get(
        reverse("destination_comparison"),
        {"source_currency": "EUR"},
    )

    assert preferred.status_code == 200
    assert preferred.context["form"].initial["source_currency"] == "NOK"
    assert explicit.status_code == 200
    assert explicit.context["form"].initial["source_currency"] == "EUR"
