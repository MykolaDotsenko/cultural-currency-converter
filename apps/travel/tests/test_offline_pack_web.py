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
    cache_control = response["Cache-Control"]
    assert "private" in cache_control
    assert "no-store" in cache_control
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
def test_saved_budget_detail_exposes_offline_pack_action_and_explicit_app_snapshot_control(
    client,
    offline_pack_scenario,
):
    owner, scenario = offline_pack_scenario
    client.force_login(owner)

    response = client.get(reverse("saved_scenario_detail", args=(scenario.pk,)))

    assert response.status_code == 200
    assert b"Offline options" in response.content
    assert b"Download portable HTML pack" in response.content
    download_url = reverse("download_offline_destination_pack", args=(scenario.pk,)).encode()
    assert response.content.count(download_url) == 1
    assert b"Save trip for offline" in response.content
    assert b"Nothing is stored in the app cache until you choose" in response.content
    assert reverse("offline_trip_snapshot", args=(scenario.pk,)).encode() in response.content
    assert b'data-offline-trip-revision="' in response.content


@pytest.mark.django_db
def test_explicit_offline_app_snapshot_is_private_owner_scoped_and_versioned(
    client,
    offline_pack_scenario,
):
    owner, scenario = offline_pack_scenario
    snapshot_url = reverse("offline_trip_snapshot", args=(scenario.pk,))

    anonymous = client.get(snapshot_url)
    assert anonymous.status_code == 302
    assert reverse("login") in anonymous.url

    other = User.objects.create_user(
        username="offline-snapshot-other",
        password="StrongPass-482!",
    )
    client.force_login(other)
    assert client.get(snapshot_url).status_code == 404

    client.force_login(owner)
    response = client.get(snapshot_url)

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/html")
    cache_control = response["Cache-Control"]
    assert "private" in cache_control
    assert "no-store" in cache_control
    assert response["Pragma"] == "no-cache"
    assert response["X-Robots-Tag"] == "noindex, nofollow"
    assert response["Referrer-Policy"] == "no-referrer"
    assert response["X-Cultural-Currency-Offline-Snapshot"] == "1"
    policy = response["Content-Security-Policy"]
    assert "default-src 'none'" in policy
    assert "script-src 'none'" in policy
    assert "style-src 'unsafe-inline'" in policy
    revision = response["X-Cultural-Currency-Snapshot-Revision"]
    assert len(revision) == 24
    assert response["X-Cultural-Currency-Snapshot-Generated-At"]

    html = response.content.decode("utf-8")
    assert f'data-offline-snapshot-revision="{revision}"' in html
    assert "Offline means stored, not live." in html
    assert "<script" not in html.lower()
    assert 'rel="stylesheet"' not in html.lower()
    assert "attachment;" not in response.headers.get("Content-Disposition", "")


@pytest.mark.django_db
def test_offline_snapshot_revision_changes_when_confirmed_spend_changes(
    client,
    offline_pack_scenario,
):
    owner, scenario = offline_pack_scenario
    client.force_login(owner)
    snapshot_url = reverse("offline_trip_snapshot", args=(scenario.pk,))

    before = client.get(snapshot_url)
    before_revision = before["X-Cultural-Currency-Snapshot-Revision"]

    record_scenario_spend(
        scenario,
        amount=Decimal("300"),
        source=SavedScenarioSpendSource.MANUAL,
    )

    after = client.get(snapshot_url)
    after_revision = after["X-Cultural-Currency-Snapshot-Revision"]

    assert before_revision != after_revision
    normalized = " ".join(after.content.decode("utf-8").split())
    assert "confirmed spend 5000 JPY" in normalized
