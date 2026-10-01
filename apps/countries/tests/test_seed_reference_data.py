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
