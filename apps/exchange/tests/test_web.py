from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.countries.models import Country, CountryCurrency, Currency
from apps.exchange.domain import (
    DEFAULT_SOURCE_POLICY,
    HistoricalObservationUnavailable,
    ObservationGranularity,
    RateQuote,
    RateSeries,
    RateSeriesGrouping,
    RateSeriesPoint,
)
from apps.exchange.providers.base import FxProviderUnavailable


class FakeGateway:
    def __init__(self, *, stale=False):
        self.stale = stale
        self.calls = []

    def get(self, base, quote, policy, *, now):
        self.calls.append((base, quote, policy))
        return (
            RateQuote(
                base_currency=base,
                quote_currency=quote,
                rate=Decimal("174.50") if (base, quote) == ("EUR", "JPY") else Decimal("0.0057"),
                requested_date=None,
                effective_date=date(2026, 9, 18),
                fetched_at=datetime(2026, 9, 20, 8, tzinfo=UTC),
                provider_policy=DEFAULT_SOURCE_POLICY,
                provider_keys=("ecb",),
                historical=False,
            ),
            self.stale,
        )


class UnavailableGateway:
    def get(self, *args, **kwargs):
        raise FxProviderUnavailable("down")


class FakeSeriesGateway:
    def __init__(self, *, stale=False):
        self.stale = stale
        self.calls = []

    def get(self, base, quote, start_date, end_date, grouping, policy, *, now):
        self.calls.append((base, quote, start_date, end_date, grouping, policy, now))
        midpoint = start_date + (end_date - start_date) // 2
        points = (
            RateSeriesPoint(start_date, Decimal("170.25"), ("ecb",)),
            RateSeriesPoint(midpoint, Decimal("178.40"), ("ecb",)),
            RateSeriesPoint(end_date, Decimal("174.50"), ("ecb",)),
        )
        return (
            RateSeries(
                base_currency=base,
                quote_currency=quote,
                start_date=start_date,
                end_date=end_date,
                grouping=grouping,
                points=points,
                fetched_at=datetime(2026, 9, 20, 8, tzinfo=UTC),
                provider_policy=policy,
                observation_granularity=ObservationGranularity.DAILY,
            ),
            self.stale,
        )


class FakeHistoricalGateway:
    def __init__(self, *, effective_date=None, granularity=ObservationGranularity.DAILY):
        self.effective_date = effective_date
        self.granularity = granularity
        self.calls = []

    def get(self, base, quote, requested_date, policy):
        self.calls.append((base, quote, requested_date, policy))
        effective = self.effective_date or requested_date
        return RateQuote(
            base_currency=base,
            quote_currency=quote,
            rate=Decimal("174.50"),
            requested_date=requested_date,
            effective_date=effective,
            fetched_at=datetime(2026, 9, 20, 8, tzinfo=UTC),
            provider_policy=DEFAULT_SOURCE_POLICY,
            provider_keys=("ecb",),
            historical=True,
            observation_granularity=self.granularity,
        )


@pytest.fixture(autouse=True)
def use_vite_dev_mode(settings):
    settings.VITE_DEV_SERVER_ENABLED = True


@pytest.fixture
def reference_data(db):
    fi = Country.objects.create(iso2="FI", iso3="FIN", name="Finland")
    jp = Country.objects.create(iso2="JP", iso3="JPN", name="Japan")
    eur = Currency.objects.create(code="EUR", name="Euro", symbol="€", minor_units=2)
    jpy = Currency.objects.create(code="JPY", name="Japanese yen", symbol="¥", minor_units=0)
    fim = Currency.objects.create(
        code="FIM",
        name="Finnish markka",
        symbol="mk",
        minor_units=2,
        is_active=False,
        active_to=date(2001, 12, 31),
        coverage_from=date(1972, 1, 1),
        coverage_to=date(2001, 12, 31),
        coverage_to_is_terminal=True,
        coverage_source="test-frankfurter",
    )
    CountryCurrency.objects.create(
        country=fi,
        currency=fim,
        is_primary=True,
        valid_to=date(2001, 12, 31),
        source="test",
    )
    CountryCurrency.objects.create(
        country=fi,
        currency=eur,
        is_primary=True,
        valid_from=date(2002, 1, 1),
        source="test",
    )
    CountryCurrency.objects.create(
        country=jp,
        currency=jpy,
        is_primary=True,
        source="test",
    )
    return fi, jp, eur, jpy, fim


