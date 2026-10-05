from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.exchange.domain import (
    DEFAULT_SOURCE_POLICY,
    ConversionResult,
    ObservationGranularity,
    RateQuote,
    same_currency_quote,
)
from apps.exchange.share_snapshot import build_conversion_share_token


@pytest.fixture(autouse=True)
def use_vite_dev_mode(settings):
    settings.VITE_DEV_SERVER_ENABLED = True


def _result(
    *,
    historical: bool = False,
    stale: bool = False,
) -> ConversionResult:
    requested_date = date(1998, 6, 15) if historical else None
    effective_date = date(1998, 6, 12) if historical else date(2026, 9, 18)
    base = "FIM" if historical else "EUR"
    quote = "USD" if historical else "JPY"
    rate = Decimal("0.2135") if historical else Decimal("174.50")
    output = Decimal("21.35") if historical else Decimal("17450")
    return ConversionResult(
        input_amount=Decimal("100"),
        output_amount=output,
        quote=RateQuote(
            base_currency=base,
            quote_currency=quote,
            rate=rate,
            requested_date=requested_date,
            effective_date=effective_date,
            fetched_at=datetime(2026, 9, 20, 8, tzinfo=UTC),
            provider_policy=DEFAULT_SOURCE_POLICY,
            provider_keys=("ecb",),
            historical=historical,
            observation_granularity=(
                ObservationGranularity.MONTHLY if historical else ObservationGranularity.DAILY
            ),
        ),
        stale=stale,
    )


def _share_url(result: ConversionResult) -> str:
    token = build_conversion_share_token(result)
    return f"{reverse('share_conversion_card')}?snapshot={token}"


def test_share_page_is_read_only_provider_free_snapshot(client, monkeypatch) -> None:
    def unexpected_gateway(*_args, **_kwargs):
        raise AssertionError("Share rendering must never build an FX gateway.")

    monkeypatch.setattr(
        "apps.exchange.web.gateways.build_latest_quote_gateway",
        unexpected_gateway,
    )

    response = client.get(_share_url(_result()))

    assert response.status_code == 200
    cache_control = response["Cache-Control"]
    assert "private" in cache_control
    assert "no-store" in cache_control
    assert response["X-Robots-Tag"] == "noindex, nofollow"
    assert response["Referrer-Policy"] == "no-referrer"
    text = " ".join(response.content.decode("utf-8").split())
    assert "100 EUR → 17450 JPY" in text
    assert "1 EUR = 174.5 JPY" in text
    assert "18 Sep 2026" in text
    assert "ECB" in text
    assert "signed read-only snapshot" in text
    assert "never refreshes the exchange rate" in text
    assert "Stored share snapshot" in text
    assert "Copy share link" in text
    assert reverse("share_conversion_card_svg") in text


def test_stale_share_page_keeps_cached_reference_warning(client) -> None:
    response = client.get(_share_url(_result(stale=True)))

    assert response.status_code == 200
    text = " ".join(response.content.decode("utf-8").split())
    assert "Cached reference" in text
    assert "already marked stale when shared" in text
    assert "current executable rate" in text


def test_historical_share_page_preserves_requested_and_effective_date(client) -> None:
    response = client.get(_share_url(_result(historical=True)))

    assert response.status_code == 200
    text = " ".join(response.content.decode("utf-8").split())
    assert "100 FIM → 21.35 USD" in text
    assert "Requested date" in text
    assert "15 Jun 1998" in text
    assert "12 Jun 1998" in text
    assert "Monthly historical" in text
    assert "not a current rate" in text


def test_exact_share_svg_uses_equals_and_no_external_provider(client) -> None:
    quote = same_currency_quote(
        "EUR",
        fetched_at=datetime(2026, 10, 5, 6, tzinfo=UTC),
    )
    result = ConversionResult(
        input_amount=Decimal("12"),
        output_amount=Decimal("12.00"),
        quote=quote,
        stale=False,
    )
    token = build_conversion_share_token(result)

    response = client.get(f"{reverse('share_conversion_card_svg')}?snapshot={token}")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("image/svg+xml")
    assert "private" in response["Cache-Control"]
    assert "no-store" in response["Cache-Control"]
    body = response.content.decode("utf-8")
    assert "<script" not in body.lower()
    assert "= 12 EUR" in body
    assert "≈ 12 EUR" not in body
    assert "No external rate source" in body


def test_invalid_share_token_fails_closed(client) -> None:
    response = client.get(
        reverse("share_conversion_card"),
        {"snapshot": "not-a-valid-token"},
    )
    svg = client.get(
        reverse("share_conversion_card_svg"),
        {"snapshot": "not-a-valid-token"},
    )

    assert response.status_code == 404
    assert svg.status_code == 404
