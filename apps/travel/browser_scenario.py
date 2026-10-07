from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID, uuid4

from django.core import signing
from django.contrib.auth import get_user_model
from django.db import transaction

from apps.countries.models import City, Country, Currency
from apps.exchange.budget import BudgetCategoryAssumption
from apps.exchange.domain import (
    ConversionResult,
    FxSourcePolicy,
    ObservationGranularity,
    ProviderPolicyMode,
    RateQuote,
    normalize_currency_code,
)
from apps.exchange.shopping import ShoppingAssumptions
from apps.travel.models import SavedScenario, SavedScenarioBudgetBasis, SavedScenarioKind
from apps.travel.scenarios import (
    MAX_ACCOUNT_SCENARIOS,
    SavedScenarioError,
    SavedScenarioSpec,
    create_saved_scenario,
)

_TOKEN_SALT = "travel.browser-scenario:v1"
_MAX_TOKEN_LENGTH = 24_576
_MAX_IMPORT_BATCH = 12
_ALLOWED_KINDS = frozenset({SavedScenarioKind.BUDGET, SavedScenarioKind.SHOPPING})


class BrowserScenarioTokenError(ValueError):
    """Raised when a browser-owned scenario snapshot cannot be trusted."""


@dataclass(frozen=True, slots=True)
class BrowserScenarioSnapshot:
    origin_key: UUID
    kind: str
    title: str
    source_currency_code: str
    destination_currency_code: str
    source_country_code: str
    destination_country_code: str
    destination_city_slug: str
    source_amount: Decimal
    budget_basis: str
    planning_destination_amount: Decimal | None
    fx_markup_percent: Decimal | None
    source_fixed_fee: Decimal | None
    destination_fixed_fee: Decimal | None
    duration_days: int | None
    travelers: int
    travel_start_date: date | None
    travel_end_date: date | None
    budget_categories: tuple[BudgetCategoryAssumption, ...]
    shopping_assumptions: ShoppingAssumptions | None
    conversion: ConversionResult


@dataclass(frozen=True, slots=True)
class BrowserScenarioIssue:
    token: str
    snapshot: BrowserScenarioSnapshot


@dataclass(frozen=True, slots=True)
class BrowserScenarioImportResult:
    imported_origin_keys: tuple[str, ...]
    created_count: int
    scenario_ids: tuple[int, ...]


