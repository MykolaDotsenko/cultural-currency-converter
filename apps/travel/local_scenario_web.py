from __future__ import annotations

import json
import logging
from decimal import Decimal
from urllib.parse import urlencode

from django.db import DatabaseError, transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils.formats import date_format
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from apps.travel.local_scenario_snapshot import (
    LocalScenarioTokenError,
    build_local_scenario_token,
    load_local_scenario_token,
    local_scenario_public_summary,
    materialize_local_scenario,
)
from apps.travel.models import SavedScenario, SavedScenarioKind
from apps.travel.scenario_drafts import (
    ScenarioDraftError,
    build_budget_scenario_draft,
    build_shopping_scenario_draft,
)
from apps.travel.scenarios import SavedScenarioError, create_saved_scenario

logger = logging.getLogger("cultural_currency.travel")

_MAX_IMPORT_ITEMS = 10
_MAX_IMPORT_BODY_BYTES = 256 * 1024


def _json_response(payload: dict[str, object], *, status: int = 200) -> JsonResponse:
    response = JsonResponse(payload, status=status)
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


def _json_error(code: str, message: str, *, status: int) -> JsonResponse:
    return _json_response({"error": {"code": code, "message": message}}, status=status)


def _local_token_response(draft) -> JsonResponse:
    try:
        token = build_local_scenario_token(spec=draft.spec, conversion=draft.conversion)
        snapshot = load_local_scenario_token(token)
    except (LocalScenarioTokenError, SavedScenarioError) as exc:
        logger.warning(
            "local_scenario_token_build_rejected",
            extra={"error_code": exc.__class__.__name__},
        )
        return _json_error(
            "local_scenario_unavailable",
            "This scenario could not be saved safely in the browser.",
            status=422,
        )

    summary = local_scenario_public_summary(snapshot)
    detail_url = f"{reverse('local_scenario_detail')}?{urlencode({'snapshot': token})}"
    return _json_response(
        {
            "token": token,
            "scenario": summary,
            "detailUrl": detail_url,
        }
    )


@require_POST
def create_local_budget_scenario(request: HttpRequest) -> JsonResponse:
    try:
        draft = build_budget_scenario_draft(request.POST)
    except ScenarioDraftError as exc:
        return _json_error(exc.code, exc.user_message, status=422)
    except DatabaseError:
        logger.exception("local_budget_scenario_draft_database_unavailable")
        return _json_error(
            "scenario_metadata_unavailable",
            "Scenario reference metadata is temporarily unavailable.",
            status=503,
        )
    return _local_token_response(draft)


@require_POST
def create_local_shopping_scenario(request: HttpRequest) -> JsonResponse:
    try:
        draft = build_shopping_scenario_draft(request.POST)
    except ScenarioDraftError as exc:
        return _json_error(exc.code, exc.user_message, status=422)
    except DatabaseError:
        logger.exception("local_shopping_scenario_draft_database_unavailable")
        return _json_error(
            "scenario_metadata_unavailable",
            "Scenario reference metadata is temporarily unavailable.",
            status=503,
        )
    return _local_token_response(draft)


def _money_text(value: Decimal) -> str:
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _local_reopen_url(snapshot) -> str:
    if snapshot.kind == SavedScenarioKind.SHOPPING and snapshot.shopping_assumptions is not None:
        params = {
            "purchase_country": snapshot.source_country_code,
            "purchase_currency": snapshot.source_currency_code,
            "home_currency": snapshot.destination_currency_code,
            "item_price": _money_text(snapshot.shopping_assumptions.item_price),
            "shipping": _money_text(snapshot.shopping_assumptions.shipping),
            "known_fees": _money_text(snapshot.shopping_assumptions.known_fees),
            "fx_markup_percent": _money_text(snapshot.shopping_assumptions.fx_markup_percent),
        }
        return f"{reverse('shopping_calculation')}?{urlencode(params)}"

    params = {
        "convert": "1",
        "amount": _money_text(snapshot.source_amount),
        "source_currency": snapshot.source_currency_code,
        "destination_currency": snapshot.destination_currency_code,
    }
    if snapshot.source_country_code:
        params["source_country"] = snapshot.source_country_code
    if snapshot.destination_country_code:
        params["destination_country"] = snapshot.destination_country_code
    if snapshot.destination_city_slug:
        params["destination_city_slug"] = snapshot.destination_city_slug
    return f"{reverse('converter')}?{urlencode(params)}"


