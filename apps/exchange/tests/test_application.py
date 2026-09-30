from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import Mock, patch

import pytest
from django.db import DatabaseError

from apps.countries.models import Country, CountryCurrency, Currency
from apps.culture.services import DestinationContext
from apps.exchange.application import ConverterSubmissionCommand, run_converter_submission
from apps.exchange.domain import DEFAULT_SOURCE_POLICY, RateQuote
from apps.exchange.money_context import MoneyContextState
from apps.exchange.providers.base import FxProviderInvalidPayload, FxProviderUnavailable


class FakeLatestGateway:
    def __init__(self):
        self.calls = []

    def get(self, base, quote, policy, *, now):
        self.calls.append((base, quote, policy, now))
        return (
            RateQuote(
                base_currency=base,
                quote_currency=quote,
                rate=Decimal("174.50"),
                requested_date=None,
                effective_date=date(2026, 9, 18),
                fetched_at=datetime(2026, 9, 20, 8, tzinfo=UTC),
                provider_policy=DEFAULT_SOURCE_POLICY,
                provider_keys=("ecb",),
                historical=False,
            ),
            False,
        )


class UnrepresentableLatestGateway:
    def get(self, base, quote, policy, *, now):
        return (
            RateQuote(
                base_currency=base,
                quote_currency=quote,
                rate=Decimal("1E+50"),
                requested_date=None,
                effective_date=date(2026, 9, 18),
                fetched_at=datetime(2026, 9, 20, 8, tzinfo=UTC),
                provider_policy=DEFAULT_SOURCE_POLICY,
                provider_keys=("ecb",),
                historical=False,
            ),
            False,
        )


class UnavailableHistoricalGateway:
    def get(self, *args, **kwargs):
        raise FxProviderUnavailable("down")


class FakeHistoricalGateway:
    def __init__(self):
        self.calls = []

    def get(self, base, quote, requested_date, policy):
        self.calls.append((base, quote, requested_date, policy))
        return RateQuote(
            base_currency=base,
            quote_currency=quote,
            rate=Decimal("0.20"),
            requested_date=requested_date,
            effective_date=requested_date,
            fetched_at=datetime(2026, 9, 20, 8, tzinfo=UTC),
            provider_policy=DEFAULT_SOURCE_POLICY,
            provider_keys=("ecb",),
            historical=True,
        )


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


@pytest.mark.django_db
def test_current_submission_coordinates_quote_and_destination_context(reference_data):
    latest = FakeLatestGateway()
    historical_factory = Mock()
    destination_context = DestinationContext(
        country_code="JP",
        country_name="Japan",
        as_of=date(2026, 9, 22),
        payment=None,
        prices=(),
    )
    command = ConverterSubmissionCommand(
        amount=Decimal("100"),
        source_country="FI",
        source_currency="EUR",
        destination_country="JP",
        destination_currency="JPY",
    )

    with patch(
        "apps.exchange.money_context.build_destination_context_default",
        return_value=destination_context,
    ) as context_builder:
        outcome = run_converter_submission(
            command,
            latest_gateway_factory=lambda: latest,
            historical_gateway_factory=historical_factory,
            context_as_of=date(2026, 9, 22),
        )

    assert outcome.error is None
    assert outcome.money_context is not None
    assert outcome.money_context.destination_state is MoneyContextState.EMPTY
    assert outcome.conversion is not None
    assert outcome.conversion.output_amount == Decimal("17450")
    assert outcome.destination_context == destination_context
    assert outcome.historical_suggestions == ()
    assert len(latest.calls) == 1
    historical_factory.assert_not_called()
    context_builder.assert_called_once_with(
        country_code="JP",
        converted_amount=Decimal("17450"),
        quote_currency="JPY",
        as_of=date(2026, 9, 22),
        price_limit=3,
    )


@pytest.mark.django_db
def test_unrepresentable_provider_result_is_returned_as_invalid_payload(reference_data):
    command = ConverterSubmissionCommand(
        amount=Decimal("100"),
        source_country="FI",
        source_currency="EUR",
        destination_country="JP",
        destination_currency="JPY",
    )

    outcome = run_converter_submission(
        command,
        latest_gateway_factory=UnrepresentableLatestGateway,
        historical_gateway_factory=Mock(),
        context_as_of=date(2026, 9, 22),
    )

    assert outcome.conversion is None
    assert isinstance(outcome.error, FxProviderInvalidPayload)
    assert "cannot be represented" in str(outcome.error)
    assert outcome.destination_context is None


@pytest.mark.django_db
def test_historical_submission_uses_request_local_date_for_future_boundary(reference_data):
    requested = date(1998, 6, 15)
    command = ConverterSubmissionCommand(
        amount=Decimal("100"),
        source_country="FI",
        source_currency="EUR",
        destination_country="JP",
        destination_currency="JPY",
        historical=True,
        requested_date=requested,
    )

    with (
        patch(
            "apps.exchange.application.timezone.localdate",
            return_value=date(2026, 9, 21),
        ),
        patch(
            "apps.exchange.application.quote_historical_conversion",
        ) as historical_conversion,
    ):
        historical_conversion.return_value = Mock()
        outcome = run_converter_submission(
            command,
            latest_gateway_factory=Mock(),
            historical_gateway_factory=Mock(),
        )

    assert outcome.error is None
    assert historical_conversion.call_args.kwargs["current_date"] == date(2026, 9, 21)