def build_browser_scenario_token(
    *,
    spec: SavedScenarioSpec,
    conversion: ConversionResult,
    origin_key: UUID | None = None,
) -> BrowserScenarioIssue:
    """Create a durable signed browser-owned scenario snapshot.

    The token is intentionally not time-limited. It is immutable, remains
    private to whoever holds it and is invalidated naturally by signing-key
    rotation. Import never trusts browser-authored financial fields.
    """

    key = origin_key or spec.browser_import_key or uuid4()
    if spec.kind not in _ALLOWED_KINDS:
        raise BrowserScenarioTokenError("Browser scenarios currently support Budget and Shopping.")
    if conversion.quote.historical:
        raise BrowserScenarioTokenError("Browser scenarios require a current conversion.")
    if conversion.quote.base_currency != spec.source_currency.code:
        raise BrowserScenarioTokenError("Scenario source currency does not match the conversion.")
    if conversion.quote.quote_currency != spec.destination_currency.code:
        raise BrowserScenarioTokenError(
            "Scenario destination currency does not match the conversion."
        )
    if conversion.input_amount != spec.source_amount:
        raise BrowserScenarioTokenError("Scenario amount does not match the conversion input.")

    quote = conversion.quote
    payload = {
        "v": 1,
        "origin_key": str(key),
        "kind": str(spec.kind),
        "title": spec.title.strip(),
        "source_currency": spec.source_currency.code,
        "destination_currency": spec.destination_currency.code,
        "source_country": spec.source_country.iso2 if spec.source_country is not None else "",
        "destination_country": (
            spec.destination_country.iso2 if spec.destination_country is not None else ""
        ),
        "destination_city": (
            spec.destination_city.slug if spec.destination_city is not None else ""
        ),
        "source_amount": format(spec.source_amount, "f"),
        "budget_basis": str(spec.budget_basis),
        "planning_destination_amount": _optional_decimal_text(spec.planning_destination_amount),
        "fx_markup_percent": _optional_decimal_text(spec.fx_markup_percent),
        "source_fixed_fee": _optional_decimal_text(spec.source_fixed_fee),
        "destination_fixed_fee": _optional_decimal_text(spec.destination_fixed_fee),
        "duration_days": spec.duration_days,
        "travelers": spec.travelers,
        "travel_start_date": _optional_date_text(spec.travel_start_date),
        "travel_end_date": _optional_date_text(spec.travel_end_date),
        "budget_categories": [
            {
                "category": item.category,
                "units_per_person_per_day": format(item.units_per_person_per_day, "f"),
            }
            for item in spec.budget_categories
        ],
        "shopping": (
            {
                "item_price": format(spec.shopping_assumptions.item_price, "f"),
                "shipping": format(spec.shopping_assumptions.shipping, "f"),
                "known_fees": format(spec.shopping_assumptions.known_fees, "f"),
                "fx_markup_percent": format(spec.shopping_assumptions.fx_markup_percent, "f"),
            }
            if spec.shopping_assumptions is not None
            else None
        ),
        "conversion": {
            "input_amount": format(conversion.input_amount, "f"),
            "output_amount": format(conversion.output_amount, "f"),
            "base_currency": quote.base_currency,
            "quote_currency": quote.quote_currency,
            "rate": format(quote.rate, "f"),
            "effective_date": quote.effective_date.isoformat(),
            "fetched_at": quote.fetched_at.isoformat(),
            "provider_policy_mode": quote.provider_policy.mode.value,
            "provider_policy_key": quote.provider_policy.provider_key,
            "provider_policy_include_attribution": quote.provider_policy.include_attribution,
            "provider_keys": list(quote.provider_keys),
            "observation_granularity": quote.observation_granularity.value,
            "stale": conversion.stale,
        },
    }
    token = signing.dumps(payload, salt=_TOKEN_SALT, compress=True)
    snapshot = load_browser_scenario_token(token)
    return BrowserScenarioIssue(token=token, snapshot=snapshot)