def payload(**overrides):
    values = {
        "amount": "100.00",
        "source_country": "FI",
        "source_currency": "EUR",
        "destination_country": "JP",
        "destination_currency": "JPY",
    }
    values.update(overrides)
    return values


@pytest.mark.django_db
def test_initial_page_does_not_request_rate(client, reference_data):
    with patch("apps.exchange.views.build_latest_quote_gateway") as factory:
        response = client.get(reverse("converter"))

    assert response.status_code == 200
    assert b"Ready when you are" in response.content
    factory.assert_not_called()


@pytest.mark.django_db
def test_initial_converter_page_has_bounded_query_count(client, reference_data):
    with (
        patch("apps.exchange.views.build_latest_quote_gateway") as factory,
        CaptureQueriesContext(connection) as captured,
    ):
        response = client.get(reverse("converter"))

    assert response.status_code == 200
    assert len(captured) <= 6
    factory.assert_not_called()


@pytest.mark.django_db
def test_htmx_conversion_returns_fragment_and_pushes_bookmarkable_url(client, reference_data):
    gateway = FakeGateway()
    with patch("apps.exchange.views.build_latest_quote_gateway", return_value=gateway):
        response = client.post(
            reverse("converter"),
            payload(),
            HTTP_HX_REQUEST="true",
        )

    assert response.status_code == 200
    assert b"<html" not in response.content
    assert b'id="current-conversion-result"' in response.content
    assert b"17450" in response.content
    assert b"18 Sep 2026" in response.content
    assert b"Frankfurter" in response.content
    assert response["HX-Push-Url"].startswith("/?convert=1&")
    assert "HX-Request" in response.get("Vary", "")
    assert len(gateway.calls) == 1


@pytest.mark.django_db
def test_full_post_redirects_to_bookmarkable_get(client, reference_data):
    gateway = FakeGateway()
    with patch("apps.exchange.views.build_latest_quote_gateway", return_value=gateway):
        response = client.post(reverse("converter"), payload())

    assert response.status_code == 302
    assert response["Location"].startswith("/?convert=1&")


@pytest.mark.django_db
def test_invalid_amount_never_builds_provider_gateway(client, reference_data):
    with patch("apps.exchange.views.build_latest_quote_gateway") as factory:
        response = client.post(
            reverse("converter"),
            payload(amount="-1"),
            HTTP_HX_REQUEST="true",
        )

    assert response.status_code == 422
    assert b"zero or a positive amount" in response.content
    factory.assert_not_called()


@pytest.mark.django_db
def test_same_currency_uses_exact_one_without_gateway_call(client, reference_data):
    gateway = FakeGateway()
    with patch("apps.exchange.views.build_latest_quote_gateway", return_value=gateway):
        response = client.post(
            reverse("converter"),
            payload(
                destination_country="",
                destination_currency="EUR",
            ),
            HTTP_HX_REQUEST="true",
        )

    assert response.status_code == 200
    assert b"100.00" in response.content
    assert b"Exact same-currency rate" in response.content
    assert b"equals" in response.content
    assert b"Last synced" not in response.content
    assert gateway.calls == []


@pytest.mark.django_db
def test_stale_result_is_explicitly_labelled(client, reference_data):
    with patch(
        "apps.exchange.views.build_latest_quote_gateway",
        return_value=FakeGateway(stale=True),
    ):
        response = client.post(reverse("converter"), payload(), HTTP_HX_REQUEST="true")

    assert b"Cached reference" in response.content
    assert b"temporarily unavailable" in response.content
    assert b"Retry reference rate" in response.content


