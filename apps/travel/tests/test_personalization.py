from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier
from urllib.parse import parse_qs, urlparse

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, close_old_connections, transaction
from django.test import TransactionTestCase, skipUnlessDBFeature
from django.urls import reverse
from django.utils import timezone

from apps.countries.models import City, Country, CountryCurrency, Currency
from apps.culture.models import TypicalPrice
from apps.exchange.budget import BudgetAssumptions, BudgetBasis, BudgetCategoryAssumption
from apps.exchange.comparison_snapshot import (
    build_saved_comparison_token,
    load_saved_comparison_token,
)
from apps.travel.models import SavedComparison, SavedComparisonBudgetItem, SavedPlace
from apps.travel.personalization import persist_saved_comparison, sync_user_saved_places

User = get_user_model()


@pytest.fixture(autouse=True)
def use_vite_dev_mode(settings):
    settings.VITE_DEV_SERVER_ENABLED = True


@pytest.fixture
def personalization_reference_data(db):
    eur = Currency.objects.create(code="EUR", name="Euro", minor_units=2)
    jpy = Currency.objects.create(code="JPY", name="Japanese yen", minor_units=0)
    nok = Currency.objects.create(code="NOK", name="Norwegian krone", minor_units=2)

    fi = Country.objects.create(iso2="FI", iso3="FIN", name="Finland")
    jp = Country.objects.create(iso2="JP", iso3="JPN", name="Japan")
    no = Country.objects.create(iso2="NO", iso3="NOR", name="Norway")

    for country, currency in ((fi, eur), (jp, jpy), (no, nok)):
        CountryCurrency.objects.create(
            country=country,
            currency=currency,
            is_primary=True,
            source="https://example.test/currency",
        )

    helsinki = City.objects.create(country=fi, slug="helsinki", name="Helsinki")
    tokyo = City.objects.create(country=jp, slug="tokyo", name="Tokyo")

    return {
        "eur": eur,
        "jpy": jpy,
        "nok": nok,
        "fi": fi,
        "jp": jp,
        "no": no,
        "helsinki": helsinki,
        "tokyo": tokyo,
    }


def _comparison_token() -> str:
    return build_saved_comparison_token(
        source_amount=Decimal("500"),
        source_currency_code="EUR",
        left_destination="JP:tokyo",
        right_destination="NO",
        assumptions=BudgetAssumptions(
            duration_days=5,
            travelers=2,
            categories=(
                BudgetCategoryAssumption(
                    category="coffee",
                    units_per_person_per_day=Decimal("1"),
                ),
                BudgetCategoryAssumption(
                    category="casual_meal",
                    units_per_person_per_day=Decimal("2"),
                ),
                BudgetCategoryAssumption(
                    category="transit",
                    units_per_person_per_day=Decimal("2.5"),
                ),
            ),
            basis=BudgetBasis.REFERENCE_CONVERSION,
        ),
    )


@pytest.mark.django_db
def test_saved_place_sync_is_owner_scoped_and_idempotent(personalization_reference_data):
    owner = User.objects.create_user(username="owner", password="StrongPass-482!")
    other = User.objects.create_user(username="other", password="StrongPass-482!")

    first = sync_user_saved_places(
        owner,
        [
            {"countryCode": "FI", "citySlug": ""},
            {"countryCode": "FI", "citySlug": "helsinki"},
            {"countryCode": "FI", "citySlug": "helsinki"},
        ],
    )
    second = sync_user_saved_places(
        owner,
        [{"countryCode": "FI", "citySlug": "helsinki"}],
    )
    sync_user_saved_places(other, [{"countryCode": "JP", "citySlug": "tokyo"}])

    assert first.created_count == 2
    assert second.created_count == 0
    assert SavedPlace.objects.filter(user=owner).count() == 2
    assert SavedPlace.objects.filter(user=other).count() == 1
    assert {place.token for place in first.places} == {"FI", "FI:helsinki"}


