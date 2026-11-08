from unittest.mock import patch

import pytest
from django.urls import reverse

from apps.exchange.tests.test_web import FakeGateway, payload
from apps.exchange.tests.test_web import reference_data as reference_data


@pytest.fixture(autouse=True)
def use_vite_dev_mode(settings):
    settings.VITE_DEV_SERVER_ENABLED = True


@pytest.mark.django_db
def test_current_conversion_surfaces_canon_decision_layer_and_cultural_portal(
    client,
    reference_data,
):
    gateway = FakeGateway()

    with patch("apps.exchange.views.build_latest_quote_gateway", return_value=gateway):
        response = client.post(reverse("converter"), payload(), HTTP_HX_REQUEST="true")

    assert response.status_code == 200
    body = response.content.decode()

    assert "See what your money means there." not in body  # HTMX returns only the converter panel.
    assert "data-conversion-decision-summary" in body
    assert 'data-decision-card="local-value"' in body
    assert 'data-decision-card="payment-reality"' in body
    assert 'data-decision-card="money-tips"' in body
    assert 'data-decision-card="budget"' in body
    assert "What does this money mean there?" in body
    assert "Keep this trip, not just the currency pair." in body
    assert "Sign in to save trip" in body
    assert "data-trip-save-entry" in body
    assert "Culture &amp; currency portal" in body
    assert "Discover the place behind the money." in body
    assert body.count("qa-country-preview") >= 2
    assert body.count("qa-cultural-portal-trigger") >= 2
    assert len(gateway.calls) == 1


@pytest.mark.django_db
def test_full_converter_page_uses_market_promise_and_progressive_paths(client, reference_data):
    response = client.get(reverse("converter"))

    assert response.status_code == 200
    body = response.content.decode()
    assert "See what your money means there." in body
    assert "Two countries. Two worlds. One conversion experience." in body
    assert "Quick convert" in body
    assert "Travel &amp; budget" in body
    assert "Shopping" in body