@pytest.mark.django_db
def test_provider_unavailable_preserves_form_without_numeric_result(client, reference_data):
    with patch(
        "apps.exchange.views.build_latest_quote_gateway",
        return_value=UnavailableGateway(),
    ):
        response = client.post(reverse("converter"), payload(), HTTP_HX_REQUEST="true")

    assert response.status_code == 503
    assert b"temporarily unavailable" in response.content
    assert b'value="100.00"' in response.content
    assert b"current-conversion-result" not in response.content


@pytest.mark.django_db
def test_swap_before_first_conversion_does_not_request_rate(client, reference_data):
    gateway = FakeGateway()
    with patch("apps.exchange.views.build_latest_quote_gateway", return_value=gateway):
        response = client.post(
            reverse("converter"),
            payload(action="swap", conversion_active="0"),
            HTTP_HX_REQUEST="true",
        )

    assert response.status_code == 200
    assert b"Japan" in response.content
    assert b"Finland" in response.content
    assert b'value="100.00"' in response.content
    assert b"current-conversion-result" not in response.content
    assert gateway.calls == []


@pytest.mark.django_db
def test_swap_after_success_refreshes_the_swapped_pair(client, reference_data):
    gateway = FakeGateway()
    with patch("apps.exchange.views.build_latest_quote_gateway", return_value=gateway):
        response = client.post(
            reverse("converter"),
            payload(action="swap", conversion_active="1"),
            HTTP_HX_REQUEST="true",
        )

    assert response.status_code == 200
    assert b"current-conversion-result" in response.content
    assert gateway.calls[0][0:2] == ("JPY", "EUR")


@pytest.mark.django_db
def test_picker_search_matches_country_currency_name_and_code(client, reference_data):
    response = client.get(reverse("picker_options"), {"side": "destination", "q": "yen"})

    assert response.status_code == 200
    assert b"Japanese yen" in response.content
    assert b'data-currency-code="JPY"' in response.content


@pytest.mark.django_db
def test_invalid_deep_link_currency_is_validation_state_not_500(client, reference_data):
    with patch("apps.exchange.views.build_latest_quote_gateway") as factory:
        response = client.get(
            reverse("converter"),
            {
                "convert": "1",
                **payload(destination_currency="ZZZ"),
            },
        )

    assert response.status_code == 200
    assert b"Select a valid choice" in response.content
    factory.assert_not_called()


@pytest.mark.django_db
def test_htmx_response_varies_on_history_restore_header(client, reference_data):
    response = client.get(reverse("converter"), HTTP_HX_REQUEST="true")

    vary = response.get("Vary", "")
    assert "HX-Request" in vary
    assert "HX-History-Restore-Request" in vary


@pytest.mark.django_db
def test_multiple_validation_errors_render_linked_summary(client, reference_data):
    with patch("apps.exchange.views.build_latest_quote_gateway") as factory:
        response = client.post(
            reverse("converter"),
            payload(amount="-1", destination_currency="ZZZ"),
            HTTP_HX_REQUEST="true",
        )

    assert response.status_code == 422
    assert b"Check these fields" in response.content
    assert b'href="#id_amount"' in response.content
    assert b'href="#id_destination_currency"' in response.content
    factory.assert_not_called()


@pytest.mark.django_db
def test_failed_active_refresh_keeps_enhanced_mode_enabled(client, reference_data):
    with patch("apps.exchange.views.build_latest_quote_gateway") as factory:
        response = client.post(
            reverse("converter"),
            payload(amount="-1", conversion_active="1"),
            HTTP_HX_REQUEST="true",
        )

    assert response.status_code == 422
    assert b'data-has-result="true"' in response.content
    assert b'name="conversion_active"' in response.content
    assert b'value="1"' in response.content
    factory.assert_not_called()


@pytest.mark.django_db
def test_failed_active_htmx_refresh_emits_preserve_placeholder(client, reference_data):
    with patch("apps.exchange.views.build_latest_quote_gateway") as factory:
        response = client.post(
            reverse("converter"),
            payload(amount="-1", conversion_active="1"),
            HTTP_HX_REQUEST="true",
        )

    assert response.status_code == 422
    assert b'id="conversion-result-region"' in response.content
    assert b'hx-preserve="true"' in response.content
    factory.assert_not_called()


