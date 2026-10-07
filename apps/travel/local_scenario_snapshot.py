from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID, uuid4

from django.core import signing

from apps.countries.models import City, Country, Currency
from apps.exchange.budget import BudgetCategoryAssumption, BudgetInterpretationError
from apps.exchange.domain import (
    ConversionResult,
    FxDomainError,
    FxSourcePolicy,
    ObservationGranularity,
    ProviderPolicyMode,
    RateQuote,
    normalize_currency_code,
    normalize_provider_keys,
)
from apps.exchange.shopping import ShoppingAssumptions, ShoppingCalculationError
from apps.travel.models import SavedScenarioBudgetBasis, SavedScenarioKind
from apps.travel.scenarios import (
    SavedScenarioError,
    SavedScenarioSpec,
    validate_saved_scenario_spec,
)

_TOKEN_SALT = "travel.local-scenario:v1"
_MAX_TOKEN_LENGTH = 16_384
_MAX_DECIMAL_TEXT_LENGTH = 80
_MAX_CATEGORIES = 12


class LocalScenarioTokenError(ValueError):
    """Raised when a browser-local saved-scenario token cannot be trusted."""


@dataclass(frozen=True, slots=True)
class LocalScenarioSnapshot:
    import_key: UUID
    kind: SavedScenarioKind
    title: str
    scope_label: str
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
class MaterializedLocalScenario:
    import_key: UUID
    spec: SavedScenarioSpec
    conversion: ConversionResult


