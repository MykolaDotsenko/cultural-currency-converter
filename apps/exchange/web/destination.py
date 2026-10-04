from __future__ import annotations

import logging
from urllib.parse import urlencode

from django.db import DatabaseError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from apps.accounts.preferences import home_currency_code
from apps.exchange.forms import DestinationModeForm

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
        },
        status=422 if request.method == "POST" else 200,
    )
