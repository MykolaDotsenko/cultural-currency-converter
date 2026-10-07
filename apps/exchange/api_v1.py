from __future__ import annotations

import json
from decimal import Decimal

from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from apps.countries.models import City, CountryCurrency, Currency
from apps.culture.services import PurchaseEquivalent
from apps.exchange.application import (
    ConverterSubmissionCommand,
    ConverterSubmissionError,
    run_converter_submission,
)
from apps.exchange.domain import HistoricalObservationUnavailable, HistoricalOutOfCoverage
from apps.exchange.forms import RATE_MODE_HISTORICAL, RATE_MODE_LATEST, CurrentConversionForm
from apps.exchange.money_context import MoneyContext
from apps.exchange.providers.base import (
    FxProviderInvalidPayload,
    FxProviderUnavailable,
    FxProviderUnsupportedPair,
)
from apps.exchange.web.gateways import build_historical_quote_gateway, build_latest_quote_gateway

_API_VERSION = "1"
_MAX_JSON_BODY_BYTES = 16 * 1024
_CONVERSION_FIELDS = frozenset(
    {
        "amount",
        "sourceCountry",
        "sourceCurrency",
        "destinationCountry",
        "destinationCurrency",
        "destinationCitySlug",
        "rateMode",
        "requestedDate",
    }
)


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


def _api_response(
    payload: dict[str, object],
    *,
    status: int = 200,
    cache_control: str = "private, no-store",
) -> JsonResponse:
    response = JsonResponse(payload, status=status)
    response["X-API-Version"] = _API_VERSION
    response["Cache-Control"] = cache_control
    response["X-Content-Type-Options"] = "nosniff"
    return response


def _api_error(
    *,
    code: str,
    message: str,
    status: int,
    fields: dict[str, list[str]] | None = None,
    details: dict[str, object] | None = None,
) -> JsonResponse:
    error: dict[str, object] = {"code": code, "message": message}
    if fields:
        error["fields"] = fields
    if details:
        error["details"] = details
    return _api_response({"schemaVersion": _API_VERSION, "error": error}, status=status)


def _content_length(request: HttpRequest) -> int | None:
    raw = request.META.get("CONTENT_LENGTH")
    if not raw:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def _json_body(request: HttpRequest) -> dict[str, object] | JsonResponse:
    if request.content_type != "application/json":
        return _api_error(
            code="unsupported_media_type",
            message="Content-Type must be application/json.",
            status=415,
        )

    declared = _content_length(request)
    if declared is not None and declared > _MAX_JSON_BODY_BYTES:
        return _api_error(
            code="payload_too_large",
            message="JSON request body is too large.",
            status=413,
        )

    body = request.body
    if len(body) > _MAX_JSON_BODY_BYTES:
        return _api_error(
            code="payload_too_large",
            message="JSON request body is too large.",
            status=413,
        )

    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _api_error(
            code="invalid_json",
            message="Request body must contain valid UTF-8 JSON.",
            status=400,
        )

    if not isinstance(payload, dict):
        return _api_error(
            code="invalid_request",
            message="Request body must be a JSON object.",
            status=400,
        )
    return payload


def _optional_text(payload: dict[str, object], key: str) -> str:
    value = payload.get(key, "")
    if value is None:
        return ""
    return value if isinstance(value, str) else ""


def _conversion_form_payload(payload: dict[str, object]) -> dict[str, str]:
    rate_mode = payload.get("rateMode", RATE_MODE_LATEST)
    requested_date = payload.get("requestedDate", "")
    return {
        "amount": payload.get("amount", "") if isinstance(payload.get("amount"), str) else "",
        "source_country": _optional_text(payload, "sourceCountry"),
        "source_currency": _optional_text(payload, "sourceCurrency"),
        "destination_country": _optional_text(payload, "destinationCountry"),
        "destination_currency": _optional_text(payload, "destinationCurrency"),
        "destination_city_slug": _optional_text(payload, "destinationCitySlug"),
        "rate_mode": rate_mode if isinstance(rate_mode, str) else "",
        "requested_date": requested_date if isinstance(requested_date, str) else "",
    }


def _form_errors(form: CurrentConversionForm) -> dict[str, list[str]]:
    return {
        field: [str(message) for message in messages]
        for field, messages in form.errors.items()
    }


