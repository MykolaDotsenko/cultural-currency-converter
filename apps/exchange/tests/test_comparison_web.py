from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
from urllib.parse import parse_qs, quote, urlparse

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from apps.countries.models import City, Country, CountryCurrency, Currency
from apps.culture.models import CulturalProfile, TypicalPrice
from apps.exchange.ai.packet_tokens import GroundedPacketTokenError
from apps.exchange.ai.service import RuntimeExplanationService
from apps.exchange.comparison_snapshot import load_saved_comparison_token
from apps.exchange.domain import DEFAULT_SOURCE_POLICY, RateQuote
from apps.exchange.providers.base import FxProviderUnavailable


@pytest.fixture(autouse=True)
def use_vite_dev_mode(settings):
    settings.VITE_DEV_SERVER_ENABLED = True


class ComparisonGateway:
    def __init__(self, *, fail_quote: str = "") -> None:
        self.calls: list[tuple[str, str]] = []
        self.fail_quote = fail_quote

    def get(self, base, quote, policy, *, now):
        self.calls.append((base, quote))
        if quote == self.fail_quote:
            raise FxProviderUnavailable("upstream comparison test failure")

        rates = {
            "JPY": Decimal("174.50"),
            "NOK": Decimal("11.80"),
            "EUR": Decimal("1"),
        }
        return (
            RateQuote(
                base_currency=base,
                quote_currency=quote,
                rate=rates[quote],
                requested_date=None,
                effective_date=timezone.localdate(),
                fetched_at=now,
                provider_policy=DEFAULT_SOURCE_POLICY,
                provider_keys=("ecb",),
                historical=False,
            ),
            False,
        )


@pytest.fixture
def comparison_reference_data(db):
    fi = Country.objects.create(iso2="FI", iso3="FIN", name="Finland")
    jp = Country.objects.create(iso2="JP", iso3="JPN", name="Japan")
    no = Country.objects.create(iso2="NO", iso3="NOR", name="Norway")

    eur = Currency.objects.create(code="EUR", name="Euro", symbol="€", minor_units=2)
    jpy = Currency.objects.create(code="JPY", name="Japanese yen", symbol="¥", minor_units=0)
    nok = Currency.objects.create(code="NOK", name="Norwegian krone", symbol="kr", minor_units=2)

    for country, currency in ((fi, eur), (jp, jpy), (no, nok)):
        CountryCurrency.objects.create(
            country=country,
            currency=currency,
            is_primary=True,
            source="test",
        )

    tokyo = City.objects.create(country=jp, slug="tokyo", name="Tokyo")
    verified_at = timezone.now()
    observed_at = timezone.localdate() - timedelta(days=5)

    for country, summary in (
        (jp, "Cards are common in Tokyo; keep some cash for smaller situations."),
        (no, "Cards are widely used in Norway."),
    ):
        CulturalProfile.objects.create(
            country=country,
            summary=summary,
            payment_customs="Cards are commonly accepted for routine purchases.",
            cash_usage="Carry cash only when the local situation calls for it.",
            tipping="Follow reviewed local tipping customs.",
            atm_notes="Use clearly identified ATMs and review disclosed fees.",
            dcc_warning="If DCC is offered, review the local-currency option carefully.",
            source_name="Official payment source",
            source_url="https://example.com/payment-context",
            verified_at=verified_at,
            is_published=True,
        )

    japan_prices = (
        ("coffee", "Coffee", Decimal("500"), Decimal("700")),
        ("casual_meal", "Casual meal", Decimal("1200"), Decimal("1800")),
        ("transit", "Local transit", Decimal("180"), Decimal("300")),
    )
    norway_prices = (
        ("coffee", "Coffee", Decimal("45"), Decimal("65")),
        ("casual_meal", "Casual meal", Decimal("180"), Decimal("280")),
        ("transit", "Local transit", Decimal("40"), Decimal("60")),
    )

    for order, (category, label, low, high) in enumerate(japan_prices, start=1):
        TypicalPrice.objects.create(
            country=jp,
            city_ref=tokyo,
            category=category,
            label=label,
            amount_low=low,
            amount_high=high,
            currency=jpy,
            source_name="Tokyo price source",
            source_url="https://example.com/tokyo-prices",
            observed_at=observed_at,
            verified_at=verified_at,
            source_class="curated_factual",
            confidence="high",
            display_order=order,
            is_published=True,
        )

    for order, (category, label, low, high) in enumerate(norway_prices, start=1):
        TypicalPrice.objects.create(
            country=no,
            category=category,
            label=label,
            amount_low=low,
            amount_high=high,
            currency=nok,
            source_name="Norway price source",
            source_url="https://example.com/norway-prices",
            observed_at=observed_at,
            verified_at=verified_at,
            source_class="curated_factual",
            confidence="high",
            display_order=order,
            is_published=True,
        )

    return {
        "fi": fi,
        "jp": jp,
        "no": no,
        "eur": eur,
        "jpy": jpy,
        "nok": nok,
        "tokyo": tokyo,
    }