@pytest.mark.django_db
def test_successful_active_htmx_refresh_never_emits_preserve_placeholder(client, reference_data):
    gateway = FakeGateway()
    with patch("apps.exchange.views.build_latest_quote_gateway", return_value=gateway):
        response = client.post(
            reverse("converter"),
            payload(conversion_active="1"),
            HTTP_HX_REQUEST="true",
        )

    assert response.status_code == 200
    assert b'id="current-conversion-result"' in response.content
    assert b'hx-preserve="true"' not in response.content


@pytest.mark.django_db
def test_historical_htmx_conversion_preserves_requested_and_observation_dates(
    client, reference_data
):
    gateway = FakeHistoricalGateway()
    with patch("apps.exchange.views.build_historical_quote_gateway", return_value=gateway):
        response = client.post(
            reverse("converter"),
            payload(rate_mode="historical", requested_date="1998-06-15"),
            HTTP_HX_REQUEST="true",
        )

    assert response.status_code == 200
    assert b"Historical reference" in response.content
    assert b"Requested date" in response.content
    assert b"15 Jun 1998" in response.content
    assert b"Observation date" in response.content
    assert "rate_mode=historical" in response["HX-Push-Url"]
    assert "requested_date=1998-06-15" in response["HX-Push-Url"]
    assert gateway.calls[0][2] == date(1998, 6, 15)
    assert b"Finland used Finnish markka" in response.content
    assert b"Use FIM" in response.content
    assert b"explicit EUR selection has not been changed" in response.content


@pytest.mark.django_db
def test_historical_previous_observation_is_explicit(client, reference_data):
    gateway = FakeHistoricalGateway(effective_date=date(1998, 6, 12))
    with patch("apps.exchange.views.build_historical_quote_gateway", return_value=gateway):
        response = client.post(
            reverse("converter"),
            payload(rate_mode="historical", requested_date="1998-06-14"),
            HTTP_HX_REQUEST="true",
        )

    assert response.status_code == 200
    assert b"Previous available observation" in response.content
    assert b"14 Jun 1998" in response.content
    assert b"12 Jun 1998" in response.content


@pytest.mark.django_db
def test_future_historical_date_never_builds_provider_gateway(client, reference_data):
    with patch("apps.exchange.views.build_historical_quote_gateway") as factory:
        response = client.post(
            reverse("converter"),
            payload(rate_mode="historical", requested_date="2999-01-01"),
            HTTP_HX_REQUEST="true",
        )

    assert response.status_code == 422
    assert b"Historical date cannot be in the future" in response.content
    factory.assert_not_called()


@pytest.mark.django_db
def test_historical_picker_exposes_archived_currency_for_selected_date(client, reference_data):
    response = client.get(
        reverse("picker_options"),
        {
            "side": "source",
            "q": "markka",
            "rate_mode": "historical",
            "requested_date": "1998-06-15",
        },
    )

    assert response.status_code == 200
    assert b"Finnish markka" in response.content
    assert b"FIM" in response.content


@pytest.mark.django_db
def test_current_picker_keeps_archived_currency_hidden(client, reference_data):
    response = client.get(
        reverse("picker_options"),
        {"side": "source", "q": "markka"},
    )

    assert response.status_code == 200
    assert b"Finnish markka" not in response.content


@pytest.mark.django_db
def test_historical_currency_suggestion_action_replays_conversion_with_suggested_code(
    client, reference_data
):
    gateway = FakeHistoricalGateway()
    with patch("apps.exchange.views.build_historical_quote_gateway", return_value=gateway):
        response = client.post(
            reverse("converter"),
            payload(
                rate_mode="historical",
                requested_date="1998-06-15",
                historical_currency_action="source:FIM",
            ),
            HTTP_HX_REQUEST="true",
        )

    assert response.status_code == 200
    assert gateway.calls[0][0:2] == ("FIM", "JPY")
    assert b"Finnish markka" in response.content
    assert b"Use FIM" not in response.content


