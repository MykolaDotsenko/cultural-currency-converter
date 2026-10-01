from __future__ import annotations

import io
import re
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import Mock, patch

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image

from apps.countries.models import City, Country, CountryCurrency, Currency
from apps.exchange.camera import (
    CameraAmountCandidate,
    CameraCandidateKind,
    CameraConfidence,
    CameraExtraction,
    load_confirmed_camera_amount_token,
    make_camera_candidate_token,
)
from apps.exchange.camera_service import (
    CameraFeatureDisabled,
    CameraProviderUnavailable,
    CameraScanDelivery,
)
from apps.exchange.domain import DEFAULT_SOURCE_POLICY, ConversionResult, RateQuote
from apps.travel.camera_forms import camera_scope_for_scenario
from apps.travel.models import SavedScenarioKind
from apps.travel.scenarios import SavedScenarioSpec, create_saved_scenario

User = get_user_model()


def _png_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (500, 300), "white").save(output, format="PNG")
    return output.getvalue()


def _normalized_response_text(response) -> str:
    return " ".join(response.content.decode("utf-8").split())


@pytest.fixture(autouse=True)
def use_vite_dev_mode(settings):
    settings.VITE_DEV_SERVER_ENABLED = True


@pytest.fixture
def camera_scenario(db):
    eur = Currency.objects.create(code="EUR", name="Euro", minor_units=2)
    jpy = Currency.objects.create(code="JPY", name="Japanese yen", minor_units=0)
    fi = Country.objects.create(iso2="FI", iso3="FIN", name="Finland")
    jp = Country.objects.create(iso2="JP", iso3="JPN", name="Japan")
    CountryCurrency.objects.create(country=fi, currency=eur, is_primary=True, source="test")
    CountryCurrency.objects.create(country=jp, currency=jpy, is_primary=True, source="test")
    tokyo = City.objects.create(country=jp, slug="tokyo", name="Tokyo")
    owner = User.objects.create_user(username="camera-owner", password="StrongPass-482!")

    conversion = ConversionResult(
        input_amount=Decimal("600"),
        output_amount=Decimal("104700"),
        quote=RateQuote(
            base_currency="EUR",
            quote_currency="JPY",
            rate=Decimal("174.5"),
            requested_date=None,
            effective_date=date(2026, 10, 1),
            fetched_at=datetime(2026, 10, 1, 4, tzinfo=UTC),
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
            title="Tokyo budget",
            source_currency=eur,
            destination_currency=jpy,
            source_country=fi,
            destination_country=jp,
            destination_city=tokyo,
            source_amount=Decimal("600"),
            duration_days=5,
        ),
        conversion=conversion,
    )
    return owner, scenario


def _delivery(*candidates: CameraAmountCandidate) -> CameraScanDelivery:
    return CameraScanDelivery(
        extraction=CameraExtraction(
            candidates=tuple(candidates),
            provider_model="fake-camera",
            provider_response_id="response-1",
        ),
        image_width=1200,
        image_height=800,
    )


def _candidate(
    amount: str,
    *,
    currency: str = "JPY",
    confidence: CameraConfidence = CameraConfidence.HIGH,
) -> CameraAmountCandidate:
    return CameraAmountCandidate(
        amount=Decimal(amount),
        currency_code=currency,
        kind=CameraCandidateKind.TOTAL,
        confidence=confidence,
    )


@pytest.mark.django_db
def test_saved_budget_exposes_camera_action_only_when_runtime_capability_is_enabled(
    client,
    camera_scenario,
    settings,
):
    owner, scenario = camera_scenario
    client.force_login(owner)

    settings.AI_CAMERA_EXTRACTION_ENABLED = False
    disabled = client.get(reverse("saved_scenario_detail", args=(scenario.pk,)))
    assert disabled.status_code == 200
    assert b"Scan a price" not in disabled.content

    settings.AI_CAMERA_EXTRACTION_ENABLED = True
    enabled = client.get(reverse("saved_scenario_detail", args=(scenario.pk,)))
    assert enabled.status_code == 200
    assert b"Scan a price" in enabled.content
    assert reverse("camera_scan_saved_scenario", args=(scenario.pk,)).encode() in enabled.content


@pytest.mark.django_db
def test_camera_page_is_owner_scoped_and_explains_ephemeral_privacy(client, camera_scenario):
    owner, scenario = camera_scenario
    client.force_login(owner)

    response = client.get(reverse("camera_scan_saved_scenario", args=(scenario.pk,)))

    assert response.status_code == 200
    assert b"Scan a visible price" in response.content
    assert b"Image processing is ephemeral" in response.content
    assert b"does not save the uploaded image" in response.content
    assert b'name="robots" content="noindex"' in response.content
    assert scenario.spend_entries.count() == 0


@pytest.mark.django_db
def test_camera_page_requires_owner_login(client, camera_scenario):
    _, scenario = camera_scenario
    other = User.objects.create_user(username="camera-other", password="StrongPass-482!")

    anonymous = client.get(reverse("camera_scan_saved_scenario", args=(scenario.pk,)))
    assert anonymous.status_code == 302
    assert reverse("login") in anonymous.url

    client.force_login(other)
    forbidden = client.get(reverse("camera_scan_saved_scenario", args=(scenario.pk,)))
    assert forbidden.status_code == 404