def build_local_scenario_token(
    *,
    spec: SavedScenarioSpec,
    conversion: ConversionResult,
    import_key: UUID | None = None,
) -> str:
    """Sign one validated browser-portable scenario snapshot.

    This token represents immutable saved evidence, not an authorization grant.
    It deliberately contains no account/user identifier.
    """

    validate_saved_scenario_spec(spec=spec, conversion=conversion)
    normalized_import_key = import_key or uuid4()
    quote = conversion.quote

    payload = {
        "v": 1,
        "import_key": str(normalized_import_key),
        "kind": spec.kind.value,
        "title": spec.title.strip(),
        "scope_label": _scope_label(spec),
        "source_currency": spec.source_currency.code,
        "destination_currency": spec.destination_currency.code,
        "source_country": spec.source_country.iso2 if spec.source_country is not None else "",
        "destination_country": (
            spec.destination_country.iso2 if spec.destination_country is not None else ""
        ),
        "destination_city_slug": (
            spec.destination_city.slug if spec.destination_city is not None else ""
        ),
        "source_amount": _decimal_text(spec.source_amount),
        "budget_basis": spec.budget_basis,
        "planning_destination_amount": _optional_decimal_text(spec.planning_destination_amount),
        "fx_markup_percent": _optional_decimal_text(spec.fx_markup_percent),
        "source_fixed_fee": _optional_decimal_text(spec.source_fixed_fee),
        "destination_fixed_fee": _optional_decimal_text(spec.destination_fixed_fee),
        "duration_days": spec.duration_days,
        "travelers": spec.travelers,
        "travel_start_date": (
            spec.travel_start_date.isoformat() if spec.travel_start_date is not None else None
        ),
        "travel_end_date": (
            spec.travel_end_date.isoformat() if spec.travel_end_date is not None else None
        ),
        "budget_categories": [
            {
                "category": item.category,
                "units": _decimal_text(item.units_per_person_per_day),
            }
            for item in spec.budget_categories
        ],
        "shopping": (
            {
                "item_price": _decimal_text(spec.shopping_assumptions.item_price),
                "shipping": _decimal_text(spec.shopping_assumptions.shipping),
                "known_fees": _decimal_text(spec.shopping_assumptions.known_fees),
                "fx_markup_percent": _decimal_text(spec.shopping_assumptions.fx_markup_percent),
            }
            if spec.shopping_assumptions is not None
            else None
        ),
        "conversion": {
            "output_amount": _decimal_text(conversion.output_amount),
            "rate": _decimal_text(quote.rate),
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
    return signing.dumps(payload, salt=_TOKEN_SALT, compress=True)


def load_local_scenario_token(token: str) -> LocalScenarioSnapshot:
    if not isinstance(token, str) or not token or len(token) > _MAX_TOKEN_LENGTH:
        raise LocalScenarioTokenError("Local scenario token is missing or invalid.")

    try:
        payload = signing.loads(token, salt=_TOKEN_SALT)
    except signing.BadSignature as exc:
        raise LocalScenarioTokenError("Local scenario token is invalid.") from exc

    expected_fields = {
        "v",
        "import_key",
        "kind",
        "title",
        "scope_label",
        "source_currency",
        "destination_currency",
        "source_country",
        "destination_country",
        "destination_city_slug",
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
    if not isinstance(payload, dict) or payload.get("v") != 1 or set(payload) != expected_fields:
        raise LocalScenarioTokenError("Local scenario token payload is invalid.")

    try:
        import_key = UUID(_required_text(payload["import_key"], maximum=64))
        kind = SavedScenarioKind(_required_text(payload["kind"], maximum=16))
        title = _text(payload["title"], maximum=120)
        scope_label = _required_text(payload["scope_label"], maximum=160)
        source_currency_code = normalize_currency_code(payload["source_currency"])
        destination_currency_code = normalize_currency_code(payload["destination_currency"])
        source_country_code = _country_code(payload["source_country"])
        destination_country_code = _country_code(payload["destination_country"])
        destination_city_slug = _city_slug(payload["destination_city_slug"])
        source_amount = _decimal(payload["source_amount"], minimum=Decimal("0"))
        budget_basis = SavedScenarioBudgetBasis(
            _required_text(payload["budget_basis"], maximum=24)
        ).value
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
        budget_categories = _budget_categories(payload["budget_categories"])
        shopping_assumptions = _shopping_assumptions(payload["shopping"])
        conversion = _conversion(
            payload["conversion"],
            source_amount=source_amount,
            source_currency_code=source_currency_code,
            destination_currency_code=destination_currency_code,
        )
    except (FxDomainError, TypeError, ValueError) as exc:
        if isinstance(exc, LocalScenarioTokenError):
            raise
        raise LocalScenarioTokenError("Local scenario token semantics are invalid.") from exc

    _validate_kind_payload(
        kind=kind,
        destination_country_code=destination_country_code,
        destination_city_slug=destination_city_slug,
        budget_basis=budget_basis,
        planning_destination_amount=planning_destination_amount,
        fx_markup_percent=fx_markup_percent,
        source_fixed_fee=source_fixed_fee,
        destination_fixed_fee=destination_fixed_fee,
        duration_days=duration_days,
        travelers=travelers,
        travel_start_date=travel_start_date,
        travel_end_date=travel_end_date,
        budget_categories=budget_categories,
        shopping_assumptions=shopping_assumptions,
    )

    return LocalScenarioSnapshot(
        import_key=import_key,
        kind=kind,
        title=title,
        scope_label=scope_label,
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
        budget_categories=budget_categories,
        shopping_assumptions=shopping_assumptions,
        conversion=conversion,
    )


def materialize_local_scenario(snapshot: LocalScenarioSnapshot) -> MaterializedLocalScenario:
    currencies = Currency.objects.in_bulk(
        [snapshot.source_currency_code, snapshot.destination_currency_code],
        field_name="code",
    )
    try:
        source_currency = currencies[snapshot.source_currency_code]
        destination_currency = currencies[snapshot.destination_currency_code]
    except KeyError as exc:
        raise LocalScenarioTokenError("Local scenario currency metadata is unavailable.") from exc

    source_country = _country(snapshot.source_country_code)
    destination_country = _country(snapshot.destination_country_code)
    destination_city = None
    if snapshot.destination_city_slug:
        if destination_country is None:
            raise LocalScenarioTokenError(
                "Local scenario city requires destination country metadata."
            )
        destination_city = City.objects.filter(
            country=destination_country,
            slug=snapshot.destination_city_slug,
            is_active=True,
        ).first()
        if destination_city is None:
            raise LocalScenarioTokenError("Local scenario city metadata is unavailable.")

    spec = SavedScenarioSpec(
        kind=snapshot.kind,
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
    )
    try:
        validate_saved_scenario_spec(spec=spec, conversion=snapshot.conversion)
    except SavedScenarioError as exc:
        raise LocalScenarioTokenError(str(exc)) from exc

    return MaterializedLocalScenario(
        import_key=snapshot.import_key,
        spec=spec,
        conversion=snapshot.conversion,
    )


def local_scenario_public_summary(snapshot: LocalScenarioSnapshot) -> dict[str, object]:
    """Return bounded display metadata safe to keep next to the signed browser token."""

    return {
        "id": str(snapshot.import_key),
        "kind": snapshot.kind.value,
        "title": snapshot.title,
        "scopeLabel": snapshot.scope_label,
        "sourceAmount": _decimal_text(snapshot.source_amount),
        "sourceCurrency": snapshot.source_currency_code,
        "destinationCurrency": snapshot.destination_currency_code,
        "durationDays": snapshot.duration_days,
        "travelers": snapshot.travelers,
        "effectiveDate": snapshot.conversion.quote.effective_date.isoformat(),
        "stale": snapshot.conversion.stale,
    }


def _conversion(
    value: Any,
    *,
    source_amount: Decimal,
    source_currency_code: str,
    destination_currency_code: str,
) -> ConversionResult:
    if not isinstance(value, dict):
        raise LocalScenarioTokenError("Local scenario conversion payload is invalid.")
    expected = {
        "output_amount",
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
        raise LocalScenarioTokenError("Local scenario conversion fields are invalid.")

    output_amount = _decimal(value["output_amount"], minimum=Decimal("0"))
    rate = _decimal(value["rate"], minimum=Decimal("0"), strict_positive=True)
    effective_date = _required_date(value["effective_date"])
    fetched_at = _required_datetime(value["fetched_at"])
    provider_policy_mode = ProviderPolicyMode(
        _required_text(value["provider_policy_mode"], maximum=16)
    )
    provider_policy_key = value["provider_policy_key"]
    if provider_policy_key is not None and not isinstance(provider_policy_key, str):
        raise LocalScenarioTokenError("Local scenario provider policy is invalid.")
    include_attribution = value["provider_policy_include_attribution"]
    if not isinstance(include_attribution, bool):
        raise LocalScenarioTokenError("Local scenario provider policy is invalid.")
    raw_provider_keys = value["provider_keys"]
    if not isinstance(raw_provider_keys, list):
        raise LocalScenarioTokenError("Local scenario provider attribution is invalid.")
    provider_keys = normalize_provider_keys(raw_provider_keys)
    observation_granularity = ObservationGranularity(
        _required_text(value["observation_granularity"], maximum=24)
    )
    stale = value["stale"]
    if not isinstance(stale, bool):
        raise LocalScenarioTokenError("Local scenario stale state is invalid.")

    provider_policy = FxSourcePolicy(
        mode=provider_policy_mode,
        provider_key=provider_policy_key,
        include_attribution=include_attribution,
    )
    try:
        quote = RateQuote(
            base_currency=source_currency_code,
            quote_currency=destination_currency_code,
            rate=rate,
            requested_date=None,
            effective_date=effective_date,
            fetched_at=fetched_at,
            provider_policy=provider_policy,
            provider_keys=provider_keys,
            historical=False,
            observation_granularity=observation_granularity,
        )
        return ConversionResult(
            input_amount=source_amount,
            output_amount=output_amount,
            quote=quote,
            stale=stale,
        )
    except ValueError as exc:
        raise LocalScenarioTokenError("Local scenario conversion semantics are invalid.") from exc


def _budget_categories(value: Any) -> tuple[BudgetCategoryAssumption, ...]:
    if not isinstance(value, list) or len(value) > _MAX_CATEGORIES:
        raise LocalScenarioTokenError("Local scenario budget categories are invalid.")
    categories: list[BudgetCategoryAssumption] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {"category", "units"}:
            raise LocalScenarioTokenError("Local scenario budget category is invalid.")
        category = _required_text(item["category"], maximum=80).strip().lower()
        if category in seen:
            raise LocalScenarioTokenError("Local scenario budget categories contain duplicates.")
        seen.add(category)
        try:
            categories.append(
                BudgetCategoryAssumption(
                    category=category,
                    units_per_person_per_day=_decimal(
                        item["units"],
                        minimum=Decimal("0"),
                        strict_positive=True,
                        maximum=Decimal("100"),
                    ),
                )
            )
        except BudgetInterpretationError as exc:
            raise LocalScenarioTokenError(str(exc)) from exc
    return tuple(categories)


def _shopping_assumptions(value: Any) -> ShoppingAssumptions | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise LocalScenarioTokenError("Local scenario shopping assumptions are invalid.")
    expected = {"item_price", "shipping", "known_fees", "fx_markup_percent"}
    if set(value) != expected:
        raise LocalScenarioTokenError("Local scenario shopping fields are invalid.")
    try:
        return ShoppingAssumptions(
            item_price=_decimal(value["item_price"], minimum=Decimal("0")),
            shipping=_decimal(value["shipping"], minimum=Decimal("0")),
            known_fees=_decimal(value["known_fees"], minimum=Decimal("0")),
            fx_markup_percent=_decimal(
                value["fx_markup_percent"],
                minimum=Decimal("0"),
                maximum=Decimal("25"),
            ),
        )
    except ShoppingCalculationError as exc:
        raise LocalScenarioTokenError(str(exc)) from exc


def _validate_kind_payload(
    *,
    kind: SavedScenarioKind,
    destination_country_code: str,
    destination_city_slug: str,
    budget_basis: str,
    planning_destination_amount: Decimal | None,
    fx_markup_percent: Decimal | None,
    source_fixed_fee: Decimal | None,
    destination_fixed_fee: Decimal | None,
    duration_days: int | None,
    travelers: int,
    travel_start_date: date | None,
    travel_end_date: date | None,
    budget_categories: tuple[BudgetCategoryAssumption, ...],
    shopping_assumptions: ShoppingAssumptions | None,
) -> None:
    if destination_city_slug and not destination_country_code:
        raise LocalScenarioTokenError("Local scenario city requires a destination country.")
    if travel_end_date is not None and travel_start_date is None:
        raise LocalScenarioTokenError("Local scenario end date requires a start date.")
    if (
        travel_start_date is not None
        and travel_end_date is not None
        and travel_end_date < travel_start_date
    ):
        raise LocalScenarioTokenError("Local scenario travel dates are invalid.")
    if kind == SavedScenarioKind.BUDGET:
        if not destination_country_code:
            raise LocalScenarioTokenError("Budget local scenario requires a destination country.")
        if duration_days is None:
            raise LocalScenarioTokenError("Budget local scenario requires a duration.")
        if not budget_categories:
            raise LocalScenarioTokenError("Budget local scenario requires explicit basket assumptions.")
        if shopping_assumptions is not None:
            raise LocalScenarioTokenError("Budget local scenario cannot carry shopping assumptions.")
    elif kind == SavedScenarioKind.SHOPPING:
        if duration_days is not None or travelers != 1 or budget_categories:
            raise LocalScenarioTokenError("Shopping local scenario contains budget-only assumptions.")
        if travel_start_date is not None or travel_end_date is not None:
            raise LocalScenarioTokenError("Shopping local scenario contains travel dates.")
        if shopping_assumptions is None:
            raise LocalScenarioTokenError("Shopping local scenario requires shopping assumptions.")
    else:
        raise LocalScenarioTokenError("Unsupported local scenario kind.")

    payment_fields = (
        planning_destination_amount,
        fx_markup_percent,
        source_fixed_fee,
        destination_fixed_fee,
    )
    if budget_basis == SavedScenarioBudgetBasis.REFERENCE_CONVERSION:
        if any(value is not None for value in payment_fields):
            raise LocalScenarioTokenError("Reference budget local scenario has payment-only fields.")
    elif budget_basis == SavedScenarioBudgetBasis.PAYMENT_ESTIMATE:
        if kind != SavedScenarioKind.BUDGET or any(value is None for value in payment_fields):
            raise LocalScenarioTokenError("Payment-adjusted local scenario payload is incomplete.")


def _scope_label(spec: SavedScenarioSpec) -> str:
    if spec.kind == SavedScenarioKind.SHOPPING:
        if spec.source_country is not None:
            return f"{spec.source_country.name} purchase"
        return f"{spec.source_currency.code} purchase"
    if spec.destination_city is not None and spec.destination_country is not None:
        return f"{spec.destination_city.name}, {spec.destination_country.name}"
    if spec.destination_country is not None:
        return spec.destination_country.name
    return "Saved travel-money plan"


def _country(code: str) -> Country | None:
    if not code:
        return None
    country = Country.objects.filter(iso2=code, is_active=True).first()
    if country is None:
        raise LocalScenarioTokenError("Local scenario country metadata is unavailable.")
    return country


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


def _optional_decimal_text(value: Decimal | None) -> str | None:
    return _decimal_text(value) if value is not None else None


def _decimal(
    value: Any,
    *,
    minimum: Decimal,
    maximum: Decimal | None = None,
    strict_positive: bool = False,
) -> Decimal:
    if not isinstance(value, str) or not value or len(value) > _MAX_DECIMAL_TEXT_LENGTH:
        raise LocalScenarioTokenError("Local scenario numeric value is invalid.")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise LocalScenarioTokenError("Local scenario numeric value is invalid.") from exc
    if not parsed.is_finite():
        raise LocalScenarioTokenError("Local scenario numeric value is invalid.")
    if strict_positive and parsed <= minimum:
        raise LocalScenarioTokenError("Local scenario numeric value must be positive.")
    if not strict_positive and parsed < minimum:
        raise LocalScenarioTokenError("Local scenario numeric value is out of range.")
    if maximum is not None and parsed > maximum:
        raise LocalScenarioTokenError("Local scenario numeric value is out of range.")
    return parsed


def _optional_decimal(
    value: Any,
    *,
    minimum: Decimal,
    maximum: Decimal | None = None,
) -> Decimal | None:
    if value is None:
        return None
    return _decimal(value, minimum=minimum, maximum=maximum)


def _text(value: Any, *, maximum: int) -> str:
    if not isinstance(value, str) or len(value) > maximum:
        raise LocalScenarioTokenError("Local scenario text value is invalid.")
    return value


def _required_text(value: Any, *, maximum: int) -> str:
    text = _text(value, maximum=maximum).strip()
    if not text:
        raise LocalScenarioTokenError("Local scenario text value is required.")
    return text


def _country_code(value: Any) -> str:
    text = _text(value, maximum=2).upper().strip()
    if text and (len(text) != 2 or not text.isascii() or not text.isalpha()):
        raise LocalScenarioTokenError("Local scenario country code is invalid.")
    return text


def _city_slug(value: Any) -> str:
    text = _text(value, maximum=140).strip().lower()
    if text and (
        any(character.isspace() for character in text)
        or not all(character.isalnum() or character == "-" for character in text)
    ):
        raise LocalScenarioTokenError("Local scenario city slug is invalid.")
    return text


def _required_int(value: Any, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise LocalScenarioTokenError("Local scenario integer value is invalid.")
    return value


def _optional_int(value: Any, *, minimum: int, maximum: int) -> int | None:
    if value is None:
        return None
    return _required_int(value, minimum=minimum, maximum=maximum)


def _required_date(value: Any) -> date:
    if not isinstance(value, str):
        raise LocalScenarioTokenError("Local scenario date value is invalid.")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise LocalScenarioTokenError("Local scenario date value is invalid.") from exc


def _optional_date(value: Any) -> date | None:
    if value is None:
        return None
    return _required_date(value)


def _required_datetime(value: Any) -> datetime:
    if not isinstance(value, str):
        raise LocalScenarioTokenError("Local scenario timestamp is invalid.")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise LocalScenarioTokenError("Local scenario timestamp is invalid.") from exc
    if parsed.tzinfo is None:
        raise LocalScenarioTokenError("Local scenario timestamp must be timezone-aware.")
    return parsed