def load_browser_scenario_token(token: str) -> BrowserScenarioSnapshot:
    if not isinstance(token, str) or not token or len(token) > _MAX_TOKEN_LENGTH:
        raise BrowserScenarioTokenError("Browser scenario token is missing or invalid.")

    try:
        payload = signing.loads(token, salt=_TOKEN_SALT)
    except signing.BadSignature as exc:
        raise BrowserScenarioTokenError("Browser scenario token is invalid.") from exc

    if not isinstance(payload, dict) or payload.get("v") != 1:
        raise BrowserScenarioTokenError("Browser scenario token version is unsupported.")

    expected = {
        "v",
        "origin_key",
        "kind",
        "title",
        "source_currency",
        "destination_currency",
        "source_country",
        "destination_country",
        "destination_city",
        "source_amount",
        "budget_basis",
        "planning_destination_amount",
        "fx_markup_percent",
        "source_fixed_fee",
        "destination_fixed_fee",
        "duration_days",
        "travelers",
        "travel_start_date",
        "travel_end_date",
        "budget_categories",
        "shopping",
        "conversion",
    }
    if set(payload) != expected:
        raise BrowserScenarioTokenError("Browser scenario token fields are invalid.")

    try:
        origin_key = UUID(str(payload["origin_key"]))
        kind = str(payload["kind"])
        title = _title(payload["title"])
        source_currency_code = normalize_currency_code(payload["source_currency"])
        destination_currency_code = normalize_currency_code(payload["destination_currency"])
        source_country_code = _country_code(payload["source_country"], allow_empty=True)
        destination_country_code = _country_code(
            payload["destination_country"],
            allow_empty=True,
        )
        destination_city_slug = _city_slug(payload["destination_city"])
        source_amount = _finite_decimal(payload["source_amount"], minimum=Decimal("0"))
        budget_basis = str(payload["budget_basis"])
        planning_destination_amount = _optional_decimal(
            payload["planning_destination_amount"],
            minimum=Decimal("0"),
        )
        fx_markup_percent = _optional_decimal(
            payload["fx_markup_percent"],
            minimum=Decimal("0"),
            maximum=Decimal("25"),
        )
        source_fixed_fee = _optional_decimal(payload["source_fixed_fee"], minimum=Decimal("0"))
        destination_fixed_fee = _optional_decimal(
            payload["destination_fixed_fee"],
            minimum=Decimal("0"),
        )
        duration_days = _optional_int(payload["duration_days"], minimum=1, maximum=365)
        travelers = _required_int(payload["travelers"], minimum=1, maximum=20)
        travel_start_date = _optional_date(payload["travel_start_date"])
        travel_end_date = _optional_date(payload["travel_end_date"])
        categories = _budget_categories(payload["budget_categories"])
        shopping = _shopping_assumptions(payload["shopping"])
        conversion = _conversion(payload["conversion"])
    except (KeyError, TypeError, ValueError) as exc:
        raise BrowserScenarioTokenError("Browser scenario token payload is invalid.") from exc

    if kind not in _ALLOWED_KINDS:
        raise BrowserScenarioTokenError("Browser scenario kind is invalid.")
    if budget_basis not in SavedScenarioBudgetBasis.values:
        raise BrowserScenarioTokenError("Browser scenario budget basis is invalid.")
    if destination_city_slug and not destination_country_code:
        raise BrowserScenarioTokenError("Browser scenario city requires a country.")
    if travel_end_date is not None and travel_start_date is None:
        raise BrowserScenarioTokenError("Browser scenario end date requires a start date.")
    if (
        travel_start_date is not None
        and travel_end_date is not None
        and travel_end_date < travel_start_date
    ):
        raise BrowserScenarioTokenError("Browser scenario travel dates are invalid.")
    if conversion.quote.historical:
        raise BrowserScenarioTokenError("Browser scenario conversion must be current.")
    if conversion.quote.base_currency != source_currency_code:
        raise BrowserScenarioTokenError("Browser scenario source currency is inconsistent.")
    if conversion.quote.quote_currency != destination_currency_code:
        raise BrowserScenarioTokenError("Browser scenario destination currency is inconsistent.")
    if conversion.input_amount != source_amount:
        raise BrowserScenarioTokenError("Browser scenario source amount is inconsistent.")

    if kind == SavedScenarioKind.BUDGET:
        if not destination_country_code:
            raise BrowserScenarioTokenError("Budget browser scenario requires a destination.")
        if duration_days is None or not categories:
            raise BrowserScenarioTokenError("Budget browser scenario assumptions are incomplete.")
        if shopping is not None:
            raise BrowserScenarioTokenError("Budget browser scenario cannot contain Shopping data.")
    elif kind == SavedScenarioKind.SHOPPING:
        if shopping is None:
            raise BrowserScenarioTokenError("Shopping browser scenario assumptions are missing.")
        if categories or duration_days is not None:
            raise BrowserScenarioTokenError(
                "Shopping browser scenario cannot contain budget assumptions."
            )
        if shopping.purchase_total != source_amount:
            raise BrowserScenarioTokenError("Shopping browser scenario amount is inconsistent.")

    _validate_budget_basis_payload(
        kind=kind,
        budget_basis=budget_basis,
        planning_destination_amount=planning_destination_amount,
        fx_markup_percent=fx_markup_percent,
        source_fixed_fee=source_fixed_fee,
        destination_fixed_fee=destination_fixed_fee,
    )

    return BrowserScenarioSnapshot(
        origin_key=origin_key,
        kind=kind,
        title=title,
        source_currency_code=source_currency_code,
        destination_currency_code=destination_currency_code,
        source_country_code=source_country_code,
        destination_country_code=destination_country_code,
        destination_city_slug=destination_city_slug,
        source_amount=source_amount,
        budget_basis=budget_basis,
        planning_destination_amount=planning_destination_amount,
        fx_markup_percent=fx_markup_percent,
        source_fixed_fee=source_fixed_fee,
        destination_fixed_fee=destination_fixed_fee,
        duration_days=duration_days,
        travelers=travelers,
        travel_start_date=travel_start_date,
        travel_end_date=travel_end_date,
        budget_categories=categories,
        shopping_assumptions=shopping,
        conversion=conversion,
    )


