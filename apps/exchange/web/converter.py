from __future__ import annotations

import logging
from collections.abc import Callable
from urllib.parse import urlencode

from django.conf import settings
from django.db import DatabaseError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.cache import patch_vary_headers
from django.views.decorators.http import require_http_methods

from apps.accounts.preferences import home_currency_code
from apps.countries.models import City, CountryCurrency, Currency
from apps.culture.media import select_destination_media
from apps.culture.presentation import build_destination_context_component
from apps.exchange.application import ConverterSubmissionCommand, run_converter_submission
from apps.exchange.budget_presets import budget_presets_for_categories
from apps.exchange.cache import HistoricalQuoteGateway, LatestQuoteGateway
from apps.exchange.domain import (
    HistoricalCoverageReason,
    HistoricalObservationUnavailable,
    HistoricalOutOfCoverage,
)
from apps.exchange.fee_profiles import fee_profiles_for_pair
from apps.exchange.forms import RATE_MODE_HISTORICAL, CurrentConversionForm
from apps.exchange.presentation import build_converter_context
from apps.exchange.providers.base import (
    FxProviderError,
    FxProviderInvalidPayload,
    FxProviderUnavailable,
    FxProviderUnsupportedPair,
)
from apps.exchange.web.common import is_history_restore, is_htmx
from apps.travel.home import build_returning_trip_home

logger = logging.getLogger("cultural_currency.exchange")


def _country_for_currency(currency_code: str, *, preferred: str = "") -> str:
    links = CountryCurrency.objects.current().filter(currency__code=currency_code).primary()
    if preferred:
        preferred_match = (
            links.filter(country__iso2=preferred).values_list("country__iso2", flat=True).first()
        )
        if preferred_match:
            return preferred_match
    return links.values_list("country__iso2", flat=True).first() or ""


def _loaded_pair_initial(query) -> dict[str, str]:
    initial = _default_initial()
    initial["amount"] = ""

    for side in ("source", "destination"):
        currency_code = str(query.get(f"{side}_currency") or "").upper().strip()
        if not currency_code:
            continue
        if not Currency.objects.filter(code=currency_code, is_active=True).exists():
            continue

        initial[f"{side}_currency"] = currency_code
        country_code = str(query.get(f"{side}_country") or "").upper().strip()
        if not country_code:
            initial[f"{side}_country"] = ""
            continue

        associated = CountryCurrency.objects.current().filter(
            country__iso2=country_code,
            currency__code=currency_code,
        )
        initial[f"{side}_country"] = country_code if associated.exists() else ""

    destination_country = initial.get("destination_country", "")
    city_slug = str(query.get("destination_city_slug") or "").strip().lower()
    if destination_country and city_slug:
        city_exists = City.objects.filter(
            country__iso2=destination_country,
            country__is_active=True,
            slug=city_slug,
            is_active=True,
        ).exists()
        if city_exists:
            initial["destination_city_slug"] = city_slug

    return initial


def _default_initial(*, preferred_source_currency: str = "") -> dict[str, str]:
    currency_codes = list(
        Currency.objects.filter(is_active=True).order_by("code").values_list("code", flat=True)
    )
    if not currency_codes:
        return {"amount": "100.00"}

    source_currency = (
        preferred_source_currency
        if preferred_source_currency in currency_codes
        else "EUR"
        if "EUR" in currency_codes
        else currency_codes[0]
    )
    destination_currency = (
        "JPY"
        if "JPY" in currency_codes
        else next((code for code in currency_codes if code != source_currency), source_currency)
    )
    return {
        "amount": "100.00",
        "source_country": _country_for_currency(source_currency, preferred="FI"),
        "source_currency": source_currency,
        "destination_country": _country_for_currency(destination_currency, preferred="JP"),
        "destination_currency": destination_currency,
    }