@pytest.mark.django_db
def test_saved_place_json_sync_requires_authentication(client, personalization_reference_data):
    response = client.post(
        reverse("sync_saved_places"),
        data=json.dumps({"places": [{"countryCode": "FI", "citySlug": ""}]}),
        content_type="application/json",
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"
    assert not SavedPlace.objects.exists()


@pytest.mark.django_db
def test_saved_place_json_sync_rejects_unknown_city_without_partial_write(
    client,
    personalization_reference_data,
):
    user = User.objects.create_user(username="owner", password="StrongPass-482!")
    client.force_login(user)

    response = client.post(
        reverse("sync_saved_places"),
        data=json.dumps(
            {
                "places": [
                    {"countryCode": "FI", "citySlug": ""},
                    {"countryCode": "FI", "citySlug": "not-a-city"},
                ]
            }
        ),
        content_type="application/json",
    )

    assert response.status_code == 400
    assert not SavedPlace.objects.filter(user=user).exists()


@pytest.mark.django_db
def test_no_js_place_save_uses_same_canonical_service(
    client,
    personalization_reference_data,
):
    user = User.objects.create_user(username="owner", password="StrongPass-482!")
    client.force_login(user)

    first = client.post(
        reverse("save_place"),
        {"country_code": "JP", "city_slug": "tokyo"},
    )
    second = client.post(
        reverse("save_place"),
        {"country_code": "JP", "city_slug": "tokyo"},
    )

    assert first.status_code == 302
    assert first.url == reverse("explore")
    assert second.status_code == 302
    assert SavedPlace.objects.filter(user=user).count() == 1
    assert SavedPlace.objects.get(user=user).token == "JP:tokyo"


@pytest.mark.django_db
def test_saved_place_state_and_delete_are_owner_scoped(
    client,
    personalization_reference_data,
):
    owner = User.objects.create_user(username="owner", password="StrongPass-482!")
    other = User.objects.create_user(username="other", password="StrongPass-482!")
    own_place = SavedPlace.objects.create(
        user=owner,
        country=personalization_reference_data["fi"],
        city=personalization_reference_data["helsinki"],
    )
    hidden = SavedPlace.objects.create(
        user=other,
        country=personalization_reference_data["jp"],
        city=personalization_reference_data["tokyo"],
    )
    client.force_login(owner)

    state = client.get(reverse("saved_places_status"))
    denied = client.post(reverse("delete_saved_place", args=[hidden.pk]))

    assert state.status_code == 200
    assert state.json() == {"tokens": ["FI:helsinki"]}
    assert denied.status_code == 404
    assert SavedPlace.objects.filter(pk=own_place.pk).exists()
    assert SavedPlace.objects.filter(pk=hidden.pk).exists()


@pytest.mark.django_db
def test_saved_place_reentry_resolves_current_currency_instead_of_storing_snapshot(
    client,
    personalization_reference_data,
):
    user = User.objects.create_user(username="owner", password="StrongPass-482!")
    place = SavedPlace.objects.create(
        user=user,
        country=personalization_reference_data["fi"],
        city=personalization_reference_data["helsinki"],
    )
    old_link = CountryCurrency.objects.get(
        country=personalization_reference_data["fi"],
        currency=personalization_reference_data["eur"],
    )
    old_link.valid_to = timezone.localdate() - timedelta(days=1)
    old_link.save(update_fields=("valid_to",))
    new_currency = Currency.objects.create(code="SEK", name="Swedish krona", minor_units=2)
    CountryCurrency.objects.create(
        country=personalization_reference_data["fi"],
        currency=new_currency,
        is_primary=True,
        valid_from=timezone.localdate(),
        source="https://example.test/new-current-currency",
    )
    client.force_login(user)

    response = client.get(reverse("saved_state"))

    assert response.status_code == 200
    assert f'data-account-place-id="{place.pk}"'.encode() in response.content
    assert b"Current primary currency SEK" in response.content
    assert b"destination_currency=SEK" in response.content


@pytest.mark.django_db
def test_saved_comparison_save_is_explicit_idempotent_and_input_only(
    client,
    personalization_reference_data,
):
    user = User.objects.create_user(username="owner", password="StrongPass-482!")
    client.force_login(user)
    token = _comparison_token()

    first = client.post(
        reverse("save_comparison"),
        {"comparison_save_token": token},
    )
    second = client.post(
        reverse("save_comparison"),
        {"comparison_save_token": token},
    )

    saved = SavedComparison.objects.get(user=user)
    assert first.status_code == 302
    assert first.url == reverse("saved_state")
    assert second.status_code == 302
    assert SavedComparison.objects.filter(user=user).count() == 1
    assert saved.source_amount == Decimal("500.000000000000")
    assert saved.source_currency.code == "EUR"
    assert saved.left_token == "JP:tokyo"
    assert saved.right_token == "NO"
    assert saved.duration_days == 5
    assert saved.travelers == 2
    assert list(saved.budget_items.values_list("category", "units_per_person_per_day")) == [
        ("casual_meal", Decimal("2.00")),
        ("coffee", Decimal("1.00")),
        ("transit", Decimal("2.50")),
    ]
    assert not hasattr(saved, "rate")
    assert not hasattr(saved, "result")


@pytest.mark.django_db
def test_saved_comparison_database_rejects_same_country_scope(
    personalization_reference_data,
):
    user = User.objects.create_user(username="owner", password="StrongPass-482!")

    with pytest.raises(IntegrityError), transaction.atomic():
        SavedComparison.objects.create(
            user=user,
            fingerprint="a" * 64,
            source_currency=personalization_reference_data["eur"],
            source_amount=Decimal("500"),
            left_country=personalization_reference_data["jp"],
            right_country=personalization_reference_data["jp"],
            duration_days=5,
            travelers=1,
        )


@pytest.mark.django_db
def test_saved_comparison_database_rejects_out_of_contract_amount_and_category(
    personalization_reference_data,
):
    user = User.objects.create_user(username="owner", password="StrongPass-482!")

    with pytest.raises(IntegrityError), transaction.atomic():
        SavedComparison.objects.create(
            user=user,
            fingerprint="b" * 64,
            source_currency=personalization_reference_data["eur"],
            source_amount=Decimal("1000000000.01"),
            left_country=personalization_reference_data["jp"],
            left_city=personalization_reference_data["tokyo"],
            right_country=personalization_reference_data["no"],
            duration_days=5,
            travelers=1,
        )

    valid = SavedComparison.objects.create(
        user=user,
        fingerprint="c" * 64,
        source_currency=personalization_reference_data["eur"],
        source_amount=Decimal("500"),
        left_country=personalization_reference_data["jp"],
        left_city=personalization_reference_data["tokyo"],
        right_country=personalization_reference_data["no"],
        duration_days=5,
        travelers=1,
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        SavedComparisonBudgetItem.objects.create(
            comparison=valid,
            category="hotel",
            units_per_person_per_day=Decimal("1"),
        )


@pytest.mark.django_db
def test_saved_comparison_rejects_tampered_token(
    client,
    personalization_reference_data,
):
    user = User.objects.create_user(username="owner", password="StrongPass-482!")
    client.force_login(user)
    token = _comparison_token()

    response = client.post(
        reverse("save_comparison"),
        {"comparison_save_token": f"{token[:-1]}x"},
    )

    assert response.status_code == 302
    assert response.url == reverse("destination_comparison")
    assert not SavedComparison.objects.exists()


@pytest.mark.django_db
def test_saved_comparison_delete_and_saved_page_are_owner_scoped(
    client,
    personalization_reference_data,
):
    owner = User.objects.create_user(username="owner", password="StrongPass-482!")
    other = User.objects.create_user(username="other", password="StrongPass-482!")

    client.force_login(owner)
    client.post(reverse("save_comparison"), {"comparison_save_token": _comparison_token()})
    own = SavedComparison.objects.get(user=owner)

    client.force_login(other)
    client.post(reverse("save_comparison"), {"comparison_save_token": _comparison_token()})
    hidden = SavedComparison.objects.get(user=other)

    client.force_login(owner)
    page = client.get(reverse("saved_state"))
    denied = client.post(reverse("delete_saved_comparison", args=[hidden.pk]))

    assert page.status_code == 200
    body = page.content.decode()
    assert f'data-saved-comparison-id="{own.pk}"' in body
    assert f'data-saved-comparison-id="{hidden.pk}"' not in body
    assert "Reopen inputs" in body
    assert "Re-check now" in body
    assert 'action="/compare/"' in body
    assert 'name="amount" value="500"' in body
    assert 'name="left_destination" value="JP:tokyo"' in body
    assert 'name="right_destination" value="NO"' in body
    assert denied.status_code == 404
    assert SavedComparison.objects.filter(pk=hidden.pk).exists()


@pytest.mark.django_db
def test_saved_comparison_reopen_url_restores_inputs_without_result_snapshot(
    client,
    personalization_reference_data,
):
    user = User.objects.create_user(username="owner", password="StrongPass-482!")
    client.force_login(user)
    client.post(reverse("save_comparison"), {"comparison_save_token": _comparison_token()})

    page = client.get(reverse("saved_state"))
    row = page.context["account_saved_comparison_rows"][0]
    parsed = urlparse(row["reopen_url"])
    params = parse_qs(parsed.query)

    assert parsed.path == reverse("destination_comparison")
    assert params["amount"] == ["500"]
    assert params["source_currency"] == ["EUR"]
    assert params["left_destination"] == ["JP:tokyo"]
    assert params["right_destination"] == ["NO"]
    assert params["duration_days"] == ["5"]
    assert params["travelers"] == ["2"]
    assert "rate" not in params
    assert "result" not in params


@pytest.mark.django_db
def test_signed_in_saved_page_exposes_explicit_local_place_import_not_auto_migration(
    client,
    personalization_reference_data,
):
    user = User.objects.create_user(username="owner", password="StrongPass-482!")
    client.force_login(user)

    response = client.get(reverse("saved_state"))

    assert response.status_code == 200
    assert b"Import browser places to account" in response.content
    assert b"Sign-in never uploads these automatically." in response.content
    assert b"Import is an explicit, idempotent action" in response.content
    assert not SavedPlace.objects.filter(user=user).exists()


class DurablePersonalizationConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.eur = Currency.objects.create(code="EUR", name="Euro", minor_units=2)
        self.jpy = Currency.objects.create(
            code="JPY",
            name="Japanese yen",
            minor_units=0,
        )
        self.nok = Currency.objects.create(
            code="NOK",
            name="Norwegian krone",
            minor_units=2,
        )
        self.fi = Country.objects.create(iso2="FI", iso3="FIN", name="Finland")
        self.jp = Country.objects.create(iso2="JP", iso3="JPN", name="Japan")
        self.no = Country.objects.create(iso2="NO", iso3="NOR", name="Norway")
        for country, currency in (
            (self.fi, self.eur),
            (self.jp, self.jpy),
            (self.no, self.nok),
        ):
            CountryCurrency.objects.create(
                country=country,
                currency=currency,
                is_primary=True,
                source="https://example.test/currency",
            )
        City.objects.create(country=self.jp, slug="tokyo", name="Tokyo")
        self.user = User.objects.create_user(
            username="parallel-owner",
            password="StrongPass-482!",
        )

    @skipUnlessDBFeature("has_select_for_update")
    def test_concurrent_duplicate_place_sync_creates_one_owner_row(self):
        barrier = Barrier(2)
        payload = [{"countryCode": "JP", "citySlug": "tokyo"}]

        def worker():
            close_old_connections()
            try:
                user = User.objects.get(pk=self.user.pk)
                barrier.wait()
                sync_user_saved_places(user, payload)
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(worker) for _ in range(2)]
            for future in futures:
                future.result(timeout=10)

        self.assertEqual(SavedPlace.objects.filter(user=self.user).count(), 1)

    @skipUnlessDBFeature("has_select_for_update")
    def test_concurrent_duplicate_comparison_save_creates_one_owner_graph(self):
        barrier = Barrier(2)
        value = load_saved_comparison_token(_comparison_token())

        def worker():
            close_old_connections()
            try:
                user = User.objects.get(pk=self.user.pk)
                barrier.wait()
                persist_saved_comparison(user, value)
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(worker) for _ in range(2)]
            for future in futures:
                future.result(timeout=10)

        comparison = SavedComparison.objects.get(user=self.user)
        self.assertEqual(SavedComparison.objects.filter(user=self.user).count(), 1)
        self.assertEqual(comparison.budget_items.count(), 3)