def _payload(**overrides):
    values = {
        "amount": "500",
        "source_currency": "EUR",
        "left_destination": "JP:tokyo",
        "right_destination": "NO",
        "duration_days": "3",
        "travelers": "1",
        "units_coffee": "1",
        "units_casual_meal": "2",
        "units_transit": "2",
    }
    values.update(overrides)
    return values


@pytest.mark.django_db
def test_comparison_get_is_provider_free(client, comparison_reference_data):
    with patch("apps.exchange.views.build_latest_quote_gateway") as provider_factory:
        response = client.get(reverse("destination_comparison"))

    assert response.status_code == 200
    assert b"Same money. Two places. Visible assumptions." in response.content
    assert b"Tokyo, Japan" in response.content
    assert b"Norway" in response.content
    assert b"Rates are requested only after you submit." in response.content
    provider_factory.assert_not_called()


@pytest.mark.django_db
def test_comparison_get_prefills_one_canonical_destination_without_provider_call(
    client,
    comparison_reference_data,
):
    with patch("apps.exchange.views.build_latest_quote_gateway") as provider_factory:
        response = client.get(
            reverse("destination_comparison"),
            {"left_destination": "JP:tokyo"},
        )

    assert response.status_code == 200
    assert response.context["form"]["left_destination"].value() == "JP:tokyo"
    assert response.context["form"]["right_destination"].value() in (None, "")
    provider_factory.assert_not_called()


@pytest.mark.django_db
def test_comparison_get_reopens_all_saved_inputs_without_provider_call(
    client,
    comparison_reference_data,
):
    query = _payload(
        amount="725.50",
        duration_days="8",
        travelers="3",
        units_coffee="1.5",
        units_casual_meal="1",
        units_transit="4",
    )

    with patch("apps.exchange.views.build_latest_quote_gateway") as provider_factory:
        response = client.get(reverse("destination_comparison"), query)

    assert response.status_code == 200
    form = response.context["form"]
    assert form["amount"].value() == "725.50"
    assert form["source_currency"].value() == "EUR"
    assert form["left_destination"].value() == "JP:tokyo"
    assert form["right_destination"].value() == "NO"
    assert form["duration_days"].value() == "8"
    assert form["travelers"].value() == "3"
    assert form["units_coffee"].value() == "1.5"
    assert form["units_casual_meal"].value() == "1"
    assert form["units_transit"].value() == "4"
    assert response.context["comparison"] is None
    assert response.context["comparison_save_token"] == ""
    provider_factory.assert_not_called()


@pytest.mark.django_db
def test_successful_signed_in_comparison_exposes_signed_input_only_save_action(
    client,
    comparison_reference_data,
):
    user = get_user_model().objects.create_user(
        username="comparison-owner",
        password="StrongPass-482!",
    )
    client.force_login(user)
    gateway = ComparisonGateway()

    with patch("apps.exchange.views.build_latest_quote_gateway", return_value=gateway):
        response = client.post(reverse("destination_comparison"), _payload())

    assert response.status_code == 200
    token = response.context["comparison_save_token"]
    snapshot = load_saved_comparison_token(token)
    assert snapshot.source_amount == Decimal("500.00")
    assert snapshot.source_currency_code == "EUR"
    assert snapshot.left_destination == "JP:tokyo"
    assert snapshot.right_destination == "NO"
    assert snapshot.assumptions.duration_days == 3
    assert snapshot.assumptions.travelers == 1
    assert b'action="/saved/comparisons/create/"' in response.content
    assert b'name="comparison_save_token"' in response.content
    assert b"Save the inputs, not today" in response.content


