from __future__ import annotations

from decimal import Decimal
from urllib.parse import urlencode

from django.conf import settings
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format

from apps.exchange.domain import ConversionResult, ObservationGranularity
from apps.exchange.forms import CurrentConversionForm, PaymentEstimateForm
from apps.exchange.trusted_snapshot import build_trusted_conversion_snapshot_token

_FEATURED_THEME_BY_COUNTRY = {
    "FI": "fi",
    "JP": "jp",
}
_ATLAS_THEME_KEYS = (
    "atlas-fjord",
    "atlas-moss",
    "atlas-clay",
    "atlas-slate",
    "atlas-sand",
    "atlas-plum",
)


def _country_theme(country_code: str) -> str:
    code = country_code.upper().strip()
    if not code:
        return ""
    featured = _FEATURED_THEME_BY_COUNTRY.get(code)
    if featured:
        return featured
    checksum = sum((index + 1) * ord(character) for index, character in enumerate(code))
    return _ATLAS_THEME_KEYS[checksum % len(_ATLAS_THEME_KEYS)]


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _money_text(value: Decimal, *, minor_units: int) -> str:
    return f"{value:.{minor_units}f}"


def _selected_value(form: CurrentConversionForm, field_name: str) -> str:
    value = form[field_name].value()
    return str(value or "").upper()


def _selection_context(form: CurrentConversionForm, side: str) -> dict[str, str]:
    country_code = _selected_value(form, f"{side}_country")
    currency_code = _selected_value(form, f"{side}_currency")
    country = form.country_for_code(country_code)
    currency = form.currency_for_code(currency_code)

    return {
        "country_code": country.iso2 if country else "",
        "country_name": country.name if country else "No country context",
        "currency_code": currency.code if currency else currency_code,
        "currency_name": currency.name if currency else "Choose currency",
        "theme": _country_theme(country.iso2) if country else "",
    }