@pytest.mark.django_db
def test_historical_submission_returns_currency_era_suggestion(reference_data):
    latest_factory = Mock()
    historical = FakeHistoricalGateway()
    requested = date(1998, 6, 15)
    command = ConverterSubmissionCommand(
        amount=Decimal("100"),
        source_country="FI",
        source_currency="EUR",
        destination_country="JP",
        destination_currency="JPY",
        historical=True,
        requested_date=requested,
    )

    with patch("apps.exchange.money_context.build_destination_context_default") as context_builder:
        outcome = run_converter_submission(
            command,
            latest_gateway_factory=latest_factory,
            historical_gateway_factory=lambda: historical,
            context_as_of=date(2026, 9, 22),
        )

    assert outcome.error is None
    assert outcome.conversion is not None
    assert outcome.conversion.quote.historical is True
    assert outcome.conversion.quote.requested_date == requested
    assert outcome.money_context is not None
    assert outcome.money_context.destination_state is MoneyContextState.NOT_APPLICABLE
    assert outcome.destination_context is None
    context_builder.assert_not_called()
    assert len(outcome.historical_suggestions) == 1
    placement = outcome.historical_suggestions[0]
    assert placement.side == "source"
    assert placement.suggestion.country_code == "FI"
    assert placement.suggestion.suggested_currency_code == "FIM"
    latest_factory.assert_not_called()


@pytest.mark.django_db
def test_historical_provider_failure_preserves_currency_era_suggestion(reference_data):
    latest_factory = Mock()
    requested = date(1998, 6, 15)
    command = ConverterSubmissionCommand(
        amount=Decimal("100"),
        source_country="FI",
        source_currency="EUR",
        destination_country="JP",
        destination_currency="JPY",
        historical=True,
        requested_date=requested,
    )

    outcome = run_converter_submission(
        command,
        latest_gateway_factory=latest_factory,
        historical_gateway_factory=UnavailableHistoricalGateway,
        context_as_of=date(2026, 9, 22),
    )

    assert outcome.conversion is None
    assert isinstance(outcome.error, FxProviderUnavailable)
    assert outcome.destination_context is None
    assert len(outcome.historical_suggestions) == 1
    assert outcome.historical_suggestions[0].side == "source"
    assert outcome.historical_suggestions[0].suggestion.suggested_currency_code == "FIM"
    latest_factory.assert_not_called()


@pytest.mark.django_db
def test_destination_context_failure_never_invalidates_conversion(reference_data):
    latest = FakeLatestGateway()
    command = ConverterSubmissionCommand(
        amount=Decimal("100"),
        source_country="FI",
        source_currency="EUR",
        destination_country="JP",
        destination_currency="JPY",
    )

    with patch(
        "apps.exchange.money_context.build_destination_context_default",
        side_effect=DatabaseError("context unavailable"),
    ):
        outcome = run_converter_submission(
            command,
            latest_gateway_factory=lambda: latest,
            historical_gateway_factory=Mock(),
            context_as_of=date(2026, 9, 22),
        )

    assert outcome.error is None
    assert outcome.conversion is not None
    assert outcome.conversion.output_amount == Decimal("17450")
    assert outcome.money_context is not None
    assert outcome.money_context.destination_state is MoneyContextState.DEGRADED
    assert outcome.destination_context is None


@pytest.mark.django_db
def test_unexpected_destination_context_programming_error_is_not_silenced(reference_data):
    latest = FakeLatestGateway()
    command = ConverterSubmissionCommand(
        amount=Decimal("100"),
        source_country="FI",
        source_currency="EUR",
        destination_country="JP",
        destination_currency="JPY",
    )

    with (
        patch(
            "apps.exchange.money_context.build_destination_context_default",
            side_effect=RuntimeError("programming bug"),
        ),
        pytest.raises(RuntimeError, match="programming bug"),
    ):
        run_converter_submission(
            command,
            latest_gateway_factory=lambda: latest,
            historical_gateway_factory=Mock(),
            context_as_of=date(2026, 9, 22),
        )


@pytest.mark.django_db
def test_historical_submission_requires_requested_date(reference_data):
    command = ConverterSubmissionCommand(
        amount=Decimal("100"),
        source_country="FI",
        source_currency="EUR",
        destination_country="JP",
        destination_currency="JPY",
        historical=True,
        requested_date=None,
    )

    with pytest.raises(ValueError, match="requires requested_date"):
        run_converter_submission(
            command,
            latest_gateway_factory=Mock(),
            historical_gateway_factory=Mock(),
        )