@pytest.mark.django_db
def test_anonymous_comparison_result_offers_sign_in_without_auto_persistence(
    client,
    comparison_reference_data,
):
    gateway = ComparisonGateway()

    with patch("apps.exchange.views.build_latest_quote_gateway", return_value=gateway):
        response = client.post(reverse("destination_comparison"), _payload())

    assert response.status_code == 200
    assert b"Sign in to save comparisons" in response.content
    assert b'action="/saved/comparisons/create/"' not in response.content
    body = response.content.decode()
    reopen_url = response.context["comparison_reopen_url"]
    parsed_reopen = urlparse(reopen_url)
    params = parse_qs(parsed_reopen.query)
    assert parsed_reopen.path == reverse("destination_comparison")
    assert params["amount"] == ["500"]
    assert params["source_currency"] == ["EUR"]
    assert params["left_destination"] == ["JP:tokyo"]
    assert params["right_destination"] == ["NO"]
    assert params["duration_days"] == ["3"]
    assert params["travelers"] == ["1"]
    assert "rate" not in params
    assert "result" not in params
    expected_href = f"{reverse('login')}?next={quote(reopen_url)}"
    assert f'href="{expected_href}"' in body


@pytest.mark.django_db
def test_comparison_post_uses_two_trusted_conversions_and_preserves_scope(
    client,
    comparison_reference_data,
):
    gateway = ComparisonGateway()

    with patch(
        "apps.exchange.views.build_latest_quote_gateway",
        return_value=gateway,
    ) as provider_factory:
        response = client.post(reverse("destination_comparison"), _payload())

    assert response.status_code == 200
    assert provider_factory.call_count == 1
    assert gateway.calls == [("EUR", "JPY"), ("EUR", "NOK")]

    body = response.content
    assert b"Tokyo, Japan" in body
    assert b"Norway" in body
    assert b"87250" in body
    assert b"5900.00" in body
    assert body.count(b"ECB") >= 2
    assert b"Tokyo price source" in body
    assert b"Norway price source" in body
    assert b"City scope" in body
    assert b"Country scope" in body
    assert b"No winner is calculated." in body
    assert b"purchasing-power-parity" in body


@pytest.mark.django_db
def test_comparison_partial_coverage_keeps_known_rows_and_names_missing_category(
    client,
    comparison_reference_data,
):
    TypicalPrice.objects.filter(
        country=comparison_reference_data["no"],
        category="transit",
    ).delete()
    gateway = ComparisonGateway()

    with patch("apps.exchange.views.build_latest_quote_gateway", return_value=gateway):
        response = client.post(reverse("destination_comparison"), _payload())

    assert response.status_code == 200
    assert b"Coverage is partial." in response.content
    assert b"Missing: Transit" in response.content
    assert b"Norway price source" in response.content


@pytest.mark.django_db
def test_same_destination_is_rejected_before_any_rate_request(
    client,
    comparison_reference_data,
):
    with patch("apps.exchange.views.build_latest_quote_gateway") as provider_factory:
        response = client.post(
            reverse("destination_comparison"),
            _payload(right_destination="JP:tokyo"),
        )

    assert response.status_code == 422
    assert b"Choose a different destination scope." in response.content
    provider_factory.assert_not_called()


@pytest.mark.django_db
def test_comparison_uses_source_currency_precision_before_rate_request(
    client,
    comparison_reference_data,
):
    with patch("apps.exchange.views.build_latest_quote_gateway") as provider_factory:
        response = client.post(
            reverse("destination_comparison"),
            _payload(amount="1.001"),
        )

    assert response.status_code == 422
    assert b"This amount is ambiguous" in response.content
    provider_factory.assert_not_called()