@pytest.mark.django_db
def test_scan_shows_only_confirmation_paths_compatible_with_trip_currency(
    client,
    camera_scenario,
):
    owner, scenario = camera_scenario
    client.force_login(owner)
    service = Mock()
    service.scan.return_value = _delivery(
        _candidate("4800"),
        _candidate("52.40", currency="USD", confidence=CameraConfidence.MEDIUM),
        _candidate("820", currency=""),
    )

    with patch(
        "apps.travel.camera_web.build_camera_extraction_service",
        return_value=service,
    ):
        response = client.post(
            reverse("camera_scan_saved_scenario", args=(scenario.pk,)),
            {
                "action": "scan",
                "image": SimpleUploadedFile(
                    "receipt.png",
                    _png_bytes(),
                    content_type="image/png",
                ),
            },
        )

    assert response.status_code == 200
    assert b"4800 JPY" in response.content
    assert b"52.4 USD" in response.content
    assert b"820 JPY" in response.content
    assert response.content.count(b"Confirm this amount") == 2
    assert b"cannot be confirmed as trip spend" in response.content
    assert b"receipt.png" not in response.content
    assert scenario.spend_entries.count() == 0
    service.scan.assert_called_once()
    assert service.scan.call_args.kwargs["expected_currency"] == "JPY"


@pytest.mark.django_db
def test_invalid_camera_upload_never_calls_provider(client, camera_scenario):
    owner, scenario = camera_scenario
    client.force_login(owner)
    service = Mock()

    with patch(
        "apps.travel.camera_web.build_camera_extraction_service",
        return_value=service,
    ):
        response = client.post(
            reverse("camera_scan_saved_scenario", args=(scenario.pk,)),
            {
                "action": "scan",
                "image": SimpleUploadedFile(
                    "payload.gif",
                    b"GIF89a",
                    content_type="image/gif",
                ),
            },
        )

    assert response.status_code == 422
    assert b"Use a JPEG, PNG or WebP image." in response.content
    service.scan.assert_not_called()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "failure",
    [
        CameraFeatureDisabled("disabled"),
        CameraProviderUnavailable("unavailable"),
    ],
)
def test_camera_provider_failure_is_non_persisting_and_recoverable(
    client,
    camera_scenario,
    failure,
):
    owner, scenario = camera_scenario
    client.force_login(owner)
    service = Mock()
    service.scan.side_effect = failure

    with patch(
        "apps.travel.camera_web.build_camera_extraction_service",
        return_value=service,
    ):
        response = client.post(
            reverse("camera_scan_saved_scenario", args=(scenario.pk,)),
            {
                "action": "scan",
                "image": SimpleUploadedFile(
                    "price.png",
                    _png_bytes(),
                    content_type="image/png",
                ),
            },
        )

    assert response.status_code == 503
    assert b"Camera extraction is temporarily unavailable" in response.content
    assert b"No amount was stored." in response.content
    assert scenario.spend_entries.count() == 0


@pytest.mark.django_db
def test_user_can_correct_and_confirm_candidate_without_persisting_spend(
    client,
    camera_scenario,
):
    owner, scenario = camera_scenario
    client.force_login(owner)
    candidate = _candidate("4800")
    scope = camera_scope_for_scenario(scenario.pk)
    token = make_camera_candidate_token(candidate, scope=scope)

    response = client.post(
        reverse("camera_scan_saved_scenario", args=(scenario.pk,)),
        {
            "action": "confirm",
            "candidate_token": token,
            "amount": "4750",
        },
    )

    assert response.status_code == 200
    assert b"4750 JPY" in response.content
    text = _normalized_response_text(response)
    assert "uploaded image itself was not persisted" in text
    assert "Nothing was added to confirmed spend" in text
    assert scenario.spend_entries.count() == 0

    match = re.search(
        rb'name="confirmed_camera_token"\s+value="([^"]+)"',
        response.content,
    )
    assert match is not None
    confirmed = load_confirmed_camera_amount_token(
        match.group(1).decode("utf-8"),
        expected_scope=scope,
    )
    assert confirmed.amount == Decimal("4750")
    assert confirmed.currency_code == "JPY"


@pytest.mark.django_db
def test_explicit_currency_mismatch_cannot_cross_confirmation_boundary(
    client,
    camera_scenario,
):
    owner, scenario = camera_scenario
    client.force_login(owner)
    scope = camera_scope_for_scenario(scenario.pk)
    token = make_camera_candidate_token(
        _candidate("52.40", currency="USD"),
        scope=scope,
    )

    response = client.post(
        reverse("camera_scan_saved_scenario", args=(scenario.pk,)),
        {
            "action": "confirm",
            "candidate_token": token,
            "amount": "52",
        },
    )

    assert response.status_code == 422
    assert b"appears to use USD" in response.content
    assert b"saved trip uses JPY" in response.content
    assert scenario.spend_entries.count() == 0


@pytest.mark.django_db
def test_tampered_camera_candidate_cannot_be_confirmed(client, camera_scenario):
    owner, scenario = camera_scenario
    client.force_login(owner)
    scope = camera_scope_for_scenario(scenario.pk)
    token = make_camera_candidate_token(_candidate("4800"), scope=scope)

    response = client.post(
        reverse("camera_scan_saved_scenario", args=(scenario.pk,)),
        {
            "action": "confirm",
            "candidate_token": token + "tampered",
            "amount": "4800",
        },
    )

    assert response.status_code == 422
    assert b"Camera candidate token is invalid." in response.content
    assert scenario.spend_entries.count() == 0
