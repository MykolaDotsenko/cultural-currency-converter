"""Only explicit confirmation can transfer a Shopping estimate into a trip."""

import re
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.exchange.domain import DEFAULT_SOURCE_POLICY, ConversionResult, RateQuote
from apps.exchange.tests.test_shopping_web import ShoppingGateway, _payload
from apps.exchange.tests.test_shopping_web import (
    shopping_reference_data as shopping_reference_data,
)
from apps.travel.models import SavedScenario, SavedScenarioKind
from apps.travel.scenarios import SavedScenarioSpec, create_saved_scenario

User = get_user_model()


@pytest.fixture(autouse=True)
def use_vite_dev_mode(settings):
    settings.VITE_DEV_SERVER_ENABLED = True


@pytest.fixture
def matching_shopping_trip(db, shopping_reference_data):
    us, fi, usd, eur = shopping_reference_data
    owner = User.objects.create_user(username="shopping-trip-owner", password="StrongPass-482!")
    conversion = ConversionResult(
        input_amount=Decimal("300"),
        output_amount=Decimal("360"),
        quote=RateQuote(
            base_currency="EUR",
            quote_currency="USD",
            rate=Decimal("1.2"),
            requested_date=None,
            effective_date=date(2026, 10, 1),
            fetched_at=datetime(2026, 10, 2, 8, tzinfo=UTC),
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
            title="USA autumn trip",
            source_currency=eur,
            destination_currency=usd,
            source_country=fi,
            destination_country=us,
            source_amount=Decimal("300"),
            duration_days=5,
            travelers=1,
        ),
        conversion=conversion,
    )
    return owner, scenario


def _trip_token(response) -> str:
    body = response.content.decode()
    match = re.search(
        r"<form[^>]*data-shopping-trip-form[^>]*>.*?"
        r'name="shopping_context_token"\s+value="([^"]+)"',
        body,
        re.S,
    )
    assert match is not None
    return match.group(1)


@pytest.mark.django_db
def test_shopping_review_needs_separate_spend_confirmation(client, matching_shopping_trip):
    owner, scenario = matching_shopping_trip
    client.force_login(owner)
    gateway = ShoppingGateway()
    with patch("apps.exchange.views.build_latest_quote_gateway", return_value=gateway):
        estimate = client.post(reverse("shopping_calculation"), _payload())

    assert estimate.status_code == 200
    assert gateway.calls == [("USD", "EUR")]
    assert b"USA autumn trip" in estimate.content
    assert b"data-shopping-trip-handoff" in estimate.content
    assert b"130.00 USD" in estimate.content
    assert b"Review in this trip" in estimate.content
    assert "no-store" in estimate["Cache-Control"]
    token = _trip_token(estimate)
    original_output = scenario.observations.get().output_amount

    review = client.post(
        reverse("review_shopping_spend", args=(scenario.pk,)),
        {"shopping_context_token": token},
    )
    assert review.status_code == 200
    assert b"data-shopping-spend-review" in review.content
    assert b"Nothing has been recorded yet" in review.content
    assert b"data-shopping-review-jump" in review.content
    assert b'href="#shopping-spend-review"' in review.content
    assert b'id="shopping-spend-review"' in review.content
    assert b"Item price" in review.content
    assert b"100 USD" in review.content
    assert b"Shipping entered" in review.content
    assert b"20 USD" in review.content
    assert b"Known fees entered" in review.content
    assert b"10 USD" in review.content
    assert b"Proposed purchase total" in review.content
    assert b"130 USD" in review.content
    assert b"2.5% home-currency FX markup" in review.content
    assert b"not part of this purchase-currency trip spend" in review.content
    assert b'value="130"' in review.content
    assert gateway.calls == [("USD", "EUR")]
    assert scenario.spend_entries.count() == 0
    assert scenario.observations.count() == 1

    recorded = client.post(
        reverse("add_saved_scenario_spend", args=(scenario.pk,)),
        {"amount": "130.00"},
    )
    assert recorded.status_code == 302
    assert recorded.url == reverse("saved_scenario_detail", args=(scenario.pk,))
    assert scenario.spend_entries.count() == 1
    assert scenario.spend_entries.get().amount == Decimal("130")
    assert scenario.observations.get().output_amount == original_output


@pytest.mark.django_db
def test_review_is_owner_scoped_even_with_signed_shopping_token(client, matching_shopping_trip):
    owner, scenario = matching_shopping_trip
    other = User.objects.create_user(username="another-shopper", password="StrongPass-482!")
    client.force_login(owner)
    with patch("apps.exchange.views.build_latest_quote_gateway", return_value=ShoppingGateway()):
        shopping = client.post(reverse("shopping_calculation"), _payload())
    token = _trip_token(shopping)

    client.force_login(other)
    response = client.post(
        reverse("review_shopping_spend", args=(scenario.pk,)),
        {"shopping_context_token": token},
    )
    assert response.status_code == 404
    assert scenario.spend_entries.count() == 0


@pytest.mark.django_db
def test_bad_shopping_token_cannot_change_saved_budget(client, matching_shopping_trip):
    owner, scenario = matching_shopping_trip
    client.force_login(owner)
    response = client.post(
        reverse("review_shopping_spend", args=(scenario.pk,)),
        {"shopping_context_token": "forged-token"},
    )
    assert response.status_code == 422
    assert b"expired or is invalid" in response.content
    assert scenario.spend_entries.count() == 0
    assert scenario.observations.count() == 1


@pytest.mark.django_db
def test_review_rejects_wrong_currency_or_country(client, matching_shopping_trip):
    owner, scenario = matching_shopping_trip
    client.force_login(owner)
    with patch("apps.exchange.views.build_latest_quote_gateway", return_value=ShoppingGateway()):
        shopping = client.post(reverse("shopping_calculation"), _payload())
    token = _trip_token(shopping)

    other = SavedScenario.objects.create(
        user=owner,
        kind=SavedScenarioKind.BUDGET,
        title="Finland savings",
        source_currency=scenario.destination_currency,
        destination_currency=scenario.source_currency,
        source_country=scenario.destination_country,
        destination_country=scenario.source_country,
        source_amount=Decimal("300"),
    )
    denied = client.post(
        reverse("review_shopping_spend", args=(other.pk,)),
        {"shopping_context_token": token},
    )
    assert denied.status_code == 422
    assert other.spend_entries.count() == 0


@pytest.mark.django_db
def test_anonymous_shopping_does_not_expose_private_trips(client, matching_shopping_trip):
    with patch("apps.exchange.views.build_latest_quote_gateway", return_value=ShoppingGateway()):
        response = client.post(reverse("shopping_calculation"), _payload())
    assert response.status_code == 200
    assert b"USA autumn trip" not in response.content
    assert b"data-shopping-trip-handoff" not in response.content
    assert b"Review in this trip" not in response.content


@pytest.mark.django_db
def test_normal_saved_trip_detail_has_no_pending_shopping_breakdown(client, matching_shopping_trip):
    owner, scenario = matching_shopping_trip
    client.force_login(owner)
    response = client.get(reverse("saved_scenario_detail", args=(scenario.pk,)))
    assert response.status_code == 200
    assert b"data-shopping-review-jump" not in response.content
    assert b"data-shopping-spend-review" not in response.content
    assert b"Proposed purchase total" not in response.content
