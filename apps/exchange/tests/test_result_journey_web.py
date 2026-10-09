"""Trusted converter results lead to genuine current-only destination decisions."""

from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

import pytest
from django.urls import reverse

from apps.exchange.tests.test_web import FakeGateway, payload
from apps.exchange.tests.test_web import reference_data as reference_data


@pytest.fixture(autouse=True)
def use_vite_dev_mode(settings):
    settings.VITE_DEV_SERVER_ENABLED = True


@pytest.mark.django_db
def test_current_conversion_exposes_genuine_next_actions(client, reference_data):
    gateway = FakeGateway()
    with patch("apps.exchange.views.build_latest_quote_gateway", return_value=gateway):
        response = client.post(reverse("converter"), payload(), HTTP_HX_REQUEST="true")

    assert response.status_code == 200
    body = response.content.decode()
    assert "data-conversion-decision-journey" in body
    assert 'href="#payment-estimate-region"' in body
    assert 'id="payment-estimate-region"' in body
    assert 'href="#budget-interpretation-region"' in body
    assert 'id="budget-interpretation-region"' in body
    assert 'data-decision-kind="compare"' in body
    assert reverse("destination_comparison") in body
    assert len(gateway.calls) == 1


@pytest.mark.django_db
def test_comparison_handoff_carries_original_budget_not_converted_amount(client, reference_data):
    gateway = FakeGateway()
    with patch("apps.exchange.views.build_latest_quote_gateway", return_value=gateway):
        response = client.post(reverse("converter"), payload(), HTTP_HX_REQUEST="true")

    html = response.content.decode()
    from html.parser import HTMLParser

    class ActionLinkParser(HTMLParser):
        href = ""

        def handle_starttag(self, tag, attrs):
            if tag == "a":
                values = dict(attrs)
                if values.get("data-decision-kind") == "compare":
                    self.href = values.get("href", "")

    parser = ActionLinkParser()
    parser.feed(html)
    url = urlparse(parser.href)
    query = parse_qs(url.query)
    assert url.path == reverse("destination_comparison")
    assert query == {
        "amount": ["100.00"],
        "source_currency": ["EUR"],
        "left_destination": ["JP"],
    }
    assert "17450" not in parser.href
    assert "rate" not in query
    assert len(gateway.calls) == 1


@pytest.mark.django_db
def test_no_plan_handoff_when_destination_country_is_unknown(client, reference_data):
    gateway = FakeGateway()
    with patch("apps.exchange.views.build_latest_quote_gateway", return_value=gateway):
        response = client.post(
            reverse("converter"),
            payload(destination_country=""),
            HTTP_HX_REQUEST="true",
        )

    assert response.status_code == 200
    assert b'data-decision-kind="compare"' not in response.content
    assert b'data-decision-kind="payment"' in response.content
    assert len(gateway.calls) == 1


@pytest.mark.django_db
def test_historical_result_never_offers_current_decision_flow(client, reference_data):
    from apps.exchange.tests.test_web import FakeHistoricalGateway

    gateway = FakeHistoricalGateway()
    with patch("apps.exchange.views.build_historical_quote_gateway", return_value=gateway):
        response = client.post(
            reverse("converter"),
            payload(rate_mode="historical", selected_date="2026-09-18"),
            HTTP_HX_REQUEST="true",
        )

    assert response.status_code == 200
    assert b"data-conversion-decision-journey" not in response.content
    assert len(gateway.calls) == 1