def _conversion_command(form: CurrentConversionForm) -> ConverterSubmissionCommand:
    cleaned = form.cleaned_data
    return ConverterSubmissionCommand(
        amount=cleaned["amount_decimal"],
        source_country=str(cleaned.get("source_country") or ""),
        source_currency=cleaned["source_currency"],
        destination_country=str(cleaned.get("destination_country") or ""),
        destination_currency=cleaned["destination_currency"],
        destination_city_slug=str(cleaned.get("destination_city_slug") or ""),
        historical=cleaned.get("rate_mode") == RATE_MODE_HISTORICAL,
        requested_date=cleaned.get("requested_date"),
    )


def _purchase_equivalent(item: PurchaseEquivalent) -> dict[str, str]:
    return {
        "minimumCount": _decimal_text(item.minimum_count),
        "maximumCount": _decimal_text(item.maximum_count),
        "status": item.status,
    }


def _money_context_payload(context: MoneyContext) -> dict[str, object]:
    destination = context.destination_context
    destination_payload: dict[str, object] | None = None
    if destination is not None:
        payment = destination.payment
        destination_payload = {
            "countryCode": destination.country_code,
            "countryName": destination.country_name,
            "citySlug": destination.city_slug,
            "cityName": destination.city_name,
            "asOf": destination.as_of.isoformat(),
            "prices": [
                {
                    "label": item.label,
                    "category": item.category,
                    "scopeLabel": item.scope_label,
                    "city": item.city,
                    "citySlug": item.city_slug,
                    "countryName": item.country_name,
                    "currencyCode": item.currency_code,
                    "amountLow": _decimal_text(item.amount_low),
                    "amountHigh": (
                        _decimal_text(item.amount_high) if item.amount_high is not None else None
                    ),
                    "observedAt": item.observed_at.isoformat(),
                    "sourceClass": item.source_class,
                    "confidence": item.confidence,
                    "sourceName": item.source_name,
                    "sourceUrl": item.source_url,
                    "equivalent": _purchase_equivalent(item.equivalent),
                }
                for item in destination.prices
            ],
            "payment": (
                {
                    "summary": payment.summary,
                    "paymentCustoms": payment.payment_customs,
                    "cashUsage": payment.cash_usage,
                    "tipping": payment.tipping,
                    "atmNotes": payment.atm_notes,
                    "dccWarning": payment.dcc_warning,
                    "sourceName": payment.source_name,
                    "sourceUrl": payment.source_url,
                    "verifiedAt": payment.verified_at.isoformat(),
                }
                if payment is not None
                else None
            ),
        }

    return {
        "state": context.destination_state.value,
        "countryCode": context.destination_country_code,
        "citySlug": context.destination_city_slug,
        "asOf": context.as_of.isoformat(),
        "destination": destination_payload,
    }


def _conversion_payload(context: MoneyContext) -> dict[str, object]:
    conversion = context.conversion
    quote = conversion.quote
    return {
        "inputAmount": _decimal_text(conversion.input_amount),
        "outputAmount": _decimal_text(conversion.output_amount),
        "baseCurrency": quote.base_currency,
        "quoteCurrency": quote.quote_currency,
        "rate": _decimal_text(quote.rate),
        "requestedDate": quote.requested_date.isoformat() if quote.requested_date else None,
        "effectiveDate": quote.effective_date.isoformat(),
        "fetchedAt": quote.fetched_at.isoformat(),
        "historical": quote.historical,
        "observationGranularity": quote.observation_granularity.value,
        "providerKeys": list(quote.provider_keys),
        "stale": conversion.stale,
        "exact": quote.base_currency == quote.quote_currency,
    }


