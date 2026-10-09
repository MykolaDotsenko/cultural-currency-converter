"""The Money Studio exposes existing tools only when conversion is idle."""

from unittest.mock import patch

import pytest
from django.urls import reverse

from apps.exchange.tests.test_web import FakeGateway, payload
from apps.exchange.tests.test_web import reference_data as reference_data


@pytest.fixture(autouse=True)
def use_vite_dev_mode(settings):
    settings.VITE_DEV_SERVER_ENABLED = True


@pytest.mark.django_db
def test_idle_money_studio_links_existing_tools_without_requesting_fx(client, reference_data):
    with patch("apps.exchange.views.build_latest_quote_gateway") as rate_factory:
        response = client.get(reverse("converter"))

    assert response.status_code == 200
    body = response.content.decode()
    assert "data-money-studio" in body
    assert 'aria-label="Travel money tools"' in body
    for route, action in (
        ("destination_mode", "destination"),
        ("destination_comparison", "compare"),
        ("shopping_calculation", "shopping"),
        ("explore", "explore"),
    ):
        assert f'data-money-studio-action="{action}"' in body
        assert f'href="{reverse(route)}"' in body
    assert f'href="{reverse("saved_state")}"' in body
    assert body.index('id="converter-panel"') < body.index("data-money-studio")
    rate_factory.assert_not_called()


@pytest.mark.django_db
def test_money_studio_is_not_duplicate_of_results_or_htmx(client, reference_data):
    gateway = FakeGateway()
    with patch("apps.exchange.views.build_latest_quote_gateway", return_value=gateway):
        page = client.get(reverse("converter"), {"convert": "1", **payload()})
        fragment = client.post(reverse("converter"), payload(), HTTP_HX_REQUEST="true")

    assert page.status_code == 200
    assert fragment.status_code == 200
    assert b"data-money-studio" not in page.content
    assert b"data-money-studio" not in fragment.content
    assert b'id="current-conversion-result"' in fragment.content
    assert len(gateway.calls) == 2


@pytest.mark.django_db
def test_replay_and_invalid_post_keep_money_studio_hidden(client, reference_data):
    with patch("apps.exchange.views.build_latest_quote_gateway") as rate_factory:
        replay = client.get(
            reverse("converter"),
            {"load": "1", "source_currency": "EUR", "destination_currency": "JPY"},
        )
        invalid = client.post(reverse("converter"), payload(amount="invalid"))

    assert replay.status_code == 200
    assert invalid.status_code == 422
    assert b"data-money-studio" not in replay.content
    assert b"data-money-studio" not in invalid.content
    rate_factory.assert_not_called()
