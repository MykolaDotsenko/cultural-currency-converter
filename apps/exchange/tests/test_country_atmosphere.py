from __future__ import annotations

from datetime import date

import pytest

from apps.countries.models import Country, CountryCurrency, Currency
from apps.exchange.forms import CurrentConversionForm
from apps.exchange.presentation import build_converter_context


@pytest.mark.django_db
def test_curated_country_receives_explicit_atmosphere_without_changing_controls():
    united_states = Country.objects.create(iso2="US", iso3="USA", name="United States")
    usd = Currency.objects.create(code="USD", name="US dollar", symbol="$")
    CountryCurrency.objects.create(
        country=united_states,
        currency=usd,
        is_primary=True,
        valid_from=date(1792, 1, 1),
        source="https://example.org/usd",
    )

    form = CurrentConversionForm(
        initial={
            "amount": "10.00",
            "source_country": "US",
            "source_currency": "USD",
            "destination_country": "US",
            "destination_currency": "USD",
        }
    )
    context = build_converter_context(form)

    assert context["source"]["theme"] == "us"
    assert context["destination"]["theme"] == "us"
    assert form.fields["source_currency"].widget.attrs["class"] == "qa-native-select"


@pytest.mark.django_db
def test_bilateral_context_can_hold_two_distinct_curated_country_atmospheres():
    finland = Country.objects.create(iso2="FI", iso3="FIN", name="Finland")
    japan = Country.objects.create(iso2="JP", iso3="JPN", name="Japan")
    eur = Currency.objects.create(code="EUR", name="Euro", symbol="€")
    jpy = Currency.objects.create(code="JPY", name="Japanese yen", symbol="¥", minor_units=0)
    CountryCurrency.objects.create(
        country=finland,
        currency=eur,
        is_primary=True,
        source="https://example.org/eur",
    )
    CountryCurrency.objects.create(
        country=japan,
        currency=jpy,
        is_primary=True,
        source="https://example.org/jpy",
    )

    form = CurrentConversionForm(
        initial={
            "amount": "10.00",
            "source_country": "FI",
            "source_currency": "EUR",
            "destination_country": "JP",
            "destination_currency": "JPY",
        }
    )

    context = build_converter_context(form)

    assert context["source"]["theme"] == "fi"
    assert context["destination"]["theme"] == "jp"