def build_result_component(
    result: ConversionResult,
    *,
    form: CurrentConversionForm,
) -> dict[str, object]:
    base_currency = form.currency_for_code(result.quote.base_currency)
    quote_currency = form.currency_for_code(result.quote.quote_currency)
    base_minor_units = base_currency.minor_units if base_currency else 2
    quote_minor_units = quote_currency.minor_units if quote_currency else 2

    same_currency = result.quote.base_currency == result.quote.quote_currency
    historical = result.quote.historical
    used_previous = result.quote.used_previous_observation
    periodic_historical = historical and result.quote.observation_granularity in {
        ObservationGranularity.MONTHLY,
        ObservationGranularity.QUARTERLY,
    }
    provider_keys = ", ".join(key.upper() for key in result.quote.provider_keys)
    if same_currency:
        provider = "Exact same-currency rate"
        data_class = "Historical exact 1:1" if historical else "Exact 1:1"
        explanation = (
            "The currencies are identical, so no external historical observation is required."
            if historical
            else "The currencies are identical, so no external rate request is required."
        )
    else:
        provider = "Frankfurter"
        if provider_keys:
            provider = f"{provider} · {provider_keys}"
        if historical:
            if periodic_historical:
                period_label = result.quote.observation_granularity.value.capitalize()
                data_class = f"{period_label} historical observation"
                explanation = (
                    f"The selected provider publishes {period_label.lower()} observations. "
                    "This rate stands for its published period and is not presented as daily precision."
                )
            else:
                data_class = (
                    "Previous available observation" if used_previous else "Historical reference"
                )
                explanation = (
                    "The selected date had no accepted exact observation, so the nearest published "
                    "observation on or before it was used within the seven-day policy."
                    if used_previous
                    else "Historical reference exchange-rate data for the selected date."
                )
        else:
            data_class = "Cached reference" if result.stale else "Reference rate"
            explanation = (
                "A cached reference quote is being used because a fresh provider response is "
                "temporarily unavailable."
                if result.stale
                else "Reference exchange-rate data is informational; payment providers may use "
                "different rates or add fees."
            )

    requested_date = (
        date_format(result.quote.requested_date, "j M Y")
        if result.quote.requested_date is not None
        else None
    )
    effective_date = (
        date_format(result.quote.effective_date, "j M Y")
        if historical or not same_currency
        else None
    )
    fetched_at = None if same_currency else result.quote.fetched_at.strftime("%d %b %Y · %H:%M UTC")
    input_text = _money_text(result.input_amount, minor_units=base_minor_units)
    output_text = _money_text(result.output_amount, minor_units=quote_minor_units)
    rate_text = _decimal_text(result.quote.rate)

    source_country_code = _selected_value(form, "source_country")
    destination_country_code = _selected_value(form, "destination_country")
    source_country = form.country_for_code(source_country_code)
    destination_country = form.country_for_code(destination_country_code)

    story_date = (
        result.quote.requested_date
        if historical and result.quote.requested_date is not None
        else timezone.localdate()
    )
    story_params = {
        "source_country": source_country_code,
        "source_currency": result.quote.base_currency,
        "destination_country": destination_country_code,
        "destination_currency": result.quote.quote_currency,
        "selected_date": story_date.isoformat(),
        "historical": "1" if historical else "0",
    }
    current_context_params = {
        "country": destination_country_code,
        "currency": result.quote.quote_currency,
        "amount": format(result.output_amount, "f"),
    }

    trusted_snapshot_token = (
        build_trusted_conversion_snapshot_token(result) if not same_currency else None
    )
    payment_estimate_form = (
        PaymentEstimateForm(
            source_currency_code=result.quote.base_currency,
            destination_currency_code=result.quote.quote_currency,
            source_minor_units=base_minor_units,
            destination_minor_units=quote_minor_units,
        )
        if not historical and not same_currency
        else None
    )

    return {
        "id": "current-conversion-result",
        "input_amount": input_text,
        "input_currency": result.quote.base_currency,
        "output_amount": output_text,
        "output_currency": result.quote.quote_currency,
        "exact": same_currency,
        "stale": result.stale,
        "historical": historical,
        "local_state": {
            "input_amount": format(result.input_amount, "f"),
            "output_amount": format(result.output_amount, "f"),
            "source_currency": result.quote.base_currency,
            "destination_currency": result.quote.quote_currency,
            "source_country": source_country_code,
            "source_country_name": source_country.name if source_country else "",
            "destination_country": destination_country_code,
            "destination_country_name": destination_country.name if destination_country else "",
            "rate_mode": "historical" if historical else "latest",
            "requested_date": (
                result.quote.requested_date.isoformat()
                if result.quote.requested_date is not None
                else ""
            ),
            "effective_date": result.quote.effective_date.isoformat(),
        },
        "money_culture_story": {
            "href": f"{reverse('money_culture_story')}?{urlencode(story_params)}",
            "historical": historical,
        },
        "current_destination_context": (
            {
                "href": (
                    f"{reverse('current_destination_context')}?{urlencode(current_context_params)}"
                ),
                "country_name": (
                    destination_country.name if destination_country else destination_country_code
                ),
                "currency_code": result.quote.quote_currency,
            }
            if historical and destination_country_code
            else None
        ),
        "ai_explanation": (
            {
                "token": trusted_snapshot_token,
                "label": "Optional AI explanation",
            }
            if settings.AI_RUNTIME_EXPLANATION_ENABLED and not same_currency
            else None
        ),
        "payment_estimate": (
            {
                "token": trusted_snapshot_token,
                "form": payment_estimate_form,
                "source_currency": result.quote.base_currency,
                "destination_currency": result.quote.quote_currency,
                "reference_amount": output_text,
                "effective_date": effective_date,
                "provider": provider,
                "stale": result.stale,
            }
            if payment_estimate_form is not None
            else None
        ),
        "historical_trend": (
            {
                "base_currency": result.quote.base_currency,
                "quote_currency": result.quote.quote_currency,
                "amount": format(result.input_amount, "f"),
                "selected_date_iso": result.quote.effective_date.isoformat(),
                "requested_date_iso": (
                    result.quote.requested_date.isoformat()
                    if result.quote.requested_date is not None
                    else result.quote.effective_date.isoformat()
                ),
            }
            if historical and not same_currency
            else None
        ),
        "status": (
            {"kind": "historical", "label": "Historical exact 1:1"}
            if historical and same_currency
            else (
                {
                    "kind": "historical-period",
                    "label": (
                        f"{result.quote.observation_granularity.value.capitalize()} "
                        "historical observation"
                    ),
                }
                if periodic_historical
                else (
                    {
                        "kind": "historical-previous" if used_previous else "historical",
                        "label": (
                            "Previous available observation"
                            if used_previous
                            else "Historical reference"
                        ),
                    }
                    if historical
                    else (
                        {"kind": "exact", "label": "Exact 1:1"}
                        if same_currency
                        else {
                            "kind": "cached" if result.stale else "reference",
                            "label": "Cached reference" if result.stale else "Reference rate",
                        }
                    )
                )
            )
        ),
        "rate_meta": {
            "rate_line": (
                f"1 {result.quote.base_currency} = {rate_text} {result.quote.quote_currency}"
            ),
            "data_class": data_class,
            "requested_date": requested_date,
            "effective_date": effective_date,
            "effective_date_label": "Observation date" if historical else "Effective date",
            "observation_frequency": (
                result.quote.observation_granularity.value.capitalize()
                if periodic_historical
                else None
            ),
            "provider": provider,
            "fetched_at": fetched_at,
            "explanation": explanation,
        },
        "announcement": (
            (
                f"{input_text} {result.quote.base_currency} remains "
                f"{output_text} {result.quote.quote_currency}. "
                + (
                    f"Historical identity conversion for {requested_date}."
                    if historical
                    else "No exchange-rate lookup was required."
                )
            )
            if same_currency
            else (
                f"{input_text} {result.quote.base_currency} is approximately "
                f"{output_text} {result.quote.quote_currency}. "
                + (
                    (
                        f"{result.quote.observation_granularity.value.capitalize()} historical "
                        f"observation effective {effective_date}."
                    )
                    if periodic_historical
                    else (
                        (
                            f"Requested {requested_date}; previous available observation "
                            f"{effective_date}."
                        )
                        if used_previous
                        else (
                            f"Historical observation {effective_date}."
                            if historical
                            else f"Reference rate effective {effective_date}."
                        )
                    )
                )
            )
        ),
    }


