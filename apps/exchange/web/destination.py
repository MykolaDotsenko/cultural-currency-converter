from __future__ import annotations

import logging
from urllib.parse import urlencode

from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from apps.accounts.preferences import home_currency_code
from apps.exchange.forms import DestinationModeForm, parse_amount_text

logger = logging.getLogger("cultural_currency.exchange")


@require_http_methods(["GET", "POST"])
def destination_mode_view(request: HttpRequest) -> HttpResponse:
    """Resolve a destination-first plan into the canonical converter."""

    initial = None
    if request.method == "GET":
        initial_values: dict[str, str] = {}
        destination_token = str(request.GET.get("destination") or "").strip()
        if destination_token:
            initial_values["destination"] = destination_token
        if request.user.is_authenticated:
            try:
                preferred_source_currency = home_currency_code(request.user)
            except DatabaseError as exc:
                logger.warning(
                    "Home currency preference lookup failed",
                    extra={"error_code": exc.__class__.__name__},
                )
            else:
                if preferred_source_currency:
                    initial_values["source_currency"] = preferred_source_currency
        initial = initial_values or None
    form = DestinationModeForm(
        request.POST if request.method == "POST" else None,
        initial=initial,
    )
    # A saved-history link supplies inputs only, never an old rate or output.
    # Accept explicit overrides only when they pass the canonical form's
    # current-currency and Decimal/minor-unit validation policy.
    if request.method == "GET":
        source_code = str(request.GET.get("source_currency") or "").strip().upper()
        selected_source = form.active_source_currency(source_code) if source_code else None
        if selected_source is not None:
            form.initial["source_currency"] = selected_source.code
        # Never re-label an amount from an unsupported source currency with
        # an unrelated default (e.g. archived FIM as current EUR).
        source = (
            selected_source
            if source_code
            else form.active_source_currency(str(form.initial.get("source_currency") or ""))
        )
        candidate = str(request.GET.get("amount") or "").strip()
        if source is not None and 0 < len(candidate) <= 64:
            try:
                amount = parse_amount_text(candidate, minor_units=source.minor_units)
            except ValidationError:
                pass
            else:
                form.initial["amount"] = format(amount, "f")

    if request.method == "POST" and form.is_valid():
        cleaned = form.cleaned_data
        params = {
            "convert": "1",
            "amount": format(cleaned["amount_decimal"], "f"),
            "source_country": "",
            "source_currency": cleaned["source_currency"],
            "destination_country": cleaned["destination_country"],
            "destination_currency": cleaned["destination_currency"],
        }
        city_slug = str(cleaned.get("destination_city_slug") or "")
        if city_slug:
            params["destination_city_slug"] = city_slug
        return redirect(f"{reverse('converter')}?{urlencode(params)}")

    return render(
        request,
        "pages/destination_mode.html",
        {
            "form": form,
            "reference_data_ready": form.reference_data_ready,
            "replanned_from_history": (
                request.method == "GET" and request.GET.get("from_history") == "1"
            ),
        },
        status=422 if request.method == "POST" else 200,
    )