def import_browser_scenarios(user, raw_tokens: Any) -> BrowserScenarioImportResult:
    if not user.is_authenticated or user.pk is None:
        raise BrowserScenarioTokenError("Authentication is required.")
    if not isinstance(raw_tokens, list):
        raise BrowserScenarioTokenError("scenarios must be a list.")
    if len(raw_tokens) > _MAX_IMPORT_BATCH:
        raise BrowserScenarioTokenError(
            f"At most {_MAX_IMPORT_BATCH} browser scenarios may be imported at once."
        )

    snapshots: list[BrowserScenarioSnapshot] = []
    seen: set[UUID] = set()
    for raw in raw_tokens:
        if not isinstance(raw, str):
            raise BrowserScenarioTokenError("Every browser scenario must be a signed token.")
        snapshot = load_browser_scenario_token(raw)
        if snapshot.origin_key in seen:
            continue
        seen.add(snapshot.origin_key)
        snapshots.append(snapshot)

    drafts = [_resolve_snapshot(snapshot) for snapshot in snapshots]

    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=user.pk)
        existing_keys = set(
            SavedScenario.objects.filter(
                user=user,
                browser_import_key__in=[snapshot.origin_key for snapshot in snapshots],
            ).values_list("browser_import_key", flat=True)
        )
        missing_count = sum(
            snapshot.origin_key not in existing_keys for snapshot in snapshots
        )
        current_count = SavedScenario.objects.filter(user=user).count()
        if current_count + missing_count > MAX_ACCOUNT_SCENARIOS:
            raise BrowserScenarioTokenError(
                f"An account may store at most {MAX_ACCOUNT_SCENARIOS} saved scenarios."
            )

        scenario_ids: list[int] = []
        created_count = 0
        for snapshot, (spec, conversion) in zip(snapshots, drafts, strict=True):
            existed = snapshot.origin_key in existing_keys
            try:
                scenario = create_saved_scenario(
                    user,
                    spec=spec,
                    conversion=conversion,
                )
            except SavedScenarioError as exc:
                raise BrowserScenarioTokenError(str(exc)) from exc
            if scenario.pk is None:
                raise RuntimeError("Imported browser scenario was not persisted.")
            scenario_ids.append(scenario.pk)
            if not existed:
                created_count += 1

    return BrowserScenarioImportResult(
        imported_origin_keys=tuple(str(snapshot.origin_key) for snapshot in snapshots),
        created_count=created_count,
        scenario_ids=tuple(scenario_ids),
    )


def _resolve_snapshot(
    snapshot: BrowserScenarioSnapshot,
) -> tuple[SavedScenarioSpec, ConversionResult]:
    currencies = Currency.objects.in_bulk(
        [snapshot.source_currency_code, snapshot.destination_currency_code],
        field_name="code",
    )
    try:
        source_currency = currencies[snapshot.source_currency_code]
        destination_currency = currencies[snapshot.destination_currency_code]
    except KeyError as exc:
        raise BrowserScenarioTokenError(
            "Browser scenario currency metadata is no longer available."
        ) from exc

    source_country = None
    if snapshot.source_country_code:
        try:
            source_country = Country.objects.get(
                iso2=snapshot.source_country_code,
                is_active=True,
            )
        except Country.DoesNotExist as exc:
            raise BrowserScenarioTokenError(
                "Browser scenario source country is no longer available."
            ) from exc

    destination_country = None
    if snapshot.destination_country_code:
        try:
            destination_country = Country.objects.get(
                iso2=snapshot.destination_country_code,
                is_active=True,
            )
        except Country.DoesNotExist as exc:
            raise BrowserScenarioTokenError(
                "Browser scenario destination is no longer available."
            ) from exc

    destination_city = None
    if snapshot.destination_city_slug:
        if destination_country is None:
            raise BrowserScenarioTokenError("Browser scenario city has no destination country.")
        try:
            destination_city = City.objects.get(
                country=destination_country,
                slug=snapshot.destination_city_slug,
                is_active=True,
            )
        except City.DoesNotExist as exc:
            raise BrowserScenarioTokenError(
                "Browser scenario destination city is no longer available."
            ) from exc

    spec = SavedScenarioSpec(
        kind=SavedScenarioKind(snapshot.kind),
        title=snapshot.title,
        source_currency=source_currency,
        destination_currency=destination_currency,
        source_country=source_country,
        destination_country=destination_country,
        destination_city=destination_city,
        source_amount=snapshot.source_amount,
        budget_basis=snapshot.budget_basis,
        planning_destination_amount=snapshot.planning_destination_amount,
        fx_markup_percent=snapshot.fx_markup_percent,
        source_fixed_fee=snapshot.source_fixed_fee,
        destination_fixed_fee=snapshot.destination_fixed_fee,
        duration_days=snapshot.duration_days,
        travelers=snapshot.travelers,
        travel_start_date=snapshot.travel_start_date,
        travel_end_date=snapshot.travel_end_date,
        budget_categories=snapshot.budget_categories,
        shopping_assumptions=snapshot.shopping_assumptions,
        browser_import_key=snapshot.origin_key,
    )
    return spec, snapshot.conversion


