from datetime import date

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.countries.models import City, Country, CountryCurrency, Currency, primary_currency_for


@pytest.fixture
def finland():
    return Country.objects.create(iso2="FI", iso3="FIN", name="Finland")


@pytest.fixture
def eur():
    return Currency.objects.create(code="EUR", name="Euro", symbol="€")


@pytest.mark.django_db
def test_eur_can_map_to_multiple_countries(eur):
    finland = Country.objects.create(iso2="FI", iso3="FIN", name="Finland")
    france = Country.objects.create(iso2="FR", iso3="FRA", name="France")
    CountryCurrency.objects.create(country=finland, currency=eur, source="test")
    CountryCurrency.objects.create(country=france, currency=eur, source="test")

    assert set(eur.country_links.values_list("country__iso2", flat=True)) == {"FI", "FR"}


@pytest.mark.django_db
def test_primary_currency_query_preserves_historical_relationship(finland, eur):
    fim = Currency.objects.create(code="FIM", name="Finnish markka", is_active=False)
    CountryCurrency.objects.create(
        country=finland,
        currency=fim,
        is_primary=True,
        valid_to=date(2001, 12, 31),
        source="test",
    )
    CountryCurrency.objects.create(
        country=finland,
        currency=eur,
        is_primary=True,
        valid_from=date(2002, 1, 1),
        source="test",
    )

    assert primary_currency_for("FI", date(1998, 6, 15)) == fim
    assert primary_currency_for("FI", date(2026, 9, 20)) == eur
    assert primary_currency_for("FI") == eur


@pytest.mark.django_db
def test_only_one_active_primary_currency_is_allowed(finland, eur):
    CountryCurrency.objects.create(country=finland, currency=eur, is_primary=True, source="test")
    usd = Currency.objects.create(code="USD", name="US dollar")

    with pytest.raises(ValidationError, match="cannot overlap"):
        CountryCurrency.objects.create(
            country=finland,
            currency=usd,
            is_primary=True,
            source="test",
        )


@pytest.mark.django_db
def test_active_primary_database_constraint_remains_a_second_line_of_defense(finland, eur):
    CountryCurrency.objects.create(country=finland, currency=eur, is_primary=True, source="test")
    usd = Currency.objects.create(code="USD", name="US dollar")

    with pytest.raises(IntegrityError), transaction.atomic():
        CountryCurrency.objects.bulk_create(
            [
                CountryCurrency(
                    country=finland,
                    currency=usd,
                    is_primary=True,
                    source="test",
                )
            ]
        )


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("candidate_from", "candidate_to"),
    [
        (date(1999, 1, 1), date(2002, 1, 1)),
        (date(1990, 1, 1), date(2010, 1, 1)),
        (date(2000, 1, 1), date(2000, 12, 31)),
        (None, date(2000, 6, 1)),
        (date(2000, 6, 1), None),
        (None, None),
    ],
)
def test_primary_currency_periods_reject_any_inclusive_overlap(
    finland,
    eur,
    candidate_from,
    candidate_to,
):
    fim = Currency.objects.create(code="FIM", name="Finnish markka", is_active=False)
    CountryCurrency.objects.create(
        country=finland,
        currency=fim,
        is_primary=True,
        valid_from=date(2000, 1, 1),
        valid_to=date(2000, 12, 31),
        source="test",
    )

    with pytest.raises(ValidationError, match="cannot overlap"):
        CountryCurrency.objects.create(
            country=finland,
            currency=eur,
            is_primary=True,
            valid_from=candidate_from,
            valid_to=candidate_to,
            source="test",
        )


@pytest.mark.django_db
def test_adjacent_primary_currency_periods_are_allowed(finland, eur):
    fim = Currency.objects.create(code="FIM", name="Finnish markka", is_active=False)
    CountryCurrency.objects.create(
        country=finland,
        currency=fim,
        is_primary=True,
        valid_from=date(1999, 1, 1),
        valid_to=date(2001, 12, 31),
        source="test",
    )

    current = CountryCurrency.objects.create(
        country=finland,
        currency=eur,
        is_primary=True,
        valid_from=date(2002, 1, 1),
        source="test",
    )

    assert current.pk is not None


@pytest.mark.django_db
def test_non_primary_currency_period_may_overlap_primary_period(finland, eur):
    fim = Currency.objects.create(code="FIM", name="Finnish markka", is_active=False)
    CountryCurrency.objects.create(
        country=finland,
        currency=fim,
        is_primary=True,
        valid_from=date(1999, 1, 1),
        valid_to=date(2001, 12, 31),
        source="test",
    )

    secondary = CountryCurrency.objects.create(
        country=finland,
        currency=eur,
        is_primary=False,
        valid_from=date(2000, 1, 1),
        valid_to=date(2000, 12, 31),
        source="test",
    )

    assert secondary.pk is not None