@pytest.mark.django_db
def test_retired_currency_is_out_of_coverage_before_provider_call(client, reference_data):
    with patch("apps.exchange.views.build_historical_quote_gateway") as factory:
        response = client.post(
            reverse("converter"),
            payload(
                rate_mode="historical",
                requested_date="2002-01-01",
                source_currency="FIM",
            ),
            HTTP_HX_REQUEST="true",
        )

    assert response.status_code == 422
    assert b"outside known historical coverage" in response.content
    assert b"FIM was already retired" in response.content
    assert b"Use EUR" in response.content
    factory.assert_not_called()


@pytest.mark.django_db
def test_provider_coverage_start_blocks_request_before_provider_call(client, reference_data):
    eur = Currency.objects.get(code="EUR")
    eur.coverage_from = date(2000, 1, 1)
    eur.coverage_source = "test-frankfurter"
    eur.save(update_fields=["coverage_from", "coverage_source"])

    with patch("apps.exchange.views.build_historical_quote_gateway") as factory:
        response = client.post(
            reverse("converter"),
            payload(rate_mode="historical", requested_date="1998-06-15"),
            HTTP_HX_REQUEST="true",
        )

    assert response.status_code == 422
    assert b"Known provider coverage starts 01 Jan 2000" in response.content
    factory.assert_not_called()


@pytest.mark.django_db
def test_monthly_historical_observation_never_claims_daily_precision(client, reference_data):
    gateway = FakeHistoricalGateway(
        effective_date=date(2026, 9, 1),
        granularity=ObservationGranularity.MONTHLY,
    )
    with patch("apps.exchange.views.build_historical_quote_gateway", return_value=gateway):
        response = client.post(
            reverse("converter"),
            payload(rate_mode="historical", requested_date="2026-09-20"),
            HTTP_HX_REQUEST="true",
        )

    assert response.status_code == 200
    assert b"Monthly historical observation" in response.content
    assert b"Observation frequency" in response.content
    assert b"Monthly" in response.content
    assert b"Previous available observation" not in response.content


@pytest.mark.django_db
def test_archived_currency_in_latest_mode_gets_transition_guidance_without_provider(
    client, reference_data
):
    with patch("apps.exchange.views.build_latest_quote_gateway") as factory:
        response = client.get(
            reverse("converter"),
            {
                "convert": "1",
                **payload(source_currency="FIM"),
            },
        )

    assert response.status_code == 200
    assert b"Finnish markka (FIM) is archived" in response.content
    assert b"Switch Rate date to Historical date" in response.content
    factory.assert_not_called()


@pytest.mark.django_db
def test_archived_currency_in_latest_mode_post_is_422_and_never_builds_provider(
    client, reference_data
):
    with patch("apps.exchange.views.build_latest_quote_gateway") as factory:
        response = client.post(
            reverse("converter"),
            payload(source_currency="FIM"),
            HTTP_HX_REQUEST="true",
        )

    assert response.status_code == 422
    assert b"Finnish markka (FIM) is archived" in response.content
    factory.assert_not_called()


@pytest.mark.django_db
def test_historical_deep_link_reproduces_requested_state(client, reference_data):
    gateway = FakeHistoricalGateway(effective_date=date(1998, 6, 12))
    with patch("apps.exchange.views.build_historical_quote_gateway", return_value=gateway):
        response = client.get(
            reverse("converter"),
            {
                "convert": "1",
                "amount": "100.00",
                "source_country": "FI",
                "source_currency": "FIM",
                "destination_country": "JP",
                "destination_currency": "JPY",
                "rate_mode": "historical",
                "requested_date": "1998-06-15",
            },
        )

    assert response.status_code == 200
    assert b"<html" in response.content
    assert b"Finnish markka" in response.content
    assert b"15 Jun 1998" in response.content
    assert b"12 Jun 1998" in response.content
    assert b"Previous available observation" in response.content
    assert gateway.calls == [("FIM", "JPY", date(1998, 6, 15), DEFAULT_SOURCE_POLICY)]


