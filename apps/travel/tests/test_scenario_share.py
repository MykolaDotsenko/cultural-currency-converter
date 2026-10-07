from __future__ import annotations

import html
import re
from dataclasses import fields
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.countries.models import City, Country, Currency
from apps.travel.models import (
    SavedScenario,
    SavedScenarioKind,
    SavedScenarioObservation,
    SavedScenarioObservationKind,
    SavedScenarioSpendEntry,
    ScenarioNotificationCadence,
    ScenarioNotificationDeliveryChannel,
    ScenarioNotificationPreference,
    ScenarioNotificationType,
)
from apps.travel.share_snapshot import (
    ScenarioShareSnapshot,
    ScenarioShareTokenError,
    build_scenario_share_token,
    load_scenario_share_token,
)

User = get_user_model()


@pytest.fixture(autouse=True)
def use_vite_dev_mode(settings):
    settings.VITE_DEV_SERVER_ENABLED = True


@pytest.fixture
def private_scenario(db):
    owner = User.objects.create_user(
        username="private-owner-7842",
        password="StrongPass-482!",
    )
    eur = Currency.objects.create(code="EUR", name="Euro", minor_units=2)
    jpy = Currency.objects.create(code="JPY", name="Japanese yen", minor_units=0)
    japan = Country.objects.create(iso2="JP", iso3="JPN", name="Japan")
    tokyo = City.objects.create(country=japan, slug="tokyo", name="Tokyo")
    scenario = SavedScenario.objects.create(
        user=owner,
        kind=SavedScenarioKind.BUDGET,
        title="Secret family Tokyo 2027",
        source_currency=eur,
        destination_currency=jpy,
        destination_country=japan,
        destination_city=tokyo,
        source_amount=Decimal("600"),
        duration_days=6,
        travelers=3,
        travel_start_date=date(2027, 4, 12),
        travel_end_date=date(2027, 4, 18),
    )
    observation = SavedScenarioObservation.objects.create(
        scenario=scenario,
        kind=SavedScenarioObservationKind.INITIAL,
        input_amount=Decimal("600"),
        output_amount=Decimal("104700"),
        rate=Decimal("174.5"),
        effective_date=date(2026, 9, 30),
        fetched_at=datetime(2026, 9, 30, 18, tzinfo=UTC),
        provider_keys=["ecb"],
        stale=False,
    )
    SavedScenarioSpendEntry.objects.create(
        scenario=scenario,
        submission_key=uuid4(),
        amount=Decimal("4321"),
        source="manual",
    )
    ScenarioNotificationPreference.objects.create(
        scenario=scenario,
        notification_type=ScenarioNotificationType.RATE_ALERT,
        enabled=True,
        timezone="Europe/Helsinki",
        cadence=ScenarioNotificationCadence.DAILY,
        delivery_channel=ScenarioNotificationDeliveryChannel.IN_APP,
        rate_change_threshold_percent=Decimal("7.25"),
    )
    return owner, scenario, observation


def test_scenario_share_snapshot_is_privacy_minimized_and_round_trips(private_scenario):
    _owner, scenario, observation = private_scenario

    snapshot = load_scenario_share_token(build_scenario_share_token(scenario, observation))

    assert snapshot.kind == SavedScenarioKind.BUDGET
    assert snapshot.scope_label == "Tokyo, Japan"
    assert snapshot.input_amount == Decimal("600")
    assert snapshot.output_amount == Decimal("104700")
    assert snapshot.base_currency == "EUR"
    assert snapshot.quote_currency == "JPY"
    assert snapshot.rate == Decimal("174.5")
    assert snapshot.effective_date == date(2026, 9, 30)
    assert snapshot.fetched_at == datetime(2026, 9, 30, 18, tzinfo=UTC)
    assert snapshot.provider_keys == ("ecb",)
    assert snapshot.stale is False

    assert {field.name for field in fields(ScenarioShareSnapshot)} == {
        "kind",
        "scope_label",
        "input_amount",
        "output_amount",
        "base_currency",
        "quote_currency",
        "rate",
        "effective_date",
        "fetched_at",
        "provider_keys",
        "stale",
    }