def _canonical_conversion_url(form: CurrentConversionForm) -> str:
    cleaned = form.cleaned_data
    params = {
        "convert": "1",
        "amount": format(cleaned["amount_decimal"], "f"),
        "source_country": cleaned.get("source_country", ""),
        "source_currency": cleaned["source_currency"],
        "destination_country": cleaned.get("destination_country", ""),
        "destination_currency": cleaned["destination_currency"],
    }
    destination_city_slug = str(cleaned.get("destination_city_slug") or "")
    if destination_city_slug:
        params["destination_city_slug"] = destination_city_slug
    if cleaned.get("rate_mode") == RATE_MODE_HISTORICAL:
        params["rate_mode"] = RATE_MODE_HISTORICAL
        params["requested_date"] = cleaned["requested_date"].isoformat()
    return f"{reverse('converter')}?{urlencode(params)}"


def _converter_submission_command(form: CurrentConversionForm) -> ConverterSubmissionCommand:
    cleaned = form.cleaned_data
    return ConverterSubmissionCommand(
        amount=cleaned["amount_decimal"],
        source_country=cleaned.get("source_country", ""),
        source_currency=cleaned["source_currency"],
        destination_country=cleaned.get("destination_country", ""),
        destination_currency=cleaned["destination_currency"],
        destination_city_slug=str(cleaned.get("destination_city_slug") or ""),
        historical=cleaned.get("rate_mode") == RATE_MODE_HISTORICAL,
        requested_date=cleaned.get("requested_date"),
    )


def _historical_currency_payload(request: HttpRequest):
    value = request.POST.get("historical_currency_action", "")
    try:
        side, currency_code = value.split(":", 1)
    except ValueError:
        return request.POST
    if side not in {"source", "destination"}:
        return request.POST

    payload = request.POST.copy()
    payload[f"{side}_currency"] = currency_code.upper()
    return payload


def _swap_payload(request: HttpRequest):
    payload = request.POST.copy()
    payload["source_country"], payload["destination_country"] = (
        payload.get("destination_country", ""),
        payload.get("source_country", ""),
    )
    payload["source_currency"], payload["destination_currency"] = (
        payload.get("destination_currency", ""),
        payload.get("source_currency", ""),
    )
    payload["destination_city_slug"] = ""
    return payload


def _conversion_error(
    exc: FxProviderError | HistoricalObservationUnavailable | HistoricalOutOfCoverage,
    *,
    historical: bool = False,
) -> dict[str, str]:
    if isinstance(exc, HistoricalOutOfCoverage):
        boundary = exc.boundary.strftime("%d %b %Y")
        if exc.reason is HistoricalCoverageReason.CURRENCY_NOT_YET_ACTIVE:
            detail = (
                f"{exc.currency_code} was not yet active on the selected date. "
                f"Known lifecycle starts {boundary}."
            )
        elif exc.reason is HistoricalCoverageReason.CURRENCY_RETIRED:
            detail = (
                f"{exc.currency_code} was already retired on the selected date. "
                f"Known lifecycle ends {boundary}."
            )
        elif exc.reason is HistoricalCoverageReason.PROVIDER_COVERAGE_NOT_STARTED:
            detail = (
                f"The rate source has no {exc.currency_code} observations that far back. "
                f"Known provider coverage starts {boundary}."
            )
        else:
            detail = (
                f"The rate source has no {exc.currency_code} observations that late. "
                f"Known provider coverage ends {boundary}."
            )
        return {
            "title": "The selected date is outside known historical coverage.",
            "detail": detail,
        }
    if isinstance(exc, HistoricalObservationUnavailable):
        return {
            "title": "No nearby historical observation is available.",
            "detail": (
                "No published observation falls within the allowed window for this dataset's "
                "observation frequency. Choose another date."
            ),
        }
    if isinstance(exc, FxProviderUnsupportedPair):
        if historical:
            return {
                "title": "No historical observation is available for this pair and date.",
                "detail": (
                    "Try another date or currency pair. Historical provider coverage can differ "
                    "from current coverage."
                ),
            }
        return {
            "title": "This currency pair is not available.",
            "detail": "Choose another supported currency pair and try again.",
        }
    if isinstance(exc, FxProviderInvalidPayload):
        return {
            "title": "The rate source returned unusable data.",
            "detail": "No conversion was shown. Try again in a moment.",
        }
    if isinstance(exc, FxProviderUnavailable):
        return {
            "title": "Reference rates are temporarily unavailable.",
            "detail": "Your selections are preserved. Try the conversion again shortly.",
        }
    return {
        "title": "The conversion could not be completed.",
        "detail": "Your selections are preserved. Try again.",
    }


