from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from django.core import signing
from django.utils import timezone

from apps.exchange.domain import FxDomainError, normalize_currency_code, normalize_provider_keys
from apps.travel.models import SavedScenario, SavedScenarioKind, SavedScenarioObservation

_TOKEN_SALT = "travel.share-scenario:v1"
_MAX_TOKEN_LENGTH = 8192
_ALLOWED_KINDS = frozenset(SavedScenarioKind.values)


class ScenarioShareTokenError(ValueError):
    """Raised when a public saved-scenario snapshot cannot be trusted."""


@dataclass(frozen=True, slots=True)
class ScenarioShareSnapshot:
    kind: str
    scope_label: str
    input_amount: Decimal
    output_amount: Decimal
    base_currency: str
    quote_currency: str
    rate: Decimal
    effective_date: date
    fetched_at: datetime
    provider_keys: tuple[str, ...]
    stale: bool

    @property
    def exact(self) -> bool:
        return self.base_currency == self.quote_currency


def _share_scope_label(scenario: SavedScenario) -> str:
    if scenario.kind == SavedScenarioKind.SHOPPING:
        if scenario.source_country_id:
            return f"{scenario.source_country.name} purchase"
        return f"{scenario.source_currency.code} purchase"
    if scenario.destination_city_id:
        return f"{scenario.destination_city.name}, {scenario.destination_country.name}"
    if scenario.destination_country_id:
        return scenario.destination_country.name
    return "Saved travel-money plan"


def build_scenario_share_token(
    scenario: SavedScenario,
    observation: SavedScenarioObservation,
) -> str:
    """Sign a privacy-minimized immutable snapshot from already-stored scenario evidence."""

    if observation.scenario_id != scenario.pk:
        raise ScenarioShareTokenError("Scenario share observation does not belong to the scenario.")
    if observation.input_amount != scenario.source_amount:
        raise ScenarioShareTokenError("Scenario share observation does not match the saved amount.")

    payload = {
        "v": 1,
        "kind": scenario.kind,
        "scope_label": _share_scope_label(scenario),
        "input_amount": format(observation.input_amount, "f"),
        "output_amount": format(observation.output_amount, "f"),
        "base_currency": scenario.source_currency.code,
        "quote_currency": scenario.destination_currency.code,
        "rate": format(observation.rate, "f"),
        "effective_date": observation.effective_date.isoformat(),
        "fetched_at": observation.fetched_at.isoformat(),
        "provider_keys": list(observation.provider_keys),
        "stale": observation.stale,
    }
    return signing.dumps(payload, salt=_TOKEN_SALT, compress=True)


def load_scenario_share_token(token: str) -> ScenarioShareSnapshot:
    if not isinstance(token, str) or not token or len(token) > _MAX_TOKEN_LENGTH:
        raise ScenarioShareTokenError("Scenario share token is missing or invalid.")

    try:
        payload = signing.loads(token, salt=_TOKEN_SALT)
    except signing.BadSignature as exc:
        raise ScenarioShareTokenError("Scenario share token is invalid.") from exc

    expected_fields = {
        "v",
        "kind",
        "scope_label",
        "input_amount",
        "output_amount",
        "base_currency",
        "quote_currency",
        "rate",
        "effective_date",
        "fetched_at",
        "provider_keys",
        "stale",
    }
    if not isinstance(payload, dict) or payload.get("v") != 1 or set(payload) != expected_fields:
        raise ScenarioShareTokenError("Scenario share token fields are invalid.")

    kind = payload["kind"]
    scope_label = payload["scope_label"]
    stale = payload["stale"]
    raw_provider_keys = payload["provider_keys"]
    if kind not in _ALLOWED_KINDS:
        raise ScenarioShareTokenError("Scenario share kind is invalid.")
    if not isinstance(scope_label, str) or not 1 <= len(scope_label.strip()) <= 160:
        raise ScenarioShareTokenError("Scenario share scope is invalid.")
    if not isinstance(stale, bool):
        raise ScenarioShareTokenError("Scenario share stale state is invalid.")
    if not isinstance(raw_provider_keys, list):
        raise ScenarioShareTokenError("Scenario share provider attribution is invalid.")

    try:
        input_amount = _finite_decimal(payload["input_amount"], minimum=Decimal("0"))
        output_amount = _finite_decimal(payload["output_amount"], minimum=Decimal("0"))
        rate = _finite_decimal(payload["rate"], minimum=Decimal("0"), strict_positive=True)
        base_currency = normalize_currency_code(payload["base_currency"])
        quote_currency = normalize_currency_code(payload["quote_currency"])
        effective_date = date.fromisoformat(payload["effective_date"])
        fetched_at = datetime.fromisoformat(payload["fetched_at"])
        provider_keys = normalize_provider_keys(raw_provider_keys)
    except (FxDomainError, TypeError, ValueError) as exc:
        raise ScenarioShareTokenError("Scenario share token payload is invalid.") from exc

    if not timezone.is_aware(fetched_at):
        raise ScenarioShareTokenError("Scenario share fetch time is invalid.")

    exact = base_currency == quote_currency
    if exact and rate != Decimal("1"):
        raise ScenarioShareTokenError("Exact scenario share snapshot must use a 1:1 rate.")
    if exact and provider_keys:
        raise ScenarioShareTokenError(
            "Exact scenario share snapshot must not claim an external provider."
        )
    if not exact and not provider_keys:
        raise ScenarioShareTokenError("Scenario share snapshot must retain provider attribution.")

    return ScenarioShareSnapshot(
        kind=kind,
        scope_label=scope_label.strip(),
        input_amount=input_amount,
        output_amount=output_amount,
        base_currency=base_currency,
        quote_currency=quote_currency,
        rate=rate,
        effective_date=effective_date,
        fetched_at=fetched_at,
        provider_keys=provider_keys,
        stale=stale,
    )


def _finite_decimal(
    value: Any,
    *,
    minimum: Decimal,
    strict_positive: bool = False,
) -> Decimal:
    if not isinstance(value, str) or len(value) > 80:
        raise ScenarioShareTokenError("Scenario share numeric value is invalid.")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ScenarioShareTokenError("Scenario share numeric value is invalid.") from exc
    if not parsed.is_finite():
        raise ScenarioShareTokenError("Scenario share numeric value is invalid.")
    if strict_positive and parsed <= minimum:
        raise ScenarioShareTokenError("Scenario share numeric value must be positive.")
    if not strict_positive and parsed < minimum:
        raise ScenarioShareTokenError("Scenario share numeric value is out of range.")
    return parsed