def _submission_error_response(error: ConverterSubmissionError) -> JsonResponse:
    if isinstance(error, HistoricalOutOfCoverage):
        return _api_error(
            code="historical_out_of_coverage",
            message="The selected date is outside known historical coverage.",
            status=422,
            details={
                "currencyCode": error.currency_code,
                "requestedDate": error.requested_date.isoformat(),
                "reason": error.reason.value,
                "boundary": error.boundary.isoformat(),
            },
        )
    if isinstance(error, HistoricalObservationUnavailable):
        return _api_error(
            code="historical_observation_unavailable",
            message="No nearby historical observation is available.",
            status=422,
        )
    if isinstance(error, FxProviderUnsupportedPair):
        return _api_error(
            code="unsupported_pair",
            message="This currency pair is not available for the requested rate mode.",
            status=422,
        )
    if isinstance(error, FxProviderInvalidPayload):
        return _api_error(
            code="provider_invalid_payload",
            message="The rate source returned unusable data.",
            status=502,
        )
    if isinstance(error, FxProviderUnavailable):
        return _api_error(
            code="provider_unavailable",
            message="Reference rates are temporarily unavailable.",
            status=503,
        )
    return _api_error(
        code="conversion_unavailable",
        message="The conversion could not be completed.",
        status=503,
    )


@require_GET
def api_v1_root(request: HttpRequest) -> JsonResponse:
    return _api_response(
        {
            "schemaVersion": _API_VERSION,
            "data": {
                "apiVersion": _API_VERSION,
                "capabilities": [
                    "reference_metadata",
                    "canonical_conversion",
                    "money_context",
                    "historical_conversion",
                ],
                "accountMutationApi": False,
            },
        },
        cache_control="public, max-age=300",
    )


@require_GET
def api_v1_reference(request: HttpRequest) -> JsonResponse:
    currencies = list(
        Currency.objects.filter(is_active=True)
        .order_by("code")
        .values("code", "name", "symbol", "minor_units")
    )

    links = tuple(
        CountryCurrency.objects.current()
        .primary()
        .select_related("country", "currency")
        .order_by("country__name", "country__iso2")
    )
    country_ids = [link.country_id for link in links]
    cities_by_country: dict[int, list[dict[str, str]]] = {}
    if country_ids:
        for city in (
            City.objects.filter(
                is_active=True,
                country_id__in=country_ids,
                country__is_active=True,
            )
            .only("country_id", "slug", "name", "region")
            .order_by("country__name", "name", "slug")
        ):
            cities_by_country.setdefault(city.country_id, []).append(
                {
                    "slug": city.slug,
                    "name": city.name,
                    "region": city.region,
                }
            )

    destinations = [
        {
            "countryCode": link.country.iso2,
            "countryName": link.country.name,
            "region": link.country.region,
            "subregion": link.country.subregion,
            "currencyCode": link.currency.code,
            "cities": cities_by_country.get(link.country_id, []),
        }
        for link in links
    ]

    return _api_response(
        {
            "schemaVersion": _API_VERSION,
            "data": {
                "currencies": [
                    {
                        "code": row["code"],
                        "name": row["name"],
                        "symbol": row["symbol"],
                        "minorUnits": row["minor_units"],
                    }
                    for row in currencies
                ],
                "destinations": destinations,
            },
        },
        cache_control="public, max-age=300",
    )


@csrf_exempt
@require_POST
def api_v1_conversion(request: HttpRequest) -> JsonResponse:
    payload = _json_body(request)
    if isinstance(payload, JsonResponse):
        return payload

    unknown = sorted(set(payload) - _CONVERSION_FIELDS)
    if unknown:
        return _api_error(
            code="unknown_fields",
            message="Request contains unsupported fields.",
            status=400,
            details={"fields": unknown},
        )

    if not isinstance(payload.get("amount"), str):
        return _api_error(
            code="invalid_request",
            message="amount must be a decimal string.",
            status=400,
            fields={"amount": ["Use a decimal string such as 100.00."]},
        )

    form = CurrentConversionForm(_conversion_form_payload(payload))
    if not form.is_valid():
        return _api_error(
            code="validation_error",
            message="Conversion inputs are invalid.",
            status=422,
            fields=_form_errors(form),
        )

    command = _conversion_command(form)
    submission = run_converter_submission(
        command,
        latest_gateway_factory=build_latest_quote_gateway,
        historical_gateway_factory=build_historical_quote_gateway,
    )
    if submission.error is not None:
        return _submission_error_response(submission.error)
    if submission.money_context is None:
        return _api_error(
            code="conversion_unavailable",
            message="The conversion returned no usable result.",
            status=503,
        )

    return _api_response(
        {
            "schemaVersion": _API_VERSION,
            "data": {
                "conversion": _conversion_payload(submission.money_context),
                "moneyContext": _money_context_payload(submission.money_context),
            },
        }
    )