@require_http_methods(["GET", "POST"])
def converter_view(
    request: HttpRequest,
    *,
    latest_gateway_factory: Callable[[], LatestQuoteGateway],
    historical_gateway_factory: Callable[[], HistoricalQuoteGateway],
    record_recent_conversion_fn: Callable[..., object | None],
    is_user_favourite_fn: Callable[..., bool],
) -> HttpResponse:
    convert_requested = False
    load_pair_requested = False
    conversion_active = False

    if request.method == "POST":
        swapping = request.POST.get("action") == "swap"
        using_historical_currency = bool(request.POST.get("historical_currency_action"))
        conversion_active = request.POST.get("conversion_active") == "1"
        if using_historical_currency:
            data = _historical_currency_payload(request)
        elif swapping:
            data = _swap_payload(request)
        else:
            data = request.POST
        form = CurrentConversionForm(data)
        convert_requested = using_historical_currency or not swapping or conversion_active
    else:
        convert_requested = request.GET.get("convert") == "1"
        load_pair_requested = request.GET.get("load") == "1"
        if convert_requested:
            form = CurrentConversionForm(request.GET)
        elif load_pair_requested:
            form = CurrentConversionForm(initial=_loaded_pair_initial(request.GET))
        else:
            preferred_source_currency = ""
            if request.user.is_authenticated:
                try:
                    preferred_source_currency = home_currency_code(request.user)
                except DatabaseError as exc:
                    logger.warning(
                        "Home currency preference lookup failed",
                        extra={"error_code": exc.__class__.__name__},
                    )
            form = CurrentConversionForm(
                initial=_default_initial(
                    preferred_source_currency=preferred_source_currency,
                )
            )

    result = None
    error = None
    historical_suggestions = []
    destination_context_component = None
    money_context = None
    response_status = 200
    form_valid = form.is_valid() if convert_requested else False
    if form_valid:
        command = _converter_submission_command(form)
        submission = run_converter_submission(
            command,
            latest_gateway_factory=latest_gateway_factory,
            historical_gateway_factory=historical_gateway_factory,
        )
        historical_suggestions = [
            (item.side, item.suggestion) for item in submission.historical_suggestions
        ]

        if submission.error is not None:
            exc = submission.error
            if isinstance(
                exc,
                (
                    FxProviderUnsupportedPair,
                    HistoricalObservationUnavailable,
                    HistoricalOutOfCoverage,
                ),
            ):
                response_status = 422
            elif isinstance(exc, FxProviderInvalidPayload):
                response_status = 502
            else:
                response_status = 503

            logger.warning(
                "FX conversion provider failure",
                extra={
                    "provider": "frankfurter",
                    "error_code": exc.__class__.__name__,
                },
            )
            error = _conversion_error(exc, historical=command.historical)
        else:
            result = submission.conversion
            if result is None:
                raise RuntimeError("Successful converter submission returned no conversion.")
            money_context = submission.money_context
            destination_context = (
                money_context.destination_context if money_context is not None else None
            )
            if destination_context is not None:
                destination_media = select_destination_media(destination_context.country_code)
                destination_context_component = build_destination_context_component(
                    destination_context,
                    historical=False,
                    hero_image=destination_media.hero,
                    everyday_value_image=destination_media.everyday_value,
                    payment_culture_image=destination_media.payment_culture,
                    local_detail_image=destination_media.local_detail,
                )

    if convert_requested and not form_valid and request.method == "POST":
        response_status = 422

    account_recent_history_recorded = False
    if result is not None and request.user.is_authenticated and not is_history_restore(request):
        try:
            account_recent_history_recorded = (
                record_recent_conversion_fn(
                    request.user,
                    source_currency_code=result.quote.base_currency,
                    destination_currency_code=result.quote.quote_currency,
                    source_country_code=form.cleaned_data.get("source_country", ""),
                    destination_country_code=form.cleaned_data.get("destination_country", ""),
                    input_amount=result.input_amount,
                    output_amount=result.output_amount,
                    historical=result.quote.historical,
                    requested_date=result.quote.requested_date,
                    effective_date=result.quote.effective_date,
                )
                is not None
            )
        except DatabaseError as exc:
            logger.warning(
                "Account recent-history write failed",
                extra={"error_code": exc.__class__.__name__},
            )

    if request.method == "POST" and not is_htmx(request) and result is not None:
        return redirect(_canonical_conversion_url(form))

    preserve_previous_result = (
        is_htmx(request)
        and conversion_active
        and result is None
        and response_status in {422, 502, 503}
    )
    account_favourite_saved = False
    if result is not None and request.user.is_authenticated:
        try:
            account_favourite_saved = is_user_favourite_fn(
                request.user,
                source_currency=form.cleaned_data["source_currency"],
                destination_currency=form.cleaned_data["destination_currency"],
                source_country=form.cleaned_data.get("source_country", ""),
                destination_country=form.cleaned_data.get("destination_country", ""),
            )
        except DatabaseError as exc:
            logger.warning(
                "Account favourite lookup failed",
                extra={"error_code": exc.__class__.__name__},
            )

    context = build_converter_context(
        form,
        result=result,
        conversion_error=error,
        validation_attempted=convert_requested,
        conversion_active=conversion_active,
        preserve_previous_result=preserve_previous_result,
        historical_currency_suggestions=historical_suggestions,
        destination_context_component=destination_context_component,
        money_context=money_context,
    )
    context["account_favourite_saved"] = account_favourite_saved
    context["account_recent_history_recorded"] = account_recent_history_recorded

    if result is not None and request.user.is_authenticated and not result.quote.historical:
        result_component = context.get("result_component")
        payment_component = (
            result_component.get("payment_estimate") if isinstance(result_component, dict) else None
        )
        if isinstance(payment_component, dict):
            try:
                payment_component["fee_profiles"] = fee_profiles_for_pair(
                    request.user,
                    source_currency_code=result.quote.base_currency,
                    destination_currency_code=result.quote.quote_currency,
                )
            except DatabaseError as exc:
                logger.warning(
                    "Payment fee profile lookup failed",
                    extra={"error_code": exc.__class__.__name__},
                )
                payment_component["fee_profiles"] = ()

        budget_component = (
            result_component.get("budget_interpretation")
            if isinstance(result_component, dict)
            else None
        )
        if isinstance(budget_component, dict):
            available_categories = {
                str(item.get("category") or "")
                for item in budget_component.get("fields", ())
                if isinstance(item, dict) and item.get("category")
            }
            try:
                budget_component["budget_presets"] = (
                    budget_presets_for_categories(
                        request.user,
                        available_categories=frozenset(available_categories),
                    )
                    if available_categories
                    else ()
                )
            except DatabaseError as exc:
                logger.warning(
                    "Budget preset lookup failed",
                    extra={"error_code": exc.__class__.__name__},
                )
                budget_component["budget_presets"] = ()

    returning_trip_home = None
    if (
        request.method == "GET"
        and not convert_requested
        and not load_pair_requested
        and request.user.is_authenticated
        and not is_htmx(request)
    ):
        try:
            returning_trip_home = build_returning_trip_home(
                request.user,
                camera_enabled=bool(settings.AI_CAMERA_EXTRACTION_ENABLED),
            )
        except DatabaseError as exc:
            logger.warning(
                "Returning-trip home composition failed",
                extra={"error_code": exc.__class__.__name__},
            )
    context["returning_trip_home"] = returning_trip_home

    fragment = is_htmx(request) and not is_history_restore(request)
    template = "components/converter/current_panel.html" if fragment else "pages/converter.html"
    response = render(request, template, context, status=response_status)
    patch_vary_headers(response, ["HX-Request", "HX-History-Restore-Request"])

    if fragment and result is not None:
        response["HX-Push-Url"] = _canonical_conversion_url(form)
    return response