def _conversion(value: Any) -> ConversionResult:
    if not isinstance(value, dict):
        raise BrowserScenarioTokenError("Browser scenario conversion is invalid.")
    expected = {
        "input_amount",
        "output_amount",
        "base_currency",
        "quote_currency",
        "rate",
        "effective_date",
        "fetched_at",
        "provider_policy_mode",
        "provider_policy_key",
        "provider_policy_include_attribution",
        "provider_keys",
        "observation_granularity",
        "stale",
    }
    if set(value) != expected:
        raise BrowserScenarioTokenError("Browser scenario conversion fields are invalid.")

    input_amount = _finite_decimal(value["input_amount"], minimum=Decimal("0"))
    output_amount = _finite_decimal(value["output_amount"], minimum=Decimal("0"))
    rate = _finite_decimal(value["rate"], minimum=Decimal("0"), strict_positive=True)
    base_currency = normalize_currency_code(value["base_currency"])
    quote_currency = normalize_currency_code(value["quote_currency"])
    effective_date = date.fromisoformat(str(value["effective_date"]))
    fetched_at = datetime.fromisoformat(str(value["fetched_at"]))
    if fetched_at.tzinfo is None:
        raise BrowserScenarioTokenError("Browser scenario fetched-at must be timezone-aware.")
    include_attribution = value["provider_policy_include_attribution"]
    if not isinstance(include_attribution, bool):
        raise BrowserScenarioTokenError("Browser scenario provider policy is invalid.")
    policy_key = value["provider_policy_key"]
    if policy_key is not None and not isinstance(policy_key, str):
        raise BrowserScenarioTokenError("Browser scenario provider policy is invalid.")
    policy = FxSourcePolicy(
        mode=ProviderPolicyMode(str(value["provider_policy_mode"])),
        provider_key=policy_key,
        include_attribution=include_attribution,
    )
    raw_provider_keys = value["provider_keys"]
    if not isinstance(raw_provider_keys, list):
        raise BrowserScenarioTokenError("Browser scenario provider attribution is invalid.")
    granularity = ObservationGranularity(str(value["observation_granularity"]))
    stale = value["stale"]
    if not isinstance(stale, bool):
        raise BrowserScenarioTokenError("Browser scenario stale state is invalid.")

    quote = RateQuote(
        base_currency=base_currency,
        quote_currency=quote_currency,
        rate=rate,
        requested_date=None,
        effective_date=effective_date,
        fetched_at=fetched_at,
        provider_policy=policy,
        provider_keys=tuple(raw_provider_keys),
        historical=False,
        observation_granularity=granularity,
    )
    return ConversionResult(
        input_amount=input_amount,
        output_amount=output_amount,
        quote=quote,
        stale=stale,
    )


def _budget_categories(value: Any) -> tuple[BudgetCategoryAssumption, ...]:
    if not isinstance(value, list) or len(value) > 8:
        raise BrowserScenarioTokenError("Browser scenario budget categories are invalid.")
    result: list[BudgetCategoryAssumption] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {
            "category",
            "units_per_person_per_day",
        }:
            raise BrowserScenarioTokenError("Browser scenario budget category is invalid.")
        category = str(item["category"]).strip().lower()
        if category in seen:
            raise BrowserScenarioTokenError("Browser scenario budget categories must be unique.")
        seen.add(category)
        result.append(
            BudgetCategoryAssumption(
                category=category,
                units_per_person_per_day=_finite_decimal(
                    item["units_per_person_per_day"],
                    minimum=Decimal("0"),
                    strict_positive=True,
                    maximum=Decimal("100"),
                ),
            )
        )
    return tuple(result)