def test_scenario_share_rejects_tampering_and_wrong_observation(private_scenario):
    owner, scenario, observation = private_scenario
    token = build_scenario_share_token(scenario, observation)

    with pytest.raises(ScenarioShareTokenError, match="invalid"):
        load_scenario_share_token(token + "tampered")

    other = SavedScenario.objects.create(
        user=owner,
        kind=SavedScenarioKind.BUDGET,
        title="Other private plan",
        source_currency=scenario.source_currency,
        destination_currency=scenario.destination_currency,
        destination_country=scenario.destination_country,
        destination_city=scenario.destination_city,
        source_amount=Decimal("600"),
        travelers=1,
    )
    wrong_observation = SavedScenarioObservation.objects.create(
        scenario=other,
        kind=SavedScenarioObservationKind.INITIAL,
        input_amount=Decimal("600"),
        output_amount=Decimal("104700"),
        rate=Decimal("174.5"),
        effective_date=date(2026, 9, 30),
        fetched_at=datetime(2026, 9, 30, 18, tzinfo=UTC),
        provider_keys=["ecb"],
        stale=False,
    )

    with pytest.raises(ScenarioShareTokenError, match="does not belong"):
        build_scenario_share_token(scenario, wrong_observation)


def test_owner_detail_exposes_explicit_privacy_safe_share_action(client, private_scenario):
    owner, scenario, _observation = private_scenario
    client.force_login(owner)

    response = client.get(reverse("saved_scenario_detail", args=(scenario.pk,)))
    body = response.content.decode("utf-8")

    assert response.status_code == 200
    assert "Share safe snapshot" in body
    assert "excludes your account identity" in body
    assert "confirmed spend" in body
    match = re.search(r'href="([^"]*\/share\/travel\/\?snapshot=[^"]+)"', body)
    assert match is not None
    assert html.unescape(match.group(1)).startswith(reverse("share_scenario_card"))


def test_public_scenario_share_is_provider_free_account_free_and_private(
    client,
    monkeypatch,
    django_assert_num_queries,
    private_scenario,
):
    owner, scenario, observation = private_scenario

    def unexpected_gateway(*_args, **_kwargs):
        raise AssertionError("Scenario share rendering must never build an FX gateway.")

    monkeypatch.setattr(
        "apps.exchange.web.gateways.build_latest_quote_gateway",
        unexpected_gateway,
    )
    token = build_scenario_share_token(scenario, observation)
    url = f"{reverse('share_scenario_card')}?snapshot={token}"

    with django_assert_num_queries(0):
        response = client.get(url)

    assert response.status_code == 200
    assert "private" in response["Cache-Control"]
    assert "no-store" in response["Cache-Control"]
    assert response["X-Robots-Tag"] == "noindex, nofollow"
    assert response["Referrer-Policy"] == "no-referrer"

    body = " ".join(response.content.decode("utf-8").split())
    assert "Tokyo, Japan" in body
    assert "600 EUR" in body
    assert "104700 JPY" in body
    assert "30 Sep 2026" in body
    assert "ECB" in body
    assert "does not refresh the exchange rate" in body
    assert "no account, scenario ID, trip dates, spending, Camera data or notification settings" in body

    for private_value in (
        owner.username,
        scenario.title,
        "2027-04-12",
        "2027-04-18",
        "4321",
        "7.25",
    ):
        assert private_value not in body


def test_scenario_share_svg_is_safe_and_invalid_tokens_fail_closed(client, private_scenario):
    owner, scenario, observation = private_scenario
    token = build_scenario_share_token(scenario, observation)

    svg = client.get(f"{reverse('share_scenario_card_svg')}?snapshot={token}")

    assert svg.status_code == 200
    assert svg["Content-Type"].startswith("image/svg+xml")
    assert "private" in svg["Cache-Control"]
    assert "no-store" in svg["Cache-Control"]
    body = svg.content.decode("utf-8")
    assert "<script" not in body.lower()
    assert "Tokyo, Japan" in body
    assert "600 EUR" in body
    assert "104700 JPY" in body
    assert owner.username not in body
    assert scenario.title not in body
    assert "4321" not in body
    assert "7.25" not in body

    page_invalid = client.get(reverse("share_scenario_card"), {"snapshot": "invalid"})
    svg_invalid = client.get(reverse("share_scenario_card_svg"), {"snapshot": "invalid"})
    assert page_invalid.status_code == 404
    assert svg_invalid.status_code == 404