@pytest.mark.django_db
def test_historical_full_post_redirect_deep_link_preserves_date_and_archived_currency(
    client, reference_data
):
    gateway = FakeHistoricalGateway()
    with patch("apps.exchange.views.build_historical_quote_gateway", return_value=gateway):
        response = client.post(
            reverse("converter"),
            payload(
                rate_mode="historical",
                requested_date="1998-06-15",
                source_currency="FIM",
            ),
        )

    assert response.status_code == 302
    location = response["Location"]
    assert "source_currency=FIM" in location
    assert "rate_mode=historical" in location
    assert "requested_date=1998-06-15" in location


@pytest.mark.django_db
def test_historical_htmx_and_full_get_render_equivalent_numeric_semantics(client, reference_data):
    htmx_gateway = FakeHistoricalGateway(effective_date=date(1998, 6, 12))
    with patch("apps.exchange.views.build_historical_quote_gateway", return_value=htmx_gateway):
        fragment = client.post(
            reverse("converter"),
            payload(rate_mode="historical", requested_date="1998-06-15"),
            HTTP_HX_REQUEST="true",
        )

    full_gateway = FakeHistoricalGateway(effective_date=date(1998, 6, 12))
    with patch("apps.exchange.views.build_historical_quote_gateway", return_value=full_gateway):
        full = client.get(
            reverse("converter"),
            {
                "convert": "1",
                **payload(rate_mode="historical", requested_date="1998-06-15"),
            },
        )

    for response in (fragment, full):
        assert response.status_code == 200
        assert b"17450" in response.content
        assert b"15 Jun 1998" in response.content
        assert b"12 Jun 1998" in response.content
        assert b"Previous available observation" in response.content


@pytest.mark.django_db
def test_historical_series_page_uses_bounded_one_year_range(client, reference_data):
    gateway = FakeSeriesGateway()
    with (
        patch("apps.exchange.views.build_historical_series_gateway", return_value=gateway),
        patch("apps.exchange.views.build_historical_quote_gateway") as quote_factory,
    ):
        response = client.get(
            reverse("historical_series"),
            {
                "base": "EUR",
                "quote": "JPY",
                "selected_date": "2026-09-18",
                "requested_date": "2026-09-20",
                "period": "1y",
            },
        )

    assert response.status_code == 200
    assert b"Historical rate trend" in response.content
    assert b"EUR" in response.content
    assert b"JPY" in response.content
    assert b"View data table" in response.content
    assert b"178.4" in response.content
    assert b"170.25" in response.content
    assert len(gateway.calls) == 1
    assert gateway.calls[0][2] == date(2025, 9, 18)
    assert gateway.calls[0][3] == date(2026, 9, 18)
    assert gateway.calls[0][4] is RateSeriesGrouping.DAILY
    quote_factory.assert_not_called()


@pytest.mark.django_db
def test_historical_series_observation_gap_is_a_validation_state(client, reference_data):
    with patch(
        "apps.exchange.views.get_rate_series",
        side_effect=HistoricalObservationUnavailable("outside accepted gap"),
    ):
        response = client.get(
            reverse("historical_series"),
            {
                "base": "EUR",
                "quote": "JPY",
                "selected_date": "2026-09-18",
                "period": "1y",
            },
            HTTP_HX_REQUEST="true",
        )

    assert response.status_code == 422
    assert b"cannot confirm the selected observation" in response.content
    assert b"single-date conversion remains intact" in response.content


@pytest.mark.django_db
def test_historical_series_htmx_returns_fragment(client, reference_data):
    gateway = FakeSeriesGateway()
    with patch("apps.exchange.views.build_historical_series_gateway", return_value=gateway):
        response = client.get(
            reverse("historical_series"),
            {
                "base": "EUR",
                "quote": "JPY",
                "selected_date": "2026-09-18",
                "period": "1y",
            },
            HTTP_HX_REQUEST="true",
        )

    assert response.status_code == 200
    assert b"<html" not in response.content
    assert b'id="historical-trend"' in response.content
    assert "HX-Request" in response.get("Vary", "")
    assert b"View data table" in response.content