def _shopping_assumptions(value: Any) -> ShoppingAssumptions | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {
        "item_price",
        "shipping",
        "known_fees",
        "fx_markup_percent",
    }:
        raise BrowserScenarioTokenError("Browser scenario Shopping assumptions are invalid.")
    return ShoppingAssumptions(
        item_price=_finite_decimal(value["item_price"], minimum=Decimal("0")),
        shipping=_finite_decimal(value["shipping"], minimum=Decimal("0")),
        known_fees=_finite_decimal(value["known_fees"], minimum=Decimal("0")),
        fx_markup_percent=_finite_decimal(
            value["fx_markup_percent"],
            minimum=Decimal("0"),
            maximum=Decimal("25"),
        ),
    )


def _validate_budget_basis_payload(
    *,
    kind: str,
    budget_basis: str,
    planning_destination_amount: Decimal | None,
    fx_markup_percent: Decimal | None,
    source_fixed_fee: Decimal | None,
    destination_fixed_fee: Decimal | None,
) -> None:
    values = (
        planning_destination_amount,
        fx_markup_percent,
        source_fixed_fee,
        destination_fixed_fee,
    )
    if budget_basis == SavedScenarioBudgetBasis.REFERENCE_CONVERSION:
        if any(value is not None for value in values):
            raise BrowserScenarioTokenError(
                "Reference browser scenario cannot contain payment-adjusted values."
            )
        return
    if kind != SavedScenarioKind.BUDGET or any(value is None for value in values):
        raise BrowserScenarioTokenError(
            "Payment-adjusted browser scenario payload is incomplete."
        )


def _country_code(value: Any, *, allow_empty: bool) -> str:
    if value == "" and allow_empty:
        return ""
    if not isinstance(value, str):
        raise BrowserScenarioTokenError("Browser scenario country code is invalid.")
    code = value.upper().strip()
    if len(code) != 2 or not code.isascii() or not code.isalpha():
        raise BrowserScenarioTokenError("Browser scenario country code is invalid.")
    return code


def _city_slug(value: Any) -> str:
    if value == "":
        return ""
    if not isinstance(value, str) or len(value) > 140:
        raise BrowserScenarioTokenError("Browser scenario city is invalid.")
    slug = value.strip().lower()
    if not slug or any(character.isspace() for character in slug):
        raise BrowserScenarioTokenError("Browser scenario city is invalid.")
    return slug


def _title(value: Any) -> str:
    if not isinstance(value, str):
        raise BrowserScenarioTokenError("Browser scenario title is invalid.")
    title = value.strip()
    if len(title) > 120:
        raise BrowserScenarioTokenError("Browser scenario title is too long.")
    return title


def _optional_date_text(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _optional_date(value: Any) -> date | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise BrowserScenarioTokenError("Browser scenario date is invalid.")
    parsed = date.fromisoformat(value)
    if parsed < date(1970, 1, 1) or parsed > date(2200, 12, 31):
        raise BrowserScenarioTokenError("Browser scenario date is outside supported range.")
    return parsed


def _optional_decimal_text(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None


def _optional_decimal(
    value: Any,
    *,
    minimum: Decimal,
    maximum: Decimal | None = None,
) -> Decimal | None:
    if value is None:
        return None
    return _finite_decimal(value, minimum=minimum, maximum=maximum)


def _finite_decimal(
    value: Any,
    *,
    minimum: Decimal,
    maximum: Decimal | None = None,
    strict_positive: bool = False,
) -> Decimal:
    if not isinstance(value, str) or not value or len(value) > 80:
        raise BrowserScenarioTokenError("Browser scenario numeric value is invalid.")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise BrowserScenarioTokenError("Browser scenario numeric value is invalid.") from exc
    if not parsed.is_finite():
        raise BrowserScenarioTokenError("Browser scenario numeric value is invalid.")
    if strict_positive and parsed <= minimum:
        raise BrowserScenarioTokenError("Browser scenario numeric value must be positive.")
    if not strict_positive and parsed < minimum:
        raise BrowserScenarioTokenError("Browser scenario numeric value is below supported range.")
    if maximum is not None and parsed > maximum:
        raise BrowserScenarioTokenError("Browser scenario numeric value exceeds supported range.")
    return parsed


def _required_int(value: Any, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise BrowserScenarioTokenError("Browser scenario integer value is invalid.")
    return value


def _optional_int(value: Any, *, minimum: int, maximum: int) -> int | None:
    if value is None:
        return None
    return _required_int(value, minimum=minimum, maximum=maximum)