@pytest.mark.django_db
def test_second_rate_failure_returns_neutral_error_without_leaking_provider_detail(
    client,
    comparison_reference_data,
):
    gateway = ComparisonGateway(fail_quote="NOK")

    with patch("apps.exchange.views.build_latest_quote_gateway", return_value=gateway):
        response = client.post(reverse("destination_comparison"), _payload())

    assert response.status_code == 503
    assert gateway.calls == [("EUR", "JPY"), ("EUR", "NOK")]
    assert b"Destination B reference rate is unavailable" in response.content
    assert b"Nothing has been inferred for the unavailable side" in response.content
    assert b"upstream comparison test failure" not in response.content
    assert b"Side-by-side context" not in response.content


@pytest.mark.django_db
def test_comparison_field_descriptions_have_rendered_targets(
    client,
    comparison_reference_data,
):
    response = client.get(reverse("destination_comparison"))

    assert response.status_code == 200
    assert b'aria-describedby="units_coffee-hint"' in response.content
    assert b'id="units_coffee-hint"' in response.content
    assert b'id="duration_days-hint"' in response.content
    assert b'id="travelers-hint"' in response.content


@pytest.mark.django_db
def test_comparison_result_exposes_only_signed_grounded_ai_prompts(
    client,
    comparison_reference_data,
    settings,
):
    settings.AI_RUNTIME_EXPLANATION_ENABLED = True
    gateway = ComparisonGateway()

    with patch("apps.exchange.views.build_latest_quote_gateway", return_value=gateway):
        response = client.post(reverse("destination_comparison"), _payload())

    assert response.status_code == 200
    ai = response.context["comparison"]["ai_explanation"]
    assert tuple(prompt["id"] for prompt in ai["prompts"]) == (
        "comparison_overview",
        "comparison_coverage",
        "comparison_payment",
    )
    assert b"signed comparison facts only" in response.content
    assert b'name="grounded_explanation_token"' in response.content
    assert b'name="prompt_id"' not in response.content
    assert gateway.calls == [("EUR", "JPY"), ("EUR", "NOK")]


@pytest.mark.django_db
def test_comparison_ai_builtin_fallback_never_requests_another_fx_quote(
    client,
    comparison_reference_data,
    settings,
):
    settings.AI_RUNTIME_EXPLANATION_ENABLED = True
    gateway = ComparisonGateway()

    with patch("apps.exchange.views.build_latest_quote_gateway", return_value=gateway):
        result_response = client.post(reverse("destination_comparison"), _payload())

    token = result_response.context["comparison"]["ai_explanation"]["prompts"][0]["token"]
    disabled_service = RuntimeExplanationService(
        enabled=False,
        model="disabled-test",
        drafter=None,
    )

    with (
        patch(
            "apps.exchange.views.build_contextual_explanation_service",
            return_value=disabled_service,
        ),
        patch("apps.exchange.views.build_latest_quote_gateway") as fx_factory,
    ):
        response = client.post(
            reverse("comparison_explanation"),
            {"grounded_explanation_token": token},
            HTTP_HX_REQUEST="true",
        )

    assert response.status_code == 200
    assert b"Built-in explanation" in response.content
    assert b"500 EUR" in response.content
    assert b"Tokyo, Japan" in response.content
    assert b"Norway" in response.content
    assert b"Live AI is unavailable" in response.content
    assert b"no winner" in response.content.lower()
    fx_factory.assert_not_called()


@pytest.mark.django_db
def test_comparison_ai_rejects_tampered_packet_before_service_creation(
    client,
    comparison_reference_data,
    settings,
):
    settings.AI_RUNTIME_EXPLANATION_ENABLED = True

    with patch("apps.exchange.views.build_contextual_explanation_service") as service_factory:
        response = client.post(
            reverse("comparison_explanation"),
            {"grounded_explanation_token": "tampered"},
            HTTP_HX_REQUEST="true",
        )

    assert response.status_code == 422
    assert b"no longer valid" in response.content
    service_factory.assert_not_called()