@pytest.mark.django_db
def test_custom_historical_series_range_preserves_selected_observation(client, reference_data):
    gateway = FakeSeriesGateway()
    with patch("apps.exchange.views.build_historical_series_gateway", return_value=gateway):
        response = client.get(
            reverse("historical_series"),
            {
                "base": "EUR",
                "quote": "JPY",
                "selected_date": "2026-09-18",
                "period": "custom",
                "start_date": "2024-01-01",
                "end_date": "2026-09-18",
            },
        )

    assert response.status_code == 200
    assert gateway.calls[0][2] == date(2024, 1, 1)
    assert gateway.calls[0][3] == date(2026, 9, 18)
    assert gateway.calls[0][4] is RateSeriesGrouping.WEEK


@pytest.mark.django_db
def test_invalid_historical_series_range_never_builds_provider(client, reference_data):
    with patch("apps.exchange.views.build_historical_series_gateway") as factory:
        response = client.get(
            reverse("historical_series"),
            {
                "base": "EUR",
                "quote": "JPY",
                "selected_date": "2026-09-18",
                "period": "custom",
                "start_date": "2010-01-01",
                "end_date": "2026-09-18",
            },
        )

    assert response.status_code == 422
    assert b"valid historical trend range" in response.content
    factory.assert_not_called()


@pytest.mark.django_db
def test_historical_series_provider_failure_keeps_single_date_conversion_independent(
    client, reference_data
):
    with patch(
        "apps.exchange.views.build_historical_series_gateway",
        return_value=UnavailableGateway(),
    ):
        response = client.get(
            reverse("historical_series"),
            {
                "base": "EUR",
                "quote": "JPY",
                "selected_date": "2026-09-18",
                "period": "1y",
            },
        )

    assert response.status_code == 503
    assert b"Historical series is unavailable" in response.content
    assert b"Single-date conversion remains intact" in response.content


@pytest.mark.django_db
def test_historical_conversion_exposes_trend_entry_for_actual_observation(client, reference_data):
    gateway = FakeHistoricalGateway(effective_date=date(1998, 6, 12))
    with patch("apps.exchange.views.build_historical_quote_gateway", return_value=gateway):
        response = client.post(
            reverse("converter"),
            payload(rate_mode="historical", requested_date="1998-06-14"),
            HTTP_HX_REQUEST="true",
        )

    assert response.status_code == 200
    assert b"View historical trend" in response.content
    assert b"selected_date=1998-06-12" in response.content
    assert b"requested_date=1998-06-14" in response.content

    content = response.content
    assert b'class="qa-destination-context"' not in content
    assert b"current local context for Japan" in content
    result_index = content.index(b'id="current-conversion-result"')
    story_index = content.index(b'class="qa-story-entry"')
    historical_index = content.index(b'class="qa-historical-trend-entry"')
    current_context_index = content.index(b'class="qa-current-context-entry"')
    save_index = content.index(b'class="qa-local-save-control"')
    assert result_index < story_index < historical_index < current_context_index < save_index


@pytest.mark.django_db
def test_same_currency_historical_result_does_not_offer_redundant_trend(client, reference_data):
    with patch("apps.exchange.views.build_historical_quote_gateway") as factory:
        response = client.post(
            reverse("converter"),
            payload(
                rate_mode="historical",
                requested_date="1998-06-14",
                destination_country="FI",
                destination_currency="EUR",
            ),
            HTTP_HX_REQUEST="true",
        )

    assert response.status_code == 200
    assert b"Historical exact 1:1" in response.content
    assert b"View historical trend" not in response.content
    factory.assert_not_called()


