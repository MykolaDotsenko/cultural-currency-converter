from datetime import date

import pytest
from django.core.management import call_command

from apps.countries.models import CountryCurrency, Currency


@pytest.mark.django_db
def test_reference_seed_persists_currency_minor_units():
    call_command("seed_reference_data")

    expected_minor_units = {
        "EUR": 2,
        "JPY": 0,
        "USD": 2,
        "SEK": 2,
        "DKK": 2,
        "NOK": 2,
        "SGD": 2,
        "CAD": 2,
        "NZD": 2,
        "FIM": 2,
    }
    assert {
        code: Currency.objects.get(code=code).minor_units for code in expected_minor_units
    } == expected_minor_units


@pytest.mark.django_db
def test_reference_seed_exposes_wave_one_current_primary_currencies():
    call_command("seed_reference_data")

    links = (
        CountryCurrency.objects.current(date(2026, 10, 1))
        .primary()
        .filter(country__iso2__in={"FI", "SE", "DK", "NO", "DE"})
        .select_related("country", "currency")
    )

    assert {link.country.iso2: link.currency.code for link in links} == {
        "FI": "EUR",
        "SE": "SEK",
        "DK": "DKK",
        "NO": "NOK",
        "DE": "EUR",
    }
    assert all(link.source.startswith("https://") for link in links)


@pytest.mark.django_db
def test_reference_seed_exposes_wave_two_current_primary_currencies():
    call_command("seed_reference_data")

    links = (
        CountryCurrency.objects.current(date(2026, 10, 1))
        .primary()
        .filter(country__iso2__in={"JP", "SG", "CA", "NZ"})
        .select_related("country", "currency")
    )

    assert {link.country.iso2: link.currency.code for link in links} == {
        "JP": "JPY",
        "SG": "SGD",
        "CA": "CAD",
        "NZ": "NZD",
    }
    assert all(link.source.startswith("https://") for link in links)


@pytest.mark.django_db
def test_reference_seed_populates_canonical_region_metadata():
    call_command("seed_reference_data")

    expected = {
        "FI": ("Europe", "Northern Europe"),
        "JP": ("Asia", "Eastern Asia"),
        "US": ("Americas", "Northern America"),
        "DE": ("Europe", "Western Europe"),
        "SG": ("Asia", "South-Eastern Asia"),
        "CA": ("Americas", "Northern America"),
        "NZ": ("Oceania", "Australia and New Zealand"),
    }

    actual = {
        country.iso2: (country.region, country.subregion)
        for country in Country.objects.filter(iso2__in=expected)
    }
    assert actual == expected