def _build_error_summary(form: CurrentConversionForm) -> list[dict[str, str]]:
    if len(form.errors) < 2:
        return []

    summary: list[dict[str, str]] = []
    for field_name, errors in form.errors.items():
        if not errors:
            continue
        if field_name == "__all__":
            summary.append(
                {
                    "href": "#current-conversion-form",
                    "label": "Conversion",
                    "message": str(errors[0]),
                }
            )
            continue

        bound_field = form[field_name]
        summary.append(
            {
                "href": f"#{bound_field.id_for_label}",
                "label": bound_field.label,
                "message": str(errors[0]),
            }
        )
    return summary


def build_converter_context(
    form: CurrentConversionForm,
    *,
    result: ConversionResult | None = None,
    conversion_error: dict[str, str] | None = None,
    validation_attempted: bool = False,
    conversion_active: bool = False,
    preserve_previous_result: bool = False,
    historical_currency_suggestions: list[tuple[str, object]] | None = None,
    destination_context_component: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "form": form,
        "source": _selection_context(form, "source"),
        "destination": _selection_context(form, "destination"),
        "result_component": build_result_component(result, form=form) if result else None,
        "conversion_error": conversion_error,
        "error_summary": _build_error_summary(form) if validation_attempted else [],
        "has_result": result is not None,
        "conversion_active": conversion_active or result is not None,
        "preserve_previous_result": preserve_previous_result,
        "historical_currency_suggestions": historical_currency_suggestions or [],
        "destination_context_component": destination_context_component,
        "reference_data_ready": form.reference_data_ready,
    }
