from __future__ import annotations

import json
from decimal import Decimal
from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.db import DatabaseError
from django.http import HttpRequest, JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.travel.browser_scenario import (
    BrowserScenarioTokenError,
    build_browser_scenario_token,
    import_browser_scenarios,
)
from apps.travel.models import SavedScenarioKind
from apps.travel.scenario_drafts import (
    ScenarioDraft,
    ScenarioDraftError,
    build_budget_scenario_draft,
    build_shopping_scenario_draft,
)

_MAX_IMPORT_BODY_BYTES = 320 * 1024


def _json_error(
    code: str,
    message: str,
    *,
    status: int,
) -> JsonResponse:
    response = JsonResponse({"error": {"code": code, "message": message}}, status=status)
    response["Cache-Control"] = "private, no-store"
    return response


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _budget_reopen_url(draft: ScenarioDraft) -> str:
    spec = draft.spec
    params = {
        "convert": "1",
        "amount": _decimal_text(spec.source_amount),
        "source_currency": spec.source_currency.code,
        "destination_currency": spec.destination_currency.code,
    }
    if spec.destination_country is not None:
        params["destination_country"] = spec.destination_country.iso2
    if spec.destination_city is not None:
        params["destination_city_slug"] = spec.destination_city.slug
    return f"{reverse('converter')}?{urlencode(params)}"


def _shopping_reopen_url(draft: ScenarioDraft) -> str:
    spec = draft.spec
    shopping = spec.shopping_assumptions
    if shopping is None:
        raise RuntimeError("Shopping browser draft has no Shopping assumptions.")
    params = {
        "purchase_country": spec.source_country.iso2 if spec.source_country is not None else "",
        "purchase_currency": spec.source_currency.code,
        "home_currency": spec.destination_currency.code,
        "item_price": _decimal_text(shopping.item_price),
        "shipping": _decimal_text(shopping.shipping),
        "known_fees": _decimal_text(shopping.known_fees),
        "fx_markup_percent": _decimal_text(shopping.fx_markup_percent),
    }
    return f"{reverse('shopping_calculation')}?{urlencode(params)}"


def _issued_payload(draft: ScenarioDraft) -> JsonResponse:
    issue = build_browser_scenario_token(
        spec=draft.spec,
        conversion=draft.conversion,
    )
    spec = draft.spec
    response = JsonResponse(
        {
            "scenario": {
                "id": str(issue.snapshot.origin_key),
                "token": issue.token,
                "kind": str(spec.kind),
                "title": spec.title,
                "scope": draft.display_scope,
                "sourceCurrency": spec.source_currency.code,
                "destinationCurrency": spec.destination_currency.code,
                "sourceAmount": _decimal_text(spec.source_amount),
                "savedAt": timezone.now().isoformat(),
                "reopenUrl": (
                    _shopping_reopen_url(draft)
                    if spec.kind == SavedScenarioKind.SHOPPING
                    else _budget_reopen_url(draft)
                ),
            }
        }
    )
    response["Cache-Control"] = "private, no-store"
    return response


@require_POST
def issue_browser_budget_scenario(request: HttpRequest) -> JsonResponse:
    try:
        draft = build_budget_scenario_draft(request.POST)
        return _issued_payload(draft)
    except ScenarioDraftError as exc:
        return _json_error(exc.code, exc.user_message, status=422)
    except BrowserScenarioTokenError:
        return _json_error(
            "browser_snapshot_invalid",
            "This budget could not be prepared for browser-only saving.",
            status=422,
        )
    except DatabaseError:
        return _json_error(
            "reference_data_unavailable",
            "Browser-only saving is temporarily unavailable. Your budget result is unchanged.",
            status=503,
        )


@require_POST
def issue_browser_shopping_scenario(request: HttpRequest) -> JsonResponse:
    try:
        draft = build_shopping_scenario_draft(request.POST)
        return _issued_payload(draft)
    except ScenarioDraftError as exc:
        return _json_error(exc.code, exc.user_message, status=422)
    except BrowserScenarioTokenError:
        return _json_error(
            "browser_snapshot_invalid",
            "This Shopping estimate could not be prepared for browser-only saving.",
            status=422,
        )
    except DatabaseError:
        return _json_error(
            "reference_data_unavailable",
            "Browser-only saving is temporarily unavailable. Your Shopping result is unchanged.",
            status=503,
        )


@login_required
@require_POST
def import_browser_scenarios_view(request: HttpRequest) -> JsonResponse:
    if request.content_type != "application/json":
        return _json_error(
            "unsupported_media_type",
            "Content-Type must be application/json.",
            status=415,
        )

    raw_length = request.META.get("CONTENT_LENGTH")
    if raw_length:
        try:
            if int(raw_length) > _MAX_IMPORT_BODY_BYTES:
                return _json_error("payload_too_large", "Import payload is too large.", status=413)
        except ValueError:
            return _json_error("invalid_content_length", "Invalid Content-Length.", status=400)

    body = request.body
    if len(body) > _MAX_IMPORT_BODY_BYTES:
        return _json_error("payload_too_large", "Import payload is too large.", status=413)

    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _json_error("invalid_json", "Request body must contain valid JSON.", status=400)

    if not isinstance(payload, dict) or set(payload) != {"scenarios"}:
        return _json_error(
            "invalid_request",
            "Request must contain only a scenarios list.",
            status=400,
        )

    try:
        result = import_browser_scenarios(request.user, payload["scenarios"])
    except BrowserScenarioTokenError as exc:
        return _json_error("invalid_scenarios", str(exc), status=400)
    except DatabaseError:
        return _json_error(
            "persistence_unavailable",
            "Browser scenarios could not be imported right now. Local copies are unchanged.",
            status=503,
        )

    response = JsonResponse(
        {
            "importedOriginKeys": list(result.imported_origin_keys),
            "createdCount": result.created_count,
            "savedCount": len(result.scenario_ids),
        }
    )
    response["Cache-Control"] = "private, no-store"
    return response