@pytest.mark.django_db
def test_primary_period_overlap_is_scoped_to_one_country(finland, eur):
    france = Country.objects.create(iso2="FR", iso3="FRA", name="France")
    fim = Currency.objects.create(code="FIM", name="Finnish markka", is_active=False)
    CountryCurrency.objects.create(
        country=finland,
        currency=fim,
        is_primary=True,
        valid_from=date(2000, 1, 1),
        valid_to=date(2000, 12, 31),
        source="test",
    )

    france_euro = CountryCurrency.objects.create(
        country=france,
        currency=eur,
        is_primary=True,
        valid_from=date(2000, 1, 1),
        valid_to=date(2000, 12, 31),
        source="test",
    )

    assert france_euro.pk is not None


@pytest.mark.django_db
def test_updating_primary_period_into_overlap_is_rejected(finland, eur):
    fim = Currency.objects.create(code="FIM", name="Finnish markka", is_active=False)
    historical = CountryCurrency.objects.create(
        country=finland,
        currency=fim,
        is_primary=True,
        valid_from=date(1999, 1, 1),
        valid_to=date(2001, 12, 31),
        source="test",
    )
    current = CountryCurrency.objects.create(
        country=finland,
        currency=eur,
        is_primary=True,
        valid_from=date(2002, 1, 1),
        source="test",
    )

    current.valid_from = date(2001, 12, 31)
    with pytest.raises(ValidationError, match="cannot overlap"):
        current.save()

    current.refresh_from_db()
    assert current.valid_from == date(2002, 1, 1)
    assert historical.valid_to == date(2001, 12, 31)


@pytest.mark.django_db
def test_archived_currency_remains_representable(finland):
    fim = Currency.objects.create(
        code="FIM",
        name="Finnish markka",
        is_active=False,
        active_to=date(2001, 12, 31),
    )
    link = CountryCurrency.objects.create(
        country=finland,
        currency=fim,
        is_primary=True,
        valid_to=date(2001, 12, 31),
        source="test",
    )

    assert CountryCurrency.objects.on_date(date(1998, 1, 1)).get() == link
    assert not CountryCurrency.objects.current().filter(currency=fim).exists()


@pytest.mark.django_db
def test_current_relationship_excludes_future_valid_from(finland, eur):
    CountryCurrency.objects.create(
        country=finland,
        currency=eur,
        is_primary=True,
        valid_from=date(2099, 1, 1),
        source="test",
    )

    assert not CountryCurrency.objects.current(as_of=date(2026, 9, 20)).exists()
    assert CountryCurrency.objects.current(as_of=date(2099, 1, 1)).exists()


@pytest.mark.django_db
def test_currency_covered_on_treats_latest_observation_as_non_terminal():
    eur = Currency.objects.create(
        code="EUR",
        name="Euro",
        coverage_from=date(1999, 1, 4),
        coverage_to=date(2026, 9, 18),
        coverage_to_is_terminal=False,
    )

    assert Currency.objects.covered_on(date(2026, 9, 20)).get() == eur


@pytest.mark.django_db
def test_currency_covered_on_respects_terminal_archived_coverage():
    fim = Currency.objects.create(
        code="FIM",
        name="Finnish markka",
        is_active=False,
        coverage_from=date(1972, 1, 3),
        coverage_to=date(2001, 12, 28),
        coverage_to_is_terminal=True,
    )

    assert Currency.objects.covered_on(date(1998, 6, 15)).get() == fim
    assert not Currency.objects.covered_on(date(2002, 1, 1)).filter(pk=fim.pk).exists()


@pytest.mark.django_db
def test_city_identity_is_scoped_to_country():
    japan = Country.objects.create(iso2="JP", iso3="JPN", name="Japan")
    united_states = Country.objects.create(iso2="US", iso3="USA", name="United States")

    tokyo = City.objects.create(country=japan, slug="TOKYO ", name="Tokyo")
    tokyo_us = City.objects.create(country=united_states, slug="tokyo", name="Tokyo")

    assert tokyo.slug == "tokyo"
    assert tokyo_us.slug == "tokyo"
    assert str(tokyo) == "Tokyo, JP"


@pytest.mark.django_db
def test_city_slug_must_be_unique_within_country():
    japan = Country.objects.create(iso2="JP", iso3="JPN", name="Japan")
    City.objects.create(country=japan, slug="tokyo", name="Tokyo")

    with pytest.raises(IntegrityError), transaction.atomic():
        City.objects.create(country=japan, slug="TOKYO", name="Tokyo duplicate")