@pytest.mark.django_db
def test_comparison_ai_has_no_javascript_full_page_fallback(
    client,
    comparison_reference_data,
    settings,
):
    settings.AI_RUNTIME_EXPLANATION_ENABLED = True
    gateway = ComparisonGateway()

    with patch("apps.exchange.views.build_latest_quote_gateway", return_value=gateway):
        result_response = client.post(reverse("destination_comparison"), _payload())

    token = result_response.context["comparison"]["ai_explanation"]["prompts"][1]["token"]
    disabled_service = RuntimeExplanationService(
        enabled=False,
        model="disabled-test",
        drafter=None,
    )

    with patch(
        "apps.exchange.views.build_contextual_explanation_service",
        return_value=disabled_service,
    ):
        response = client.post(
            reverse("comparison_explanation"),
            {"grounded_explanation_token": token},
        )

    assert response.status_code == 200
    assert b"<html" in response.content
    assert b"Trusted facts first. Explanation second." in response.content
    assert b"Built-in explanation" in response.content


@pytest.mark.django_db
def test_comparison_result_survives_optional_ai_packet_contract_failure(
    client,
    comparison_reference_data,
    settings,
):
    settings.AI_RUNTIME_EXPLANATION_ENABLED = True
    gateway = ComparisonGateway()

    with (
        patch("apps.exchange.views.build_latest_quote_gateway", return_value=gateway),
        patch(
            "apps.exchange.comparison_presentation.build_grounded_packet_token",
            side_effect=GroundedPacketTokenError("bounded packet unavailable"),
        ),
    ):
        response = client.post(reverse("destination_comparison"), _payload())

    assert response.status_code == 200
    assert b"No winner is calculated." in response.content
    assert response.context["comparison"]["ai_explanation"] is None
    assert b"signed comparison facts only" not in response.content
    assert gateway.calls == [("EUR", "JPY"), ("EUR", "NOK")]


@pytest.mark.django_db
def test_comparison_frontend_exposes_full_backend_context_contract(
    client,
    comparison_reference_data,
):
    gateway = ComparisonGateway()

    with patch("apps.exchange.views.build_latest_quote_gateway", return_value=gateway):
        response = client.post(reverse("destination_comparison"), _payload())

    assert response.status_code == 200
    component = response.context["comparison"]
    assert component["selected_categories"] == (
        {"label": "Coffee", "units": "1"},
        {"label": "Casual Meal", "units": "2"},
        {"label": "Transit", "units": "2"},
    )
    assert component["shared_categories"] == ("Coffee", "Casual Meal", "Transit")

    left = component["left"]
    right = component["right"]
    assert left["context_state"] == "available"
    assert right["context_state"] == "available"
    assert left["context_as_of"]
    assert right["context_as_of"]

    left_converter = urlparse(left["converter_url"])
    left_query = parse_qs(left_converter.query)
    assert left_converter.path == reverse("converter")
    assert left_query["amount"] == ["500"]
    assert left_query["source_currency"] == ["EUR"]
    assert left_query["destination_country"] == ["JP"]
    assert left_query["destination_currency"] == ["JPY"]
    assert left_query["destination_city_slug"] == ["tokyo"]

    assert parse_qs(urlparse(left["budget_url"]).query)["destination"] == ["JP:tokyo"]
    assert left["city_profile_url"] == reverse("city_money_profile", args=("JP", "tokyo"))
    assert left["theme"] == "jp"

    right_converter = urlparse(right["converter_url"])
    right_query = parse_qs(right_converter.query)
    assert right_query["destination_country"] == ["NO"]
    assert right_query["destination_currency"] == ["NOK"]
    assert "destination_city_slug" not in right_query
    assert parse_qs(urlparse(right["budget_url"]).query)["destination"] == ["NO"]
    assert right["city_profile_url"] == ""
    assert right["theme"] == "no"

    body = response.content
    assert b"Same explicit basket on both sides" in body
    assert body.count(b"Reviewed local context assembled as of") == 2
    assert b"City evidence" in body
    assert b"National fallback" in body
    assert b"Curated factual" in body
    assert b"High confidence" in body
    assert body.count(b"Open conversion") == 2
    assert body.count(b"Build budget") == 2
    assert b"City money profile" in body
    assert body.count(b"Full payment guide") == 2
    assert b'data-country-theme="jp"' in body
    assert b'data-country-theme="no"' in body
    assert b"Cards are commonly accepted for routine purchases." in body
    assert b"Use clearly identified ATMs and review disclosed fees." in body
    assert b"Follow reviewed local tipping customs." in body
