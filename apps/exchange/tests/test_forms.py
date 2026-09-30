from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.countries.models import Country, CountryCurrency, Currency
from apps.exchange.forms import (
    BudgetInterpretationForm,
    CurrentConversionForm,
    HistoricalSeriesForm,
    parse_amount_text,
)


@pytest.mark.parametrize(
    ("raw", "minor_units", "expected"),
    [
        ("12.50", 2, Decimal("12.50")),
        ("12,50", 2, Decimal("12.50")),
        ("0", 2, Decimal("0")),
        ("100.00", 0, Decimal("100.00")),
        ("12.500", 2, Decimal("12.500")),
        ("1.234", 3, Decimal("1.234")),
    ],
)
def test_amount_parser_accepts_unambiguous_decimal_input(raw, minor_units, expected):
    assert parse_amount_text(raw, minor_units=minor_units) == expected


@pytest.mark.parametrize("raw", ["-1", "100 euros", "1,234.56"])
def test_amount_parser_rejects_invalid_or_grouped_input(raw):
    with pytest.raises(ValidationError):
        parse_amount_text(raw, minor_units=2)


def test_amount_parser_rejects_ambiguous_three_digit_fraction_for_eur():
    with pytest.raises(ValidationError, match="ambiguous"):
        parse_amount_text("1.234", minor_units=2)


def test_amount_parser_rejects_excess_precision():
    with pytest.raises(ValidationError, match="at most 2 decimal places"):
        parse_amount_text("12.3456", minor_units=2)


@pytest.fixture
def reference_data(db):
    fi = Country.objects.create(iso2="FI", iso3="FIN", name="Finland")
    jp = Country.objects.create(iso2="JP", iso3="JPN", name="Japan")
    eur = Currency.objects.create(code="EUR", name="Euro", symbol="€", minor_units=2)
    jpy = Currency.objects.create(code="JPY", name="Japanese yen", symbol="¥", minor_units=0)
    CountryCurrency.objects.create(
        country=fi,
        currency=eur,
        is_primary=True,
        source="test",
    )
    CountryCurrency.objects.create(
        country=jp,
        currency=jpy,
        is_primary=True,
        source="test",
    )
    return fi, jp, eur, jpy


def test_budget_form_native_decimal_contract_matches_server_precision():
    form = BudgetInterpretationForm(
        category_options=(("coffee", "Cup of coffee"),),
    )
    units = form.fields["units_coffee"]

    assert units.widget.attrs["min"] == "0.01"
    assert units.widget.attrs["step"] == "0.01"
    assert units.decimal_places == 2
    assert units.initial == Decimal("1")


def test_budget_form_accepts_its_default_reference_unit_grid():
    form = BudgetInterpretationForm(
        {
            "duration_days": "5",
            "travelers": "1",
            "units_coffee": "1.00",
        },
        category_options=(("coffee", "Cup of coffee"),),
    )

    assert form.is_valid(), form.errors
    assumptions = form.cleaned_data["budget_assumptions"]
    assert assumptions.duration_days == 5
    assert assumptions.travelers == 1
    assert assumptions.categories[0].units_per_person_per_day == Decimal("1.00")


@pytest.mark.django_db
def test_form_rejects_country_currency_mismatch_before_provider(reference_data):
    form = CurrentConversionForm(
        {
            "amount": "100",
            "source_country": "FI",
            "source_currency": "JPY",
            "destination_country": "JP",
            "destination_currency": "JPY",
        }
    )

    assert not form.is_valid()
    assert "source_currency" in form.errors


@pytest.mark.django_db
def test_form_normalizes_decimal_comma_to_decimal(reference_data):
    form = CurrentConversionForm(
        {
            "amount": "12,50",
            "source_country": "FI",
            "source_currency": "EUR",
            "destination_country": "JP",
            "destination_currency": "JPY",
        }
    )

    assert form.is_valid(), form.errors
    assert form.cleaned_data["amount_decimal"] == Decimal("12.50")


def test_amount_parser_rejects_value_above_product_bound():
    with pytest.raises(ValidationError, match="1,000,000,000"):
        parse_amount_text("1000000000.01", minor_units=2)


@pytest.mark.django_db
def test_historical_mode_requires_requested_date(reference_data):
    form = CurrentConversionForm(
        {
            "rate_mode": "historical",
            "amount": "100",
            "source_country": "FI",
            "source_currency": "EUR",
            "destination_country": "JP",
            "destination_currency": "JPY",
        }
    )

    assert not form.is_valid()
    assert form.errors["requested_date"] == ["Choose a historical date."]


@pytest.mark.django_db
def test_historical_mode_rejects_future_date(reference_data):
    form = CurrentConversionForm(
        {
            "rate_mode": "historical",
            "requested_date": (timezone.localdate() + timedelta(days=1)).isoformat(),
            "amount": "100",
            "source_country": "FI",
            "source_currency": "EUR",
            "destination_country": "JP",
            "destination_currency": "JPY",
        }
    )

    assert not form.is_valid()
    assert form.errors["requested_date"] == ["Historical date cannot be in the future."]


@pytest.mark.django_db
def test_latest_mode_ignores_unsubmitted_historical_date(reference_data):
    form = CurrentConversionForm(
        {
            "rate_mode": "latest",
            "requested_date": "1998-06-15",
            "amount": "100",
            "source_country": "FI",
            "source_currency": "EUR",
            "destination_country": "JP",
            "destination_currency": "JPY",
        }
    )

    assert form.is_valid(), form.errors
    assert form.cleaned_data["requested_date"] is None


def test_historical_series_form_rejects_requested_date_before_selected_observation():
    selected_date = timezone.localdate() - timedelta(days=2)
    form = HistoricalSeriesForm(
        {
            "base": "EUR",
            "quote": "JPY",
            "selected_date": selected_date.isoformat(),
            "requested_date": (selected_date - timedelta(days=1)).isoformat(),
            "period": "1y",
        }
    )

    assert not form.is_valid()
    assert form.errors["requested_date"] == [
        "Requested date cannot be before the selected observation date."
    ]


def test_historical_series_form_rejects_future_requested_date():
    form = HistoricalSeriesForm(
        {
            "base": "EUR",
            "quote": "JPY",
            "selected_date": (timezone.localdate() - timedelta(days=1)).isoformat(),
            "requested_date": (timezone.localdate() + timedelta(days=1)).isoformat(),
            "period": "1y",
        }
    )

    assert not form.is_valid()
    assert form.errors["requested_date"] == ["Requested date cannot be in the future."]
