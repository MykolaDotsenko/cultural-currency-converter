from __future__ import annotations

import re
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from apps.countries.models import Country, CountryCurrency, Currency
from apps.culture.models import (
    TypicalPrice,
    TypicalPriceConfidence,
    TypicalPriceSourceClass,
)
from apps.culture.services import DestinationContext
from apps.exchange.ai.packet_tokens import GroundedPacketTokenError
from apps.exchange.ai.service import RuntimeExplanationService
from apps.exchange.budget import BudgetCategoryAssumption
from apps.exchange.budget_presets import upsert_budget_preset
from apps.exchange.budget_snapshot import build_budget_context_snapshot_token
from apps.exchange.domain import DEFAULT_SOURCE_POLICY, ConversionResult, RateQuote
from apps.exchange.money_context import MoneyContext, MoneyContextState
from apps.exchange.payment_budget_snapshot import build_payment_budget_handoff_token
from apps.exchange.payment_estimate import estimate_payment_value

User = get_user_model()


class FakeGateway:
    def get(self, base, quote, policy, *, now):
        return (
            RateQuote(
                base_currency=base,
                quote_currency=quote,
                rate=Decimal("174.50"),
                requested_date=None,
                effective_date=timezone.localdate(),
                fetched_at=timezone.now(),
                provider_policy=DEFAULT_SOURCE_POLICY,
                provider_keys=("ecb",),
                historical=False,
            ),
            False,
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
    CountryCurrency.objects.create(country=fi, currency=eur, is_primary=True, source="test")
    CountryCurrency.objects.create(country=jp, currency=jpy, is_primary=True, source="test")

    for category, label, low, high, order in (
        ("coffee", "Cup of coffee", "100", "600", 10),
        ("casual_meal", "Casual meal", "500", "1000", 20),
    ):
        TypicalPrice.objects.create(
            country=jp,
            category=category,
            label=label,
            amount_low=Decimal(low),
            amount_high=Decimal(high),
            currency=jpy,
            source_name="Sourced travel context",
            source_url=f"https://example.com/{category}",
            observed_at=timezone.localdate(),
            verified_at=timezone.now(),
            source_class=TypicalPriceSourceClass.APPROXIMATE_CONTEXTUAL,
            confidence=TypicalPriceConfidence.MEDIUM,
            display_order=order,
            is_published=True,
        )

    return fi, jp, eur, jpy


def _payload(**overrides):
    values = {
        "amount": "100.00",
        "source_country": "FI",
        "source_currency": "EUR",
        "destination_country": "JP",
        "destination_currency": "JPY",
    }
    values.update(overrides)
    return values


def _extract_budget_token(content: bytes) -> str:
    match = re.search(rb'name="budget_context_token"\s+value="([^"]+)"', content)
    assert match is not None
    return match.group(1).decode()


def _payment_budget_handoff() -> str:
    return build_payment_budget_handoff_token(
        budget_context_token=_signed_budget_context(),
        estimate=estimate_payment_value(
            source_budget=Decimal("100.00"),
            reference_destination_amount=Decimal("17450"),
            rate=Decimal("174.50"),
            fx_markup_percent=Decimal("2"),
            source_fixed_fee=Decimal("1"),
            destination_fixed_fee=Decimal("220"),
            destination_minor_units=0,
        ),
    )


def _signed_budget_context() -> str:
    quote = RateQuote(
        base_currency="EUR",
        quote_currency="JPY",
        rate=Decimal("174.50"),
        requested_date=None,
        effective_date=timezone.localdate(),
        fetched_at=timezone.now(),
        provider_policy=DEFAULT_SOURCE_POLICY,
        provider_keys=("ecb",),
        historical=False,
    )
    conversion = ConversionResult(
        input_amount=Decimal("100.00"),
        output_amount=Decimal("17450"),
        quote=quote,
        stale=False,
    )
    destination = DestinationContext(
        country_code="JP",
        country_name="Japan",
        as_of=timezone.localdate(),
        payment=None,
        prices=(),
    )
    context = MoneyContext(
        conversion=conversion,
        destination_country_code="JP",
        as_of=timezone.localdate(),
        destination_context=destination,
        destination_state=MoneyContextState.EMPTY,
    )
    return build_budget_context_snapshot_token(context)


@pytest.mark.django_db
def test_current_conversion_offers_budget_interpretation_from_sourced_anchors(
    client,
    reference_data,
):
    with patch("apps.exchange.views.build_latest_quote_gateway", return_value=FakeGateway()):
        response = client.post(reverse("converter"), _payload(), HTTP_HX_REQUEST="true")

    assert response.status_code == 200
    assert b"Put this amount against a small daily reference basket" in response.content
    assert b"Cup of coffee per person / day" in response.content
    assert b"Casual meal per person / day" in response.content
    assert b"Transit per person / day" not in response.content
    assert _extract_budget_token(response.content)
    converter_close = response.content.index(b"</form>")
    budget_heading = response.content.index(b"Budget interpretation")
    assert converter_close < budget_heading


@pytest.mark.django_db
def test_payment_adjusted_budget_handoff_preserves_explicit_basis(
    client,
    reference_data,
):
    handoff = _payment_budget_handoff()

    response = client.post(
        reverse("budget_interpretation"),
        {"payment_budget_token": handoff},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    component = response.context["budget_interpretation"]
    assert component["basis"] == "payment_estimate"
    assert component["basis_label"] == "Payment-adjusted estimate"
    assert component["planning_amount"] == "16717"
    assert component["reference_amount"] == "17450"
    assert component["payment_estimate"]["fx_markup_percent"] == "2"
    assert b"Use this estimate" not in response.content
    assert b"Payment-adjusted estimate" in response.content
    assert b'name="payment_budget_token"' in response.content

    interpreted = client.post(
        reverse("budget_interpretation"),
        {
            "payment_budget_token": handoff,
            "duration_days": "10",
            "travelers": "1",
            "units_coffee": "1",
            "units_casual_meal": "2",
        },
        HTTP_HX_REQUEST="true",
    )

    assert interpreted.status_code == 200
    result = interpreted.context["budget_interpretation"]
    assert result["basis"] == "payment_estimate"
    assert result["result"]["available_budget"] == "16717"
    interpreted_text = " ".join(interpreted.content.decode("utf-8").split())
    assert "Reference FX value: 17450 JPY" in interpreted_text


@pytest.mark.django_db
def test_budget_interpretation_uses_signed_conversion_and_explicit_basket(
    client,
    reference_data,
):
    response = client.post(
        reverse("budget_interpretation"),
        {
            "budget_context_token": _signed_budget_context(),
            "duration_days": "10",
            "travelers": "1",
            "units_coffee": "1",
            "units_casual_meal": "2",
            "reference_amount": "999999999",
        },
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    assert b"Within this reference range" in response.content
    assert b"17450 JPY" in response.content
    assert b"1745 JPY" in response.content
    assert b"11000" in response.content
    assert b"26000" in response.content
    assert b"999999999" not in response.content
    assert b"not a full trip-cost forecast" in response.content


@pytest.mark.django_db
def test_valid_budget_interpretation_exposes_account_save_payload(
    client,
    reference_data,
):
    user = User.objects.create_user(username="owner", password="StrongPass-482!")
    client.force_login(user)

    response = client.post(
        reverse("budget_interpretation"),
        {
            "budget_context_token": _signed_budget_context(),
            "duration_days": "4",
            "travelers": "2",
            "units_coffee": "1",
            "units_casual_meal": "2",
        },
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    assert b"Save this budget scenario" in response.content
    assert b'action="/saved/scenarios/budget/create/"' in response.content
    assert b'name="duration_days" value="4"' in response.content
    assert b'name="travelers" value="2"' in response.content
    assert b'name="units_coffee" value="1"' in response.content
    assert b'name="units_casual_meal" value="2"' in response.content


@pytest.mark.django_db
def test_anonymous_budget_interpretation_keeps_save_opt_in(
    client,
    reference_data,
):
    response = client.post(
        reverse("budget_interpretation"),
        {
            "budget_context_token": _signed_budget_context(),
            "duration_days": "4",
            "travelers": "1",
            "units_coffee": "1",
        },
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    assert b"Sign in to save" in response.content
    assert b"browser-only favourites and recent history are not" in response.content
    assert b"uploaded automatically" in response.content
    assert b'action="/saved/scenarios/budget/create/"' not in response.content


@pytest.mark.django_db
def test_budget_interpretation_rejects_tampered_context_token(client, reference_data):
    response = client.post(
        reverse("budget_interpretation"),
        {
            "budget_context_token": "tampered",
            "duration_days": "3",
            "travelers": "1",
            "units_coffee": "1",
        },
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 422
    assert b"no longer valid" in response.content


@pytest.mark.django_db
def test_budget_interpretation_requires_at_least_one_visible_reference_item(
    client,
    reference_data,
):
    response = client.post(
        reverse("budget_interpretation"),
        {
            "budget_context_token": _signed_budget_context(),
            "duration_days": "3",
            "travelers": "1",
            "units_coffee": "",
            "units_casual_meal": "",
        },
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 422
    assert b"Keep at least one daily reference item" in response.content
    assert b"Reference-basket comparison" not in response.content


@pytest.mark.django_db
def test_non_javascript_budget_interpretation_returns_full_page(client, reference_data):
    response = client.post(
        reverse("budget_interpretation"),
        {
            "budget_context_token": _signed_budget_context(),
            "duration_days": "3",
            "travelers": "1",
            "units_coffee": "1",
            "units_casual_meal": "2",
        },
    )

    assert response.status_code == 200
    assert b"<html" in response.content
    assert b"A transparent reference basket, not a guessed travel budget" in response.content
    assert b"Above this reference basket" in response.content


@pytest.mark.django_db
def test_budget_interpretation_preserves_requested_category_when_source_row_disappears(
    client,
    reference_data,
):
    with patch("apps.exchange.views.build_latest_quote_gateway", return_value=FakeGateway()):
        conversion_response = client.post(
            reverse("converter"),
            _payload(),
            HTTP_HX_REQUEST="true",
        )

    token = _extract_budget_token(conversion_response.content)
    TypicalPrice.objects.filter(category="casual_meal").delete()

    response = client.post(
        reverse("budget_interpretation"),
        {
            "budget_context_token": token,
            "duration_days": "3",
            "travelers": "1",
            "units_coffee": "1",
            "units_casual_meal": "2",
        },
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    assert b"Insufficient current data" in response.content
    assert b"Missing: Casual Meal" in response.content
    assert b"Within this reference range" not in response.content


@pytest.mark.django_db
def test_budget_result_exposes_only_signed_grounded_ai_prompts(
    client,
    reference_data,
    settings,
):
    settings.AI_RUNTIME_EXPLANATION_ENABLED = True

    response = client.post(
        reverse("budget_interpretation"),
        {
            "budget_context_token": _signed_budget_context(),
            "duration_days": "4",
            "travelers": "2",
            "units_coffee": "1",
            "units_casual_meal": "2",
        },
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    ai = response.context["budget_interpretation"]["ai_explanation"]
    assert tuple(prompt["id"] for prompt in ai["prompts"]) == (
        "budget_overview",
        "budget_basket",
        "budget_coverage",
    )
    assert b"Optional AI" in response.content
    assert b"signed budget facts only" in response.content
    assert b'name="grounded_explanation_token"' in response.content
    assert b'name="prompt_id"' not in response.content


@pytest.mark.django_db
def test_budget_ai_builtin_fallback_uses_signed_deterministic_result(
    client,
    reference_data,
    settings,
):
    settings.AI_RUNTIME_EXPLANATION_ENABLED = True
    result_response = client.post(
        reverse("budget_interpretation"),
        {
            "budget_context_token": _signed_budget_context(),
            "duration_days": "4",
            "travelers": "2",
            "units_coffee": "1",
            "units_casual_meal": "2",
        },
        HTTP_HX_REQUEST="true",
    )
    token = result_response.context["budget_interpretation"]["ai_explanation"]["prompts"][0][
        "token"
    ]
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
            reverse("budget_explanation"),
            {"grounded_explanation_token": token},
            HTTP_HX_REQUEST="true",
        )

    assert response.status_code == 200
    assert b"Built-in explanation" in response.content
    assert b"17450 JPY" in response.content
    assert b"4 days" in response.content
    assert b"2 travelers" in response.content
    assert b"Live AI is unavailable" in response.content
    assert b"deterministic result above is unchanged" in response.content
    assert b"Facts used" in response.content


@pytest.mark.django_db
def test_budget_ai_rejects_tampered_packet_before_service_creation(
    client,
    reference_data,
    settings,
):
    settings.AI_RUNTIME_EXPLANATION_ENABLED = True

    with patch("apps.exchange.views.build_contextual_explanation_service") as service_factory:
        response = client.post(
            reverse("budget_explanation"),
            {"grounded_explanation_token": "tampered"},
            HTTP_HX_REQUEST="true",
        )

    assert response.status_code == 422
    assert b"no longer valid" in response.content
    service_factory.assert_not_called()


@pytest.mark.django_db
def test_budget_ai_has_no_javascript_full_page_fallback(
    client,
    reference_data,
    settings,
):
    settings.AI_RUNTIME_EXPLANATION_ENABLED = True
    result_response = client.post(
        reverse("budget_interpretation"),
        {
            "budget_context_token": _signed_budget_context(),
            "duration_days": "3",
            "travelers": "1",
            "units_coffee": "1",
        },
        HTTP_HX_REQUEST="true",
    )
    token = result_response.context["budget_interpretation"]["ai_explanation"]["prompts"][0][
        "token"
    ]
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
            reverse("budget_explanation"),
            {"grounded_explanation_token": token},
        )

    assert response.status_code == 200
    assert b"<html" in response.content
    assert b"Trusted facts first. Explanation second." in response.content
    assert b"Built-in explanation" in response.content


@pytest.mark.django_db
def test_budget_result_survives_optional_ai_packet_contract_failure(
    client,
    reference_data,
    settings,
):
    settings.AI_RUNTIME_EXPLANATION_ENABLED = True

    with patch(
        "apps.exchange.budget_presentation.build_grounded_packet_token",
        side_effect=GroundedPacketTokenError("bounded packet unavailable"),
    ):
        response = client.post(
            reverse("budget_interpretation"),
            {
                "budget_context_token": _signed_budget_context(),
                "duration_days": "4",
                "travelers": "1",
                "units_coffee": "1",
            },
            HTTP_HX_REQUEST="true",
        )

    assert response.status_code == 200
    assert b"Reference-basket comparison" in response.content
    assert response.context["budget_interpretation"]["ai_explanation"] is None
    assert b"signed budget facts only" not in response.content


@pytest.mark.django_db
def test_current_conversion_lists_only_owner_budget_presets(
    client,
    reference_data,
):
    owner = User.objects.create_user(
        username="budget-preset-list-owner", password="StrongPass-482!"
    )
    other = User.objects.create_user(
        username="budget-preset-list-other", password="StrongPass-482!"
    )
    upsert_budget_preset(
        owner,
        name="Weekend city",
        duration_days=3,
        travelers=2,
        categories=(
            BudgetCategoryAssumption("coffee", Decimal("1.00")),
            BudgetCategoryAssumption("casual_meal", Decimal("2.00")),
        ),
    )
    upsert_budget_preset(
        other,
        name="Other plan",
        duration_days=4,
        travelers=1,
        categories=(BudgetCategoryAssumption("coffee", Decimal("2.00")),),
    )
    client.force_login(owner)

    with patch("apps.exchange.views.build_latest_quote_gateway", return_value=FakeGateway()):
        response = client.post(reverse("converter"), _payload(), HTTP_HX_REQUEST="true")

    assert response.status_code == 200
    assert b"Budget presets" in response.content
    assert b"Weekend city" in response.content
    assert b"Other plan" not in response.content


@pytest.mark.django_db
def test_budget_preset_application_replaces_submitted_assumptions(
    client,
    reference_data,
):
    user = User.objects.create_user(username="budget-preset-apply", password="StrongPass-482!")
    preset = upsert_budget_preset(
        user,
        name="Weekend city",
        duration_days=5,
        travelers=2,
        categories=(
            BudgetCategoryAssumption("coffee", Decimal("2.00")),
            BudgetCategoryAssumption("casual_meal", Decimal("1.00")),
        ),
    )
    client.force_login(user)

    response = client.post(
        reverse("budget_interpretation"),
        {
            "budget_context_token": _signed_budget_context(),
            "duration_days": "99",
            "travelers": "9",
            "units_coffee": "9",
            "units_casual_meal": "9",
            "budget_preset_id": str(preset.pk),
        },
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    component = response.context["budget_interpretation"]
    assert component["selected_preset_name"] == "Weekend city"
    assert component["result"]["duration_days"] == 5
    assert component["result"]["travelers"] == 2
    assert component["form"]["duration_days"].value() == 5
    assert component["form"]["travelers"].value() == 2
    assert component["form"]["units_coffee"].value() == "2"
    assert component["form"]["units_casual_meal"].value() == "1"
    assert b"Using saved budget preset" in response.content


@pytest.mark.django_db
def test_budget_preset_with_unsourced_category_remains_explicit_and_incomplete(
    client,
    reference_data,
):
    user = User.objects.create_user(username="budget-preset-unsourced", password="StrongPass-482!")
    preset = upsert_budget_preset(
        user,
        name="Transit included",
        duration_days=3,
        travelers=1,
        categories=(
            BudgetCategoryAssumption("coffee", Decimal("1.00")),
            BudgetCategoryAssumption("transit", Decimal("2.00")),
        ),
    )
    client.force_login(user)

    response = client.post(
        reverse("budget_interpretation"),
        {
            "budget_context_token": _signed_budget_context(),
            "budget_preset_id": str(preset.pk),
        },
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    component = response.context["budget_interpretation"]
    assert component["result"]["complete"] is False
    assert component["result"]["missing_categories"] == ("Transit",)
    assert component["hidden_category_fields"] == ({"field_name": "units_transit", "value": "2"},)
    assert b"Insufficient current data" in response.content
    assert b'name="units_transit"' in response.content
    assert b'value="2"' in response.content


@pytest.mark.django_db
def test_successful_budget_interpretation_can_save_and_update_preset(
    client,
    reference_data,
):
    user = User.objects.create_user(username="budget-preset-save", password="StrongPass-482!")
    client.force_login(user)

    response = client.post(
        reverse("budget_interpretation"),
        {
            "budget_context_token": _signed_budget_context(),
            "duration_days": "4",
            "travelers": "2",
            "units_coffee": "1.5",
            "units_casual_meal": "2",
            "budget_action": "save_preset",
            "preset_name": "Weekend city",
        },
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    preset = user.budget_presets.get()
    assert preset.name == "Weekend city"
    assert preset.duration_days == 4
    assert preset.travelers == 2
    assert tuple(preset.items.values_list("category", "units_per_person_per_day")) == (
        ("casual_meal", Decimal("2.00")),
        ("coffee", Decimal("1.50")),
    )
    assert b"Saved budget preset &quot;Weekend city&quot;." in response.content

    updated = client.post(
        reverse("budget_interpretation"),
        {
            "budget_context_token": _signed_budget_context(),
            "duration_days": "7",
            "travelers": "1",
            "units_coffee": "2",
            "budget_action": "save_preset",
            "preset_name": "Weekend city",
        },
        HTTP_HX_REQUEST="true",
    )

    assert updated.status_code == 200
    preset.refresh_from_db()
    assert preset.duration_days == 7
    assert preset.travelers == 1
    assert tuple(preset.items.values_list("category", flat=True)) == ("coffee",)


@pytest.mark.django_db
def test_foreign_budget_preset_is_rejected_without_interpretation(
    client,
    reference_data,
):
    owner = User.objects.create_user(
        username="budget-preset-foreign-owner", password="StrongPass-482!"
    )
    viewer = User.objects.create_user(
        username="budget-preset-foreign-viewer", password="StrongPass-482!"
    )
    preset = upsert_budget_preset(
        owner,
        name="Private plan",
        duration_days=3,
        travelers=1,
        categories=(BudgetCategoryAssumption("coffee", Decimal("1.00")),),
    )
    client.force_login(viewer)

    response = client.post(
        reverse("budget_interpretation"),
        {
            "budget_context_token": _signed_budget_context(),
            "duration_days": "3",
            "travelers": "1",
            "units_coffee": "1",
            "budget_preset_id": str(preset.pk),
        },
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 422
    assert b"no longer available" in response.content
    assert b"Reference-basket comparison" not in response.content


@pytest.mark.django_db
def test_anonymous_user_cannot_save_budget_preset_but_keeps_result(
    client,
    reference_data,
):
    response = client.post(
        reverse("budget_interpretation"),
        {
            "budget_context_token": _signed_budget_context(),
            "duration_days": "3",
            "travelers": "1",
            "units_coffee": "1",
            "budget_action": "save_preset",
            "preset_name": "Anonymous preset",
        },
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 403
    assert b"Sign in before saving a budget preset." in response.content
    assert b"Reference-basket comparison" in response.content
    assert User.objects.count() == 0


@pytest.mark.django_db
def test_budget_preset_application_preserves_payment_adjusted_basis(
    client,
    reference_data,
):
    user = User.objects.create_user(
        username="budget-preset-payment-basis",
        password="StrongPass-482!",
    )
    preset = upsert_budget_preset(
        user,
        name="Payment-aware basket",
        duration_days=6,
        travelers=2,
        categories=(
            BudgetCategoryAssumption("coffee", Decimal("1.50")),
            BudgetCategoryAssumption("casual_meal", Decimal("1.00")),
        ),
    )
    client.force_login(user)

    response = client.post(
        reverse("budget_interpretation"),
        {
            "payment_budget_token": _payment_budget_handoff(),
            "budget_preset_id": str(preset.pk),
        },
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    component = response.context["budget_interpretation"]
    assert component["basis"] == "payment_estimate"
    assert component["basis_label"] == "Payment-adjusted estimate"
    assert component["planning_amount"] == "16717"
    assert component["reference_amount"] == "17450"
    assert component["selected_preset_name"] == "Payment-aware basket"
    assert component["result"]["duration_days"] == 6
    assert component["result"]["travelers"] == 2
    assert component["result"]["available_budget"] == "16717"
    assert b"Payment-adjusted estimate" in response.content