@pytest.mark.django_db
def test_account_saved_city_profile_link_requires_current_sourced_city_evidence(
    client, personalization_reference_data
):
    user = User.objects.create_user(username="city-guide-owner", password="StrongPass-482!")
    city = personalization_reference_data["tokyo"]
    SavedPlace.objects.create(user=user, country=city.country, city=city)
    client.force_login(user)

    missing = client.get(reverse("saved_state"))
    assert missing.status_code == 200
    assert b"City profile" not in missing.content
    assert b"Explore" in missing.content

    TypicalPrice.objects.create(
        country=city.country,
        city_ref=city,
        city="",
        category="coffee",
        unit="serving",
        label="Tokyo coffee evidence",
        amount_low=Decimal("500"),
        currency=personalization_reference_data["jpy"],
        source_name="Reviewed coffee source",
        source_url="https://example.org/tokyo-coffee",
        observed_at=timezone.localdate(),
        verified_at=timezone.now(),
        is_published=True,
    )
    published = client.get(reverse("saved_state"))
    href = reverse("city_money_profile", args=("JP", "tokyo"))
    assert published.status_code == 200
    assert href.encode() in published.content
    assert b"City profile" in published.content


@pytest.mark.django_db
def test_account_place_ignores_stale_invalid_or_wrong_currency_price_evidence(
    client, personalization_reference_data
):
    user = User.objects.create_user(username="source-safe-owner", password="StrongPass-482!")
    city = personalization_reference_data["helsinki"]
    SavedPlace.objects.create(user=user, country=city.country, city=city)
    base = {
        "country": city.country,
        "city_ref": city,
        "city": "",
        "category": "coffee",
        "unit": "serving",
        "label": "Possible coffee evidence",
        "amount_low": Decimal("5"),
        "currency": personalization_reference_data["eur"],
        "source_name": "Reviewed provider",
        "source_url": "https://example.org/fi-coffee",
        "observed_at": timezone.localdate(),
        "verified_at": timezone.now(),
        "is_published": True,
    }
    TypicalPrice.objects.create(
        **{**base, "observed_at": timezone.localdate() - timedelta(days=800)}
    )
    TypicalPrice.objects.create(
        **{**base, "category": "transit", "unit": "ride", "source_url": "http://invalid.test"}
    )
    TypicalPrice.objects.create(
        **{
            **base,
            "category": "groceries",
            "unit": "basket",
            "currency": personalization_reference_data["jpy"],
        }
    )
    client.force_login(user)
    response = client.get(reverse("saved_state"))
    assert response.status_code == 200
    assert reverse("city_money_profile", args=("FI", "helsinki")).encode() not in response.content

    # A still-active reviewed price in the current currency makes the link safe.
    TypicalPrice.objects.create(**{**base, "category": "casual_meal", "unit": "meal"})
    valid = client.get(reverse("saved_state"))
    assert reverse("city_money_profile", args=("FI", "helsinki")).encode() in valid.content
