from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.db import DatabaseError
from django.urls import reverse
from django.utils import timezone

from apps.countries.models import City, Country, CountryCurrency, Currency
from apps.culture.models import (
    CulturalProfile,
    TypicalPrice,
    TypicalPriceCategory,
    TypicalPriceConfidence,
    TypicalPriceSourceClass,
)
from apps.exchange.domain import DEFAULT_SOURCE_POLICY, ConversionResult, RateQuote
from apps.travel.models import SavedScenarioKind, SavedScenarioSpendSource
from apps.travel.scenarios import (
    SavedScenarioSpec,
    create_saved_scenario,
    record_scenario_recheck,
    record_scenario_spend,
)

User = get_user_model()


@pytest.fixture(autouse=True)
def use_vite_dev_mode(settings):
    settings.VITE_DEV_SERVER_ENABLED = True


@pytest.fixture
def offline_pack_scenario(db):
    eur = Currency.objects.create(code="EUR", name="Euro", minor_units=2)
    jpy = Currency.objects.create(code="JPY", name="Japanese yen", minor_units=0)
    fi = Country.objects.create(iso2="FI", iso3="FIN", name="Finland")
    jp = Country.objects.create(iso2="JP", iso3="JPN", name="Japan")
    CountryCurrency.objects.create(country=fi, currency=eur, is_primary=True, source="test")
    CountryCurrency.objects.create(country=jp, currency=jpy, is_primary=True, source="test")
    tokyo = City.objects.create(country=jp, slug="tokyo", name="Tokyo")
    owner = User.objects.create_user(username="offline-pack-owner", password="StrongPass-482!")

    initial = ConversionResult(
        input_amount=Decimal("600"),
        output_amount=Decimal("104700"),
        quote=RateQuote(
            base_currency="EUR",
            quote_currency="JPY",
            rate=Decimal("174.5"),
            requested_date=None,
            effective_date=date(2026, 9, 30),
            fetched_at=datetime(2026, 9, 30, 18, tzinfo=UTC),
            provider_policy=DEFAULT_SOURCE_POLICY,
            provider_keys=("ecb",),
            historical=False,
        ),
        stale=False,
    )
    scenario = create_saved_scenario(
        owner,
        spec=SavedScenarioSpec(
            kind=SavedScenarioKind.BUDGET,
            title="Tokyo five days",
            source_currency=eur,
            destination_currency=jpy,
            source_country=fi,
            destination_country=jp,
            destination_city=tokyo,
            source_amount=Decimal("600"),
            duration_days=5,
            travelers=1,
        ),
        conversion=initial,
    )

    record_scenario_spend(
        scenario,
        amount=Decimal("4700"),
        source=SavedScenarioSpendSource.CAMERA,
    )
    record_scenario_recheck(
        scenario,
        conversion=ConversionResult(
            input_amount=Decimal("600"),
            output_amount=Decimal("120000"),
            quote=RateQuote(
                base_currency="EUR",
                quote_currency="JPY",
                rate=Decimal("200"),
                requested_date=None,
                effective_date=date(2026, 10, 1),
                fetched_at=datetime(2026, 10, 1, 7, tzinfo=UTC),
                provider_policy=DEFAULT_SOURCE_POLICY,
                provider_keys=("ecb",),
                historical=False,
            ),
            stale=False,
        ),
    )

    CulturalProfile.objects.create(
        country=jp,
        summary="Cards are widely accepted in many urban situations, while some cash use remains.",
        payment_customs="Check the merchant total before confirming payment.",
        cash_usage="Carry a modest cash fallback for smaller cash-preferred situations.",
        tipping="Tipping is generally not expected in ordinary service settings.",
        atm_notes="Use clearly identified ATMs and review issuer fees separately.",
        dcc_warning="If offered a home-currency conversion, compare it with the local-currency option.",
        source_name="Japan travel payment source",
        source_url="https://example.com/japan-payment",
        verified_at=timezone.now(),
        is_published=True,
    )
    TypicalPrice.objects.create(
        country=jp,
        city_ref=tokyo,
        category=TypicalPriceCategory.COFFEE,
        label="Coffee",
        amount_low=Decimal("450"),
        amount_high=Decimal("650"),
        currency=jpy,
        source_name="Tokyo price source",
        source_url="https://example.com/tokyo-coffee",
        observed_at=timezone.localdate(),
        verified_at=timezone.now(),
        source_class=TypicalPriceSourceClass.CURATED_FACTUAL,
        confidence=TypicalPriceConfidence.MEDIUM,
        is_published=True,
    )

    return owner, scenario