@pytest.mark.django_db
def test_historical_series_amount_builds_then_now_from_series_observation(client, reference_data):
    series_gateway = FakeSeriesGateway()
    latest_gateway = FakeGateway()
    with (
        patch(
            "apps.exchange.views.build_historical_series_gateway",
            return_value=series_gateway,
        ),
        patch(
            "apps.exchange.views.build_latest_quote_gateway",
            return_value=latest_gateway,
        ),
        patch("apps.exchange.views.build_historical_quote_gateway") as historical_factory,
    ):
        response = client.get(
            reverse("historical_series"),
            {
                "base": "EUR",
                "quote": "JPY",
                "selected_date": "2026-09-18",
                "period": "1y",
                "amount": "100.00",
            },
        )

    assert response.status_code == 200
    assert b"Same amount, two reference observations" in response.content
    assert b"Latest reference" in response.content
    assert len(latest_gateway.calls) == 1
    historical_factory.assert_not_called()


@pytest.mark.django_db
def test_historical_series_latest_comparison_failure_is_non_fatal(client, reference_data):
    with (
        patch(
            "apps.exchange.views.build_historical_series_gateway",
            return_value=FakeSeriesGateway(),
        ),
        patch(
            "apps.exchange.views.build_latest_quote_gateway",
            return_value=UnavailableGateway(),
        ),
    ):
        response = client.get(
            reverse("historical_series"),
            {
                "base": "EUR",
                "quote": "JPY",
                "selected_date": "2026-09-18",
                "period": "1y",
                "amount": "100.00",
            },
        )

    assert response.status_code == 200
    assert b"Latest reference comparison is temporarily unavailable" in response.content
    assert b"Historical rate trend" in response.content


@pytest.mark.django_db
def test_historical_series_invalid_comparison_amount_keeps_trend_valid(client, reference_data):
    with (
        patch(
            "apps.exchange.views.build_historical_series_gateway",
            return_value=FakeSeriesGateway(),
        ),
        patch("apps.exchange.views.build_latest_quote_gateway") as latest_factory,
    ):
        response = client.get(
            reverse("historical_series"),
            {
                "base": "EUR",
                "quote": "JPY",
                "selected_date": "2026-09-18",
                "period": "1y",
                "amount": "12.345",
            },
        )

    assert response.status_code == 200
    assert b"amount is invalid" in response.content
    latest_factory.assert_not_called()


@pytest.mark.django_db
def test_historical_series_archived_pair_skips_latest_comparison(client, reference_data):
    with (
        patch(
            "apps.exchange.views.build_historical_series_gateway",
            return_value=FakeSeriesGateway(),
        ),
        patch("apps.exchange.views.build_latest_quote_gateway") as latest_factory,
    ):
        response = client.get(
            reverse("historical_series"),
            {
                "base": "FIM",
                "quote": "JPY",
                "selected_date": "1998-06-15",
                "period": "1y",
                "amount": "100.00",
            },
        )

    assert response.status_code == 200
    assert b"FIM is archived" in response.content
    assert b"no current-market interpretation" in response.content
    latest_factory.assert_not_called()


@pytest.mark.django_db
def test_historical_series_missing_exact_selected_point_degrades_to_notice(client, reference_data):
    class MissingSelectedSeriesGateway(FakeSeriesGateway):
        def get(self, base, quote, start_date, end_date, grouping, policy, *, now):
            self.calls.append((base, quote, start_date, end_date, grouping, policy, now))
            return (
                RateSeries(
                    base_currency=base,
                    quote_currency=quote,
                    start_date=start_date,
                    end_date=end_date,
                    grouping=grouping,
                    points=(RateSeriesPoint(start_date, Decimal("170.25"), ("ecb",)),),
                    fetched_at=datetime(2026, 9, 20, 8, tzinfo=UTC),
                    provider_policy=policy,
                    observation_granularity=ObservationGranularity.DAILY,
                ),
                False,
            )

    with (
        patch(
            "apps.exchange.views.build_historical_series_gateway",
            return_value=MissingSelectedSeriesGateway(),
        ),
        patch("apps.exchange.views.build_latest_quote_gateway") as latest_factory,
    ):
        response = client.get(
            reverse("historical_series"),
            {
                "base": "EUR",
                "quote": "JPY",
                "selected_date": "2026-09-18",
                "period": "1y",
                "amount": "100.00",
            },
        )

    assert response.status_code == 200
    assert b"selected observation is not present in the loaded series" in response.content
    latest_factory.assert_not_called()