@never_cache
@require_GET
def local_scenario_detail(request: HttpRequest) -> HttpResponse:
    token = str(request.GET.get("snapshot") or "")
    try:
        snapshot = load_local_scenario_token(token)
    except LocalScenarioTokenError:
        return render(
            request,
            "travel/local_scenario_invalid.html",
            status=404,
        )

    response = render(
        request,
        "travel/local_scenario_detail.html",
        {
            "snapshot": snapshot,
            "source_amount_text": _money_text(snapshot.source_amount),
            "output_amount_text": _money_text(snapshot.conversion.output_amount),
            "rate_text": _money_text(snapshot.conversion.quote.rate),
            "effective_date_label": date_format(
                snapshot.conversion.quote.effective_date,
                "j M Y",
            ),
            "fetched_at_label": snapshot.conversion.quote.fetched_at.strftime(
                "%d %b %Y · %H:%M %Z"
            ),
            "provider_label": (
                ", ".join(key.upper() for key in snapshot.conversion.quote.provider_keys)
                or "No external rate source"
            ),
            "reopen_url": _local_reopen_url(snapshot),
        },
    )
    response["Cache-Control"] = "private, no-store"
    response["Pragma"] = "no-cache"
    response["X-Robots-Tag"] = "noindex, nofollow"
    response["Referrer-Policy"] = "no-referrer"
    return response


def _import_tokens(request: HttpRequest) -> list[str] | JsonResponse:
    if not request.user.is_authenticated:
        return _json_error(
            "authentication_required",
            "Sign in before importing browser-saved scenarios.",
            status=401,
        )
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
            return _json_error("invalid_request", "Content-Length is invalid.", status=400)
    body = request.body
    if len(body) > _MAX_IMPORT_BODY_BYTES:
        return _json_error("payload_too_large", "Import payload is too large.", status=413)
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _json_error("invalid_json", "Request body must contain valid JSON.", status=400)
    if not isinstance(payload, dict) or set(payload) != {"tokens"}:
        return _json_error(
            "invalid_request",
            "Request must contain only a tokens list.",
            status=400,
        )
    values = payload["tokens"]
    if not isinstance(values, list) or not 1 <= len(values) <= _MAX_IMPORT_ITEMS:
        return _json_error(
            "invalid_request",
            f"Import between 1 and {_MAX_IMPORT_ITEMS} browser scenarios at a time.",
            status=400,
        )
    tokens: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value:
            return _json_error(
                "invalid_request",
                "Every imported scenario token must be text.",
                status=400,
            )
        tokens.append(value)
    return tokens


@require_POST
def import_local_scenarios(request: HttpRequest) -> JsonResponse:
    tokens = _import_tokens(request)
    if isinstance(tokens, JsonResponse):
        return tokens

    try:
        snapshots = [load_local_scenario_token(token) for token in tokens]
        if len({item.import_key for item in snapshots}) != len(snapshots):
            return _json_error(
                "duplicate_import",
                "The import request contains the same browser scenario more than once.",
                status=400,
            )
        materialized = [materialize_local_scenario(item) for item in snapshots]
    except LocalScenarioTokenError as exc:
        logger.warning(
            "local_scenario_import_rejected",
            extra={"error_code": exc.__class__.__name__},
        )
        return _json_error(
            "invalid_local_scenario",
            "One browser-saved scenario is invalid or no longer compatible.",
            status=400,
        )
    except DatabaseError:
        logger.exception("local_scenario_import_metadata_database_unavailable")
        return _json_error(
            "scenario_metadata_unavailable",
            "Scenario reference metadata is temporarily unavailable.",
            status=503,
        )

    keys = [item.import_key for item in materialized]
    try:
        with transaction.atomic():
            existing_keys = set(
                SavedScenario.objects.filter(
                    user=request.user,
                    import_key__in=keys,
                ).values_list("import_key", flat=True)
            )
            rows = [
                create_saved_scenario(
                    request.user,
                    spec=item.spec,
                    conversion=item.conversion,
                    import_key=item.import_key,
                )
                for item in materialized
            ]
    except SavedScenarioError as exc:
        logger.warning(
            "local_scenario_import_domain_rejected",
            extra={"error_code": str(exc)},
        )
        return _json_error("scenario_import_rejected", str(exc), status=409)
    except DatabaseError:
        logger.exception("local_scenario_import_database_unavailable")
        return _json_error(
            "scenario_import_unavailable",
            "Browser scenarios could not be imported right now.",
            status=503,
        )

    return _json_response(
        {
            "importedCount": len(rows),
            "createdCount": sum(item.import_key not in existing_keys for item in materialized),
            "items": [
                {
                    "localId": str(item.import_key),
                    "scenarioId": row.pk,
                    "detailUrl": reverse("saved_scenario_detail", args=(row.pk,)),
                    "created": item.import_key not in existing_keys,
                }
                for item, row in zip(materialized, rows, strict=True)
            ],
        }
    )