@pytest.mark.django_db
def test_owner_downloads_self_contained_offline_pack_with_saved_freshness_semantics(
    client,
    offline_pack_scenario,
):
    owner, scenario = offline_pack_scenario
    client.force_login(owner)

    response = client.get(
        reverse("download_offline_destination_pack", args=(scenario.pk,)),
    )

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/html")
    assert "attachment;" in response["Content-Disposition"]
    assert "tokyo-japan" in response["Content-Disposition"]
    assert response["Cache-Control"] == "private, no-store"
    assert response["X-Robots-Tag"] == "noindex, nofollow"
    assert response["Referrer-Policy"] == "no-referrer"

    text = " ".join(response.content.decode("utf-8").split())
    assert "Offline means stored, not live." in text
    assert "600 EUR → 120000 JPY" in text
    assert "Rate 200" in text
    assert "Effective 1 Oct 2026" in text
    assert "provider ecb" in text
    # Remaining budget deliberately stays anchored to the immutable initial output.
    assert "100000 JPY remaining" in text
    assert "Saved reference 104700 JPY" in text
    assert "confirmed spend 4700 JPY" in text
    assert "Coffee" in text
    assert "450 –650 JPY" in text or "450–650 JPY" in text
    assert "Tokyo price source" in text
    assert "Payment context" in text
    assert "Japan travel payment source" in text
    assert "No receipt image, merchant identity, account/card data or purchase description" in text

    html = response.content.decode("utf-8").lower()
    assert "<script" not in html
    assert 'rel="stylesheet"' not in html
    assert 'data-offline-pack-version="1"' in html


@pytest.mark.django_db
def test_offline_pack_destination_context_failure_degrades_without_losing_saved_money(
    client,
    offline_pack_scenario,
):
    owner, scenario = offline_pack_scenario
    client.force_login(owner)

    with patch(
        "apps.travel.offline_pack.build_destination_context_default",
        side_effect=DatabaseError("context unavailable"),
    ):
        response = client.get(
            reverse("download_offline_destination_pack", args=(scenario.pk,)),
        )

    assert response.status_code == 200
    text = " ".join(response.content.decode("utf-8").split())
    assert "600 EUR → 120000 JPY" in text
    assert "100000 JPY remaining" in text
    assert "Context was unavailable when this pack was generated" in text
    assert "No local-price or payment guidance was guessed" in text


@pytest.mark.django_db
def test_offline_pack_download_is_owner_scoped_and_requires_login(
    client,
    offline_pack_scenario,
):
    owner, scenario = offline_pack_scenario
    other = User.objects.create_user(username="offline-pack-other", password="StrongPass-482!")

    anonymous = client.get(
        reverse("download_offline_destination_pack", args=(scenario.pk,)),
    )
    assert anonymous.status_code == 302
    assert reverse("login") in anonymous.url

    client.force_login(other)
    forbidden = client.get(
        reverse("download_offline_destination_pack", args=(scenario.pk,)),
    )
    assert forbidden.status_code == 404

    client.force_login(owner)
    allowed = client.get(
        reverse("download_offline_destination_pack", args=(scenario.pk,)),
    )
    assert allowed.status_code == 200


@pytest.mark.django_db
def test_saved_budget_detail_exposes_offline_pack_action(client, offline_pack_scenario):
    owner, scenario = offline_pack_scenario
    client.force_login(owner)

    response = client.get(reverse("saved_scenario_detail", args=(scenario.pk,)))

    assert response.status_code == 200
    assert b"Download offline pack" in response.content
    assert (
        reverse("download_offline_destination_pack", args=(scenario.pk,)).encode()
        in response.content
    )
