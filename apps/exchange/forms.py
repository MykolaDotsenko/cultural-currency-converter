from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from django import forms
from django.utils import timezone

from apps.countries.models import City, Country, CountryCurrency, Currency
from apps.culture.models import TypicalPriceCategory
from apps.exchange.budget import (
    BudgetAssumptions,
    BudgetBasis,
    BudgetCategoryAssumption,
    BudgetInterpretationError,
)
from apps.exchange.domain import RateSeriesRangeError, normalize_currency_code
from apps.exchange.payment_estimate import MAX_FX_MARKUP_PERCENT
from apps.exchange.shopping import (
    MAX_SHOPPING_FX_MARKUP_PERCENT,
    ShoppingAssumptions,
    ShoppingCalculationError,
)

MAX_CONVERSION_AMOUNT = Decimal("1000000000")
RATE_MODE_LATEST = "latest"
RATE_MODE_HISTORICAL = "historical"
RATE_MODE_CHOICES = (
    (RATE_MODE_LATEST, "Latest available"),
    (RATE_MODE_HISTORICAL, "Historical date"),
)
_AMOUNT_PATTERN = re.compile(r"^\d+(?:[.,]\d+)?$")


def parse_amount_text(value: str, *, minor_units: int) -> Decimal:
    """Parse a user-facing amount without guessing grouping semantics."""

    text = value.strip()
    if not text:
        raise forms.ValidationError("Enter an amount.")
    if text.startswith("-"):
        raise forms.ValidationError("Enter zero or a positive amount.")
    if not _AMOUNT_PATTERN.fullmatch(text):
        raise forms.ValidationError(
            "Enter an amount such as 1234.56 or 1234,56, without thousands separators."
        )

    separator = "," if "," in text else "." if "." in text else None
    fraction = text.split(separator, 1)[1] if separator else ""
    integer = text.split(separator, 1)[0] if separator else text
    significant_fraction = fraction.rstrip("0")

    if (
        separator
        and len(fraction) == 3
        and len(significant_fraction) == 3
        and len(integer) <= 3
        and minor_units != 3
    ):
        raise forms.ValidationError(
            "This amount is ambiguous. Enter it without thousands separators."
        )
    if len(significant_fraction) > minor_units:
        unit_label = "decimal place" if minor_units == 1 else "decimal places"
        raise forms.ValidationError(f"This currency supports at most {minor_units} {unit_label}.")

    try:
        amount = Decimal(text.replace(",", "."))
    except InvalidOperation as exc:
        raise forms.ValidationError("Enter a valid decimal amount.") from exc

    if amount > MAX_CONVERSION_AMOUNT:
        raise forms.ValidationError("Enter an amount no greater than 1,000,000,000.")
    return amount


DestinationResolution = tuple[Country, City | None, Currency]


def _destination_reference_choices() -> tuple[
    dict[str, Currency],
    dict[str, DestinationResolution],
    list[tuple[str, str]],
    list[object],
]:
    currencies = list(Currency.objects.filter(is_active=True).order_by("code"))
    currency_by_code = {currency.code: currency for currency in currencies}
    currency_choices = [
        (currency.code, f"{currency.name} · {currency.code}") for currency in currencies
    ]

    primary_links = list(
        CountryCurrency.objects.current()
        .primary()
        .select_related("country", "currency")
        .order_by("country__name", "country__iso2")
    )
    destination_by_token: dict[str, DestinationResolution] = {}
    country_choices: list[tuple[str, str]] = []
    country_ids: list[int] = []
    for link in primary_links:
        token = link.country.iso2
        destination_by_token[token] = (link.country, None, link.currency)
        country_choices.append((token, f"{link.country.name} · {link.currency.code}"))
        country_ids.append(link.country_id)

    city_choices: list[tuple[str, str]] = []
    if country_ids:
        for city in (
            City.objects.filter(
                is_active=True,
                country_id__in=country_ids,
                country__is_active=True,
            )
            .select_related("country")
            .order_by("country__name", "name", "slug")
        ):
            country_entry = destination_by_token.get(city.country.iso2)
            if country_entry is None:
                continue
            currency = country_entry[2]
            token = f"{city.country.iso2}:{city.slug}"
            destination_by_token[token] = (city.country, city, currency)
            city_choices.append((token, f"{city.name}, {city.country.name} · {currency.code}"))

    destination_choices: list[object] = [("", "Choose a country or city")]
    if city_choices:
        destination_choices.append(("Cities", city_choices))
    if country_choices:
        destination_choices.append(("Countries", country_choices))

    return currency_by_code, destination_by_token, currency_choices, destination_choices


class DestinationModeForm(forms.Form):
    """Destination-first entry point that resolves into the canonical converter."""

    amount = forms.CharField(max_length=64, label="Amount")
    source_currency = forms.ChoiceField(label="Your currency")
    destination = forms.ChoiceField(label="Where are you going?")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        (
            self._currency_by_code,
            self._destination_by_token,
            currency_choices,
            destination_choices,
        ) = _destination_reference_choices()
        self.fields["source_currency"].choices = currency_choices
        self.fields["destination"].choices = destination_choices

        self.fields["amount"].widget.attrs.update(
            {
                "class": "qa-text-input",
                "inputmode": "decimal",
                "autocomplete": "off",
                "placeholder": "100",
            }
        )
        self.fields["source_currency"].widget.attrs["class"] = "qa-native-select"
        self.fields["destination"].widget.attrs["class"] = "qa-native-select"

        if not self.is_bound:
            self.initial.setdefault("amount", "100")
            preferred_source = "EUR" if "EUR" in self._currency_by_code else ""
            if not preferred_source and self._currency_by_code:
                preferred_source = next(iter(self._currency_by_code))
            if preferred_source:
                self.initial.setdefault("source_currency", preferred_source)

    @property
    def reference_data_ready(self) -> bool:
        return bool(self._currency_by_code and self._destination_by_token)

    def add_error(self, field, error):
        super().add_error(field, error)
        if field and field in self.fields:
            self.fields[field].widget.attrs.update(
                {
                    "aria-invalid": "true",
                    "aria-describedby": f"{field}-error",
                }
            )

    def clean(self):
        cleaned = super().clean()

        source_code = str(cleaned.get("source_currency") or "").upper()
        source_currency = self._currency_by_code.get(source_code)
        raw_amount = cleaned.get("amount")
        if source_currency is not None and raw_amount is not None:
            try:
                cleaned["amount_decimal"] = parse_amount_text(
                    str(raw_amount),
                    minor_units=source_currency.minor_units,
                )
            except forms.ValidationError as exc:
                self.add_error("amount", exc)

        destination_token = str(cleaned.get("destination") or "")
        destination = self._destination_by_token.get(destination_token)
        if destination is not None:
            country, city, currency = destination
            cleaned["destination_country"] = country.iso2
            cleaned["destination_city_slug"] = city.slug if city is not None else ""
            cleaned["destination_currency"] = currency.code

        return cleaned


class CurrentConversionForm(forms.Form):
    rate_mode = forms.ChoiceField(
        required=False,
        choices=RATE_MODE_CHOICES,
        initial=RATE_MODE_LATEST,
        widget=forms.RadioSelect,
        label="Rate date",
    )
    requested_date = forms.DateField(
        required=False,
        label="Historical date",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    amount = forms.CharField(max_length=64, label="Amount")
    source_country = forms.ChoiceField(required=False, label="Source country")
    source_currency = forms.ChoiceField(label="Source currency")
    destination_country = forms.ChoiceField(required=False, label="Destination country")
    destination_currency = forms.ChoiceField(label="Destination currency")
    destination_city_slug = forms.CharField(
        required=False,
        max_length=140,
        widget=forms.HiddenInput(),
    )

    def __init__(self, *args, **kwargs):
        if args and args[0] is not None and "rate_mode" not in args[0]:
            data = args[0].copy()
            data["rate_mode"] = RATE_MODE_LATEST
            args = (data, *args[1:])
        elif kwargs.get("data") is not None and "rate_mode" not in kwargs["data"]:
            data = kwargs["data"].copy()
            data["rate_mode"] = RATE_MODE_LATEST
            kwargs["data"] = data

        super().__init__(*args, **kwargs)

        raw_mode = (
            self.data.get("rate_mode")
            if self.is_bound
            else self.initial.get("rate_mode", RATE_MODE_LATEST)
        )
        historical_mode = raw_mode == RATE_MODE_HISTORICAL
        currency_query = (
            Currency.objects.all() if historical_mode else Currency.objects.filter(is_active=True)
        )
        currencies = list(currency_query.order_by("code"))

        self._archived_bound_codes: set[str] = set()
        if self.is_bound and not historical_mode:
            raw_codes = {
                str(self.data.get(field_name) or "").upper().strip()
                for field_name in ("source_currency", "destination_currency")
            }
            raw_codes.discard("")
            archived_bound = list(
                Currency.objects.filter(code__in=raw_codes, is_active=False)
                .only("code", "name")
                .order_by("code")
            )
            self._archived_bound_codes = {currency.code for currency in archived_bound}
            currencies.extend(archived_bound)
        countries = list(Country.objects.filter(is_active=True).order_by("name"))

        self._currency_by_code = {currency.code: currency for currency in currencies}
        self._country_by_code = {country.iso2: country for country in countries}

        currency_choices = [
            (currency.code, f"{currency.name} · {currency.code}") for currency in currencies
        ]
        country_choices = [("", "No country context")] + [
            (country.iso2, f"{country.name} · {country.iso2}") for country in countries
        ]

        self.fields["source_currency"].choices = currency_choices
        self.fields["destination_currency"].choices = currency_choices
        self.fields["source_country"].choices = country_choices
        self.fields["destination_country"].choices = country_choices

        self.fields["requested_date"].widget.attrs.update(
            {
                "class": "qa-date-input",
                "max": timezone.localdate().isoformat(),
            }
        )

        for field_name in (
            "source_country",
            "source_currency",
            "destination_country",
            "destination_currency",
        ):
            self.fields[field_name].widget.attrs["class"] = "qa-native-select"

    def add_error(self, field, error):
        super().add_error(field, error)
        if field and field in self.fields and field != "amount":
            self.fields[field].widget.attrs.update(
                {
                    "aria-invalid": "true",
                    "aria-describedby": f"{field}-error",
                }
            )

    @property
    def reference_data_ready(self) -> bool:
        return bool(self._currency_by_code)

    def currency_for_code(self, code: str | None) -> Currency | None:
        return self._currency_by_code.get((code or "").upper())

    def country_for_code(self, code: str | None) -> Country | None:
        return self._country_by_code.get((code or "").upper())

    def clean(self):
        cleaned = super().clean()

        rate_mode = cleaned.get("rate_mode") or RATE_MODE_LATEST
        cleaned["rate_mode"] = rate_mode
        requested_date = cleaned.get("requested_date")
        if rate_mode == RATE_MODE_HISTORICAL:
            if requested_date is None:
                self.add_error("requested_date", "Choose a historical date.")
            elif requested_date > timezone.localdate():
                self.add_error("requested_date", "Historical date cannot be in the future.")
        else:
            cleaned["requested_date"] = None

        source_code = cleaned.get("source_currency")
        source_currency = self.currency_for_code(source_code)
        raw_amount = cleaned.get("amount")
        if source_currency is not None and raw_amount is not None:
            try:
                cleaned["amount_decimal"] = parse_amount_text(
                    raw_amount,
                    minor_units=source_currency.minor_units,
                )
            except forms.ValidationError as exc:
                self.add_error("amount", exc)

        if rate_mode == RATE_MODE_LATEST:
            archived_sides: set[str] = set()
            for side in ("source", "destination"):
                raw_code = str(self.data.get(f"{side}_currency") or "").upper().strip()
                if raw_code not in self._archived_bound_codes:
                    continue
                currency = self.currency_for_code(raw_code)
                if currency is not None:
                    archived_sides.add(side)
                    self.add_error(
                        f"{side}_currency",
                        f"{currency.name} ({currency.code}) is archived and has no current-market "
                        "interpretation. Switch Rate date to Historical date to use it.",
                    )
            for side in ("source", "destination"):
                if side not in archived_sides:
                    self._validate_country_currency(side, cleaned)

        self._validate_destination_city(cleaned)
        return cleaned

    @property
    def historical_mode(self) -> bool:
        if self.is_bound:
            return self.data.get("rate_mode") == RATE_MODE_HISTORICAL
        return self.initial.get("rate_mode") == RATE_MODE_HISTORICAL

    def _validate_destination_city(self, cleaned: dict[str, object]) -> None:
        city_slug = str(cleaned.get("destination_city_slug") or "").strip().lower()
        cleaned["destination_city_slug"] = city_slug
        if not city_slug:
            return

        country_code = str(cleaned.get("destination_country") or "").upper()
        if not country_code:
            cleaned["destination_city_slug"] = ""
            self.add_error(
                "destination_country",
                "Choose the destination country again to keep the selected city context.",
            )
            return

        exists = City.objects.filter(
            country__iso2=country_code,
            country__is_active=True,
            slug=city_slug,
            is_active=True,
        ).exists()
        if not exists:
            cleaned["destination_city_slug"] = ""
            self.add_error(
                "destination_country",
                "The selected city is no longer available for this destination. "
                "Choose the destination again.",
            )

    def _validate_country_currency(self, side: str, cleaned: dict[str, object]) -> None:
        country_code = cleaned.get(f"{side}_country")
        currency_code = cleaned.get(f"{side}_currency")
        if not country_code or not currency_code:
            return

        exists = (
            CountryCurrency.objects.current()
            .filter(
                country__iso2=country_code,
                currency__code=currency_code,
            )
            .exists()
        )
        if not exists:
            self.add_error(
                f"{side}_currency",
                "Choose a currency currently associated with this country, "
                "or remove the country context.",
            )


class PaymentEstimateForm(forms.Form):
    fx_markup_percent = forms.DecimalField(
        required=False,
        min_value=Decimal("0"),
        max_value=MAX_FX_MARKUP_PERCENT,
        max_digits=5,
        decimal_places=2,
        initial=Decimal("0"),
        label="FX markup",
        widget=forms.NumberInput(
            attrs={
                "class": "qa-text-input",
                "inputmode": "decimal",
                "min": "0",
                "max": format(MAX_SHOPPING_FX_MARKUP_PERCENT, "f"),
                "step": "0.01",
            }
        ),
    )
    source_fixed_fee = forms.CharField(
        required=False,
        initial="0",
        max_length=64,
        widget=forms.TextInput(
            attrs={
                "class": "qa-text-input",
                "inputmode": "decimal",
                "autocomplete": "off",
            }
        ),
    )
    destination_fixed_fee = forms.CharField(
        required=False,
        initial="0",
        max_length=64,
        widget=forms.TextInput(
            attrs={
                "class": "qa-text-input",
                "inputmode": "decimal",
                "autocomplete": "off",
            }
        ),
    )

    def __init__(
        self,
        *args,
        source_currency_code: str,
        destination_currency_code: str,
        source_minor_units: int,
        destination_minor_units: int,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.source_minor_units = source_minor_units
        self.destination_minor_units = destination_minor_units
        self.fields["source_fixed_fee"].label = f"Fixed fee in {source_currency_code}"
        self.fields[
            "destination_fixed_fee"
        ].label = f"Fixed local fee in {destination_currency_code}"

    def add_error(self, field, error):
        super().add_error(field, error)
        if field and field in self.fields:
            self.fields[field].widget.attrs.update(
                {
                    "aria-invalid": "true",
                    "aria-describedby": f"{field}-error",
                }
            )

    def clean(self):
        cleaned = super().clean()
        self._clean_fee(
            cleaned,
            field_name="source_fixed_fee",
            minor_units=self.source_minor_units,
        )
        self._clean_fee(
            cleaned,
            field_name="destination_fixed_fee",
            minor_units=self.destination_minor_units,
        )
        if cleaned.get("fx_markup_percent") is None and not self.has_error("fx_markup_percent"):
            cleaned["fx_markup_percent"] = Decimal("0")
        return cleaned

    def _clean_fee(
        self,
        cleaned: dict[str, object],
        *,
        field_name: str,
        minor_units: int,
    ) -> None:
        raw = cleaned.get(field_name)
        if raw is None or self.has_error(field_name):
            return
        try:
            parsed = parse_amount_text(str(raw).strip() or "0", minor_units=minor_units)
        except forms.ValidationError as exc:
            self.add_error(field_name, exc)
            return
        cleaned[f"{field_name}_decimal"] = parsed


class ShoppingCalculationForm(forms.Form):
    """Explicit foreign-purchase inputs for the canonical shopping calculation."""

    purchase_country = forms.ChoiceField(required=False, label="Purchase country")
    purchase_currency = forms.ChoiceField(label="Purchase currency")
    home_currency = forms.ChoiceField(label="Your home currency")
    item_price = forms.CharField(max_length=64, label="Item price")
    shipping = forms.CharField(required=False, max_length=64, initial="0", label="Shipping")
    known_fees = forms.CharField(
        required=False,
        max_length=64,
        initial="0",
        label="Known fees",
    )
    fx_markup_percent = forms.DecimalField(
        required=False,
        min_value=Decimal("0"),
        max_value=MAX_SHOPPING_FX_MARKUP_PERCENT,
        max_digits=5,
        decimal_places=2,
        initial=Decimal("0"),
        label="FX markup assumption",
        widget=forms.NumberInput(
            attrs={
                "class": "qa-text-input",
                "inputmode": "decimal",
                "min": "0",
                "max": format(MAX_FX_MARKUP_PERCENT, "f"),
                "step": "0.01",
            }
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        currencies = list(Currency.objects.filter(is_active=True).order_by("code"))
        countries = list(Country.objects.filter(is_active=True).order_by("name"))
        self._currency_by_code = {currency.code: currency for currency in currencies}
        self._country_by_code = {country.iso2: country for country in countries}

        currency_choices = [
            (currency.code, f"{currency.name} · {currency.code}") for currency in currencies
        ]
        self.fields["purchase_currency"].choices = currency_choices
        self.fields["home_currency"].choices = currency_choices
        self.fields["purchase_country"].choices = [("", "No country context")] + [
            (country.iso2, f"{country.name} · {country.iso2}") for country in countries
        ]

        for field_name in ("purchase_country", "purchase_currency", "home_currency"):
            self.fields[field_name].widget.attrs["class"] = "qa-native-select"
        for field_name in ("item_price", "shipping", "known_fees"):
            self.fields[field_name].widget.attrs.update(
                {
                    "class": "qa-text-input",
                    "inputmode": "decimal",
                    "autocomplete": "off",
                }
            )

        if not self.is_bound and currencies:
            home_code = "EUR" if "EUR" in self._currency_by_code else currencies[0].code
            purchase_code = next(
                (
                    code
                    for code in ("USD", "JPY", "GBP")
                    if code in self._currency_by_code and code != home_code
                ),
                next(
                    (
                        currency.code
                        for currency in currencies
                        if currency.code != home_code
                    ),
                    home_code,
                ),
            )
            self.initial.setdefault("home_currency", home_code)
            self.initial.setdefault("purchase_currency", purchase_code)
            self.initial.setdefault("item_price", "100")

    @property
    def reference_data_ready(self) -> bool:
        return len(self._currency_by_code) >= 2

    def add_error(self, field, error):
        super().add_error(field, error)
        if field and field in self.fields:
            self.fields[field].widget.attrs.update(
                {
                    "aria-invalid": "true",
                    "aria-describedby": f"{field}-error",
                }
            )

    def clean(self):
        cleaned = super().clean()
        purchase_code = str(cleaned.get("purchase_currency") or "").upper()
        home_code = str(cleaned.get("home_currency") or "").upper()
        purchase_currency = self._currency_by_code.get(purchase_code)
        home_currency = self._currency_by_code.get(home_code)

        if purchase_code and home_code and purchase_code == home_code:
            self.add_error(
                "home_currency",
                "Choose a different home currency for a foreign-currency purchase.",
            )

        country_code = str(cleaned.get("purchase_country") or "").upper()
        if country_code and purchase_code:
            current_pair = (
                CountryCurrency.objects.current()
                .filter(country__iso2=country_code, currency__code=purchase_code)
                .exists()
            )
            if not current_pair:
                self.add_error(
                    "purchase_currency",
                    "Choose a currency currently associated with this purchase country, "
                    "or remove the country context.",
                )

        if purchase_currency is not None:
            for field_name in ("item_price", "shipping", "known_fees"):
                raw = str(cleaned.get(field_name) or "").strip()
                if field_name != "item_price" and not raw:
                    raw = "0"
                if not raw:
                    continue
                try:
                    cleaned[f"{field_name}_decimal"] = parse_amount_text(
                        raw,
                        minor_units=purchase_currency.minor_units,
                    )
                except forms.ValidationError as exc:
                    self.add_error(field_name, exc)

        if self.errors or purchase_currency is None or home_currency is None:
            return cleaned

        try:
            assumptions = ShoppingAssumptions(
                item_price=cleaned["item_price_decimal"],
                shipping=cleaned.get("shipping_decimal", Decimal("0")),
                known_fees=cleaned.get("known_fees_decimal", Decimal("0")),
                fx_markup_percent=cleaned.get("fx_markup_percent") or Decimal("0"),
            )
        except (KeyError, ShoppingCalculationError) as exc:
            raise forms.ValidationError(str(exc)) from exc

        cleaned["shopping_assumptions"] = assumptions
        cleaned["purchase_currency_object"] = purchase_currency
        cleaned["home_currency_object"] = home_currency
        cleaned["purchase_country_object"] = self._country_by_code.get(country_code)
        return cleaned


_BUDGET_DEFAULT_UNITS: dict[str, Decimal] = {
    "coffee": Decimal("1"),
    "casual_meal": Decimal("2"),
    "transit": Decimal("2"),
    "groceries": Decimal("1"),
    "other": Decimal("1"),
}


class BudgetInterpretationForm(forms.Form):
    duration_days = forms.IntegerField(
        min_value=1,
        max_value=365,
        initial=3,
        label="Trip duration",
        widget=forms.NumberInput(
            attrs={
                "class": "qa-text-input",
                "inputmode": "numeric",
                "min": "1",
                "max": "365",
                "step": "1",
                "aria-describedby": "duration_days-hint",
            }
        ),
    )
    travelers = forms.IntegerField(
        min_value=1,
        max_value=20,
        initial=1,
        label="Travelers",
        widget=forms.NumberInput(
            attrs={
                "class": "qa-text-input",
                "inputmode": "numeric",
                "min": "1",
                "max": "20",
                "step": "1",
                "aria-describedby": "travelers-hint",
            }
        ),
    )

    def __init__(
        self,
        *args,
        category_options: tuple[tuple[str, str], ...],
        basis: BudgetBasis = BudgetBasis.REFERENCE_CONVERSION,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        if not isinstance(basis, BudgetBasis):
            raise ValueError("Budget form basis must be a BudgetBasis value.")
        self.budget_basis = basis
        allowed_categories = {value for value, _label in TypicalPriceCategory.choices}
        visible_labels: dict[str, str] = {}
        for category, label in category_options:
            if category not in allowed_categories or not re.fullmatch(r"[a-z0-9_]+", category):
                raise ValueError("Budget category keys must be canonical identifiers.")
            if category in visible_labels:
                raise ValueError("Budget category options must be unique.")
            visible_labels[category] = label
        self.category_options = category_options

        # Define every known category as an optional field, but render only the
        # currently sourced options. This preserves a submitted category as an
        # explicit assumption if its source row disappears between page load
        # and POST; the domain can then return insufficient-data rather than
        # silently shrinking the user's basket.
        for category, generic_label in TypicalPriceCategory.choices:
            field_name = self.units_field_name(category)
            label = visible_labels.get(category, generic_label)
            self.fields[field_name] = forms.DecimalField(
                required=False,
                min_value=Decimal("0.01"),
                max_value=Decimal("100"),
                max_digits=5,
                decimal_places=2,
                initial=(
                    _BUDGET_DEFAULT_UNITS.get(category, Decimal("1"))
                    if category in visible_labels
                    else None
                ),
                label=f"{label} per person / day",
                widget=forms.NumberInput(
                    attrs={
                        "class": "qa-text-input",
                        "inputmode": "decimal",
                        "min": "0.01",
                        "max": "100",
                        "step": "0.01",
                        "aria-describedby": (f"{field_name}-anchor {field_name}-source"),
                    }
                ),
            )

    @staticmethod
    def units_field_name(category: str) -> str:
        return f"units_{category}"

    def add_error(self, field, error):
        super().add_error(field, error)
        if field and field in self.fields:
            widget = self.fields[field].widget
            existing_description = str(widget.attrs.get("aria-describedby", "")).strip()
            descriptions = " ".join(
                item for item in (f"{field}-error", existing_description) if item
            )
            widget.attrs.update(
                {
                    "aria-invalid": "true",
                    "aria-describedby": descriptions,
                }
            )

    def clean(self):
        cleaned = super().clean()
        if self.errors:
            return cleaned

        categories: list[BudgetCategoryAssumption] = []
        for category, _label in TypicalPriceCategory.choices:
            value = cleaned.get(self.units_field_name(category))
            if value is None:
                continue
            categories.append(
                BudgetCategoryAssumption(
                    category=category,
                    units_per_person_per_day=value,
                )
            )

        if not categories:
            raise forms.ValidationError("Keep at least one daily reference item.")

        try:
            cleaned["budget_assumptions"] = BudgetAssumptions(
                duration_days=cleaned["duration_days"],
                travelers=cleaned["travelers"],
                categories=tuple(categories),
                basis=self.budget_basis,
            )
        except BudgetInterpretationError as exc:
            raise forms.ValidationError(str(exc)) from exc
        return cleaned


_COMPARISON_CATEGORY_OPTIONS: tuple[tuple[str, str], ...] = (
    (TypicalPriceCategory.COFFEE, "Coffee"),
    (TypicalPriceCategory.CASUAL_MEAL, "Casual meal"),
    (TypicalPriceCategory.TRANSIT, "Transit"),
)


class SameAmountDestinationsForm(forms.Form):
    """View one explicit source amount across several canonical destination scopes."""

    amount = forms.CharField(max_length=64, label="Amount")
    source_currency = forms.ChoiceField(label="Your currency")
    destinations = forms.MultipleChoiceField(
        label="Destinations",
        widget=forms.CheckboxSelectMultiple,
    )

    MIN_DESTINATIONS = 2
    MAX_DESTINATIONS = 4

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        (
            self._currency_by_code,
            self._destination_by_token,
            currency_choices,
            destination_choices,
        ) = _destination_reference_choices()
        self.fields["source_currency"].choices = currency_choices
        self.fields["destinations"].choices = destination_choices

        self.fields["amount"].widget.attrs.update(
            {
                "class": "qa-text-input",
                "inputmode": "decimal",
                "autocomplete": "off",
                "placeholder": "100",
            }
        )
        self.fields["source_currency"].widget.attrs["class"] = "qa-native-select"
        self.fields["destinations"].widget.attrs["class"] = "qa-same-amount__choices"

        if not self.is_bound:
            self.initial.setdefault("amount", "100")
            preferred_source = "EUR" if "EUR" in self._currency_by_code else ""
            if not preferred_source and self._currency_by_code:
                preferred_source = next(iter(self._currency_by_code))
            if preferred_source:
                self.initial.setdefault("source_currency", preferred_source)

            preferred_destinations = tuple(
                token
                for token in ("JP:tokyo", "SG:singapore", "CA:toronto")
                if token in self._destination_by_token
            )
            if len(preferred_destinations) >= self.MIN_DESTINATIONS:
                self.initial.setdefault("destinations", preferred_destinations)

    @property
    def reference_data_ready(self) -> bool:
        return bool(
            self._currency_by_code and len(self._destination_by_token) >= self.MIN_DESTINATIONS
        )

    def add_error(self, field, error):
        super().add_error(field, error)
        if field and field in self.fields:
            self.fields[field].widget.attrs.update(
                {
                    "aria-invalid": "true",
                    "aria-describedby": f"{field}-error",
                }
            )

    def clean(self):
        cleaned = super().clean()

        source_code = str(cleaned.get("source_currency") or "").upper()
        source_currency = self._currency_by_code.get(source_code)
        raw_amount = cleaned.get("amount")
        if source_currency is not None and raw_amount is not None:
            cleaned["source_minor_units"] = source_currency.minor_units
            try:
                cleaned["amount_decimal"] = parse_amount_text(
                    str(raw_amount),
                    minor_units=source_currency.minor_units,
                )
            except forms.ValidationError as exc:
                self.add_error("amount", exc)

        raw_tokens = tuple(str(token) for token in cleaned.get("destinations") or ())
        if raw_tokens:
            unique_tokens = tuple(dict.fromkeys(raw_tokens))
            if len(unique_tokens) != len(raw_tokens):
                self.add_error("destinations", "Choose each destination only once.")
            if not self.MIN_DESTINATIONS <= len(unique_tokens) <= self.MAX_DESTINATIONS:
                self.add_error(
                    "destinations",
                    (
                        f"Choose between {self.MIN_DESTINATIONS} and "
                        f"{self.MAX_DESTINATIONS} destinations."
                    ),
                )

            resolved = []
            for token in unique_tokens:
                destination = self._destination_by_token.get(token)
                if destination is None:
                    self.add_error(
                        "destinations", "One selected destination is no longer available."
                    )
                    continue
                country, city, currency = destination
                resolved.append(
                    {
                        "token": token,
                        "country_code": country.iso2,
                        "country_name": country.name,
                        "city_slug": city.slug if city is not None else "",
                        "city_name": city.name if city is not None else "",
                        "scope_label": (
                            f"{city.name}, {country.name}" if city is not None else country.name
                        ),
                        "currency_code": currency.code,
                        "minor_units": currency.minor_units,
                    }
                )
            cleaned["resolved_destinations"] = tuple(resolved)

        return cleaned


class DestinationComparisonForm(BudgetInterpretationForm):
    """Compare one explicit source budget across two current destination scopes."""

    amount = forms.CharField(max_length=64, label="Amount")
    source_currency = forms.ChoiceField(label="Your currency")
    left_destination = forms.ChoiceField(label="Destination A")
    right_destination = forms.ChoiceField(label="Destination B")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, category_options=_COMPARISON_CATEGORY_OPTIONS, **kwargs)

        (
            self._currency_by_code,
            self._destination_by_token,
            currency_choices,
            destination_choices,
        ) = _destination_reference_choices()

        self.fields["source_currency"].choices = currency_choices
        self.fields["left_destination"].choices = destination_choices
        self.fields["right_destination"].choices = destination_choices

        visible_categories = {category for category, _label in _COMPARISON_CATEGORY_OPTIONS}
        for category, _label in TypicalPriceCategory.choices:
            field_name = self.units_field_name(category)
            if category not in visible_categories:
                self.fields.pop(field_name, None)
                continue
            self.fields[field_name].widget.attrs["aria-describedby"] = f"{field_name}-hint"

        self.fields["amount"].widget.attrs.update(
            {
                "class": "qa-text-input",
                "inputmode": "decimal",
                "autocomplete": "off",
                "placeholder": "500",
            }
        )
        self.fields["source_currency"].widget.attrs["class"] = "qa-native-select"
        self.fields["left_destination"].widget.attrs["class"] = "qa-native-select"
        self.fields["right_destination"].widget.attrs["class"] = "qa-native-select"

        self.order_fields(
            [
                "amount",
                "source_currency",
                "left_destination",
                "right_destination",
                "duration_days",
                "travelers",
                *(
                    self.units_field_name(category)
                    for category, _label in _COMPARISON_CATEGORY_OPTIONS
                ),
            ]
        )

        if not self.is_bound:
            self.initial.setdefault("amount", "500")
            preferred_source = "EUR" if "EUR" in self._currency_by_code else ""
            if not preferred_source and self._currency_by_code:
                preferred_source = next(iter(self._currency_by_code))
            if preferred_source:
                self.initial.setdefault("source_currency", preferred_source)

    @property
    def reference_data_ready(self) -> bool:
        return bool(self._currency_by_code and len(self._destination_by_token) >= 2)

    @property
    def comparison_categories(self) -> tuple[str, ...]:
        return tuple(category for category, _label in _COMPARISON_CATEGORY_OPTIONS)

    def clean(self):
        cleaned = super().clean()

        source_code = str(cleaned.get("source_currency") or "").upper()
        source_currency = self._currency_by_code.get(source_code)
        raw_amount = cleaned.get("amount")
        if source_currency is not None and raw_amount is not None:
            cleaned["source_minor_units"] = source_currency.minor_units
            try:
                cleaned["amount_decimal"] = parse_amount_text(
                    str(raw_amount),
                    minor_units=source_currency.minor_units,
                )
            except forms.ValidationError as exc:
                self.add_error("amount", exc)

        for side in ("left", "right"):
            token = str(cleaned.get(f"{side}_destination") or "")
            destination = self._destination_by_token.get(token)
            if destination is None:
                continue
            country, city, currency = destination
            cleaned[f"{side}_destination_country"] = country.iso2
            cleaned[f"{side}_destination_city_slug"] = city.slug if city is not None else ""
            cleaned[f"{side}_destination_currency"] = currency.code
            cleaned[f"{side}_destination_minor_units"] = currency.minor_units
            cleaned[f"{side}_destination_name"] = (
                f"{city.name}, {country.name}" if city is not None else country.name
            )

        left_token = str(cleaned.get("left_destination") or "")
        right_token = str(cleaned.get("right_destination") or "")
        if left_token and right_token and left_token == right_token:
            self.add_error("right_destination", "Choose a different destination scope.")

        return cleaned


SERIES_PERIOD_CHOICES = (
    ("1y", "1Y"),
    ("5y", "5Y"),
    ("10y", "10Y"),
    ("custom", "Custom"),
)


def _subtract_years(value, years: int):
    try:
        return value.replace(year=value.year - years)
    except ValueError:
        return value.replace(year=value.year - years, month=2, day=28)


class HistoricalSeriesForm(forms.Form):
    base = forms.CharField(max_length=3)
    quote = forms.CharField(max_length=3)
    amount = forms.CharField(required=False, max_length=64)
    selected_date = forms.DateField()
    requested_date = forms.DateField(required=False)
    period = forms.ChoiceField(choices=SERIES_PERIOD_CHOICES, initial="1y")
    start_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    end_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))

    def clean(self):
        cleaned = super().clean()
        today = timezone.localdate()

        for field_name in ("base", "quote"):
            raw_value = cleaned.get(field_name)
            if not raw_value:
                continue
            try:
                cleaned[field_name] = normalize_currency_code(raw_value)
            except ValueError as exc:
                self.add_error(field_name, str(exc))

        base = cleaned.get("base")
        quote = cleaned.get("quote")

        raw_amount = cleaned.get("amount")
        if base and raw_amount:
            source_currency = Currency.objects.filter(code=base).only("minor_units").first()
            if source_currency is not None:
                try:
                    cleaned["amount_decimal"] = parse_amount_text(
                        raw_amount,
                        minor_units=source_currency.minor_units,
                    )
                except forms.ValidationError:
                    cleaned["comparison_amount_error"] = (
                        "Then & now comparison is unavailable because the amount is invalid."
                    )
            else:
                cleaned["comparison_amount_error"] = (
                    "Then & now comparison is unavailable because currency precision metadata "
                    "is missing."
                )

        if base and quote and base == quote:
            raise forms.ValidationError(
                "Historical trend is not shown for identical currencies because the rate is exactly 1:1."
            )

        selected_date = cleaned.get("selected_date")
        if selected_date and selected_date > today:
            self.add_error("selected_date", "Selected observation date cannot be in the future.")

        requested_date = cleaned.get("requested_date")
        if requested_date:
            if requested_date > today:
                self.add_error("requested_date", "Requested date cannot be in the future.")
            if selected_date and requested_date < selected_date:
                self.add_error(
                    "requested_date",
                    "Requested date cannot be before the selected observation date.",
                )

        period = cleaned.get("period")
        if selected_date and period in {"1y", "5y", "10y"}:
            years = {"1y": 1, "5y": 5, "10y": 10}[period]
            cleaned["start_date_resolved"] = _subtract_years(selected_date, years)
            cleaned["end_date_resolved"] = selected_date
        elif period == "custom":
            start_date = cleaned.get("start_date")
            end_date = cleaned.get("end_date")
            if start_date is None:
                self.add_error("start_date", "Choose a custom start date.")
            if end_date is None:
                self.add_error("end_date", "Choose a custom end date.")
            if start_date and end_date:
                if end_date < start_date:
                    self.add_error("end_date", "Custom end date cannot precede the start date.")
                if end_date > today:
                    self.add_error("end_date", "Custom end date cannot be in the future.")
                if selected_date and not start_date <= selected_date <= end_date:
                    self.add_error(
                        "selected_date",
                        "Custom range must include the selected observation date.",
                    )
                if not self.errors:
                    cleaned["start_date_resolved"] = start_date
                    cleaned["end_date_resolved"] = end_date

        if (
            cleaned.get("start_date_resolved")
            and cleaned.get("end_date_resolved")
            and (cleaned["end_date_resolved"] - cleaned["start_date_resolved"]).days > 10 * 366
        ):
            raise forms.ValidationError(
                str(RateSeriesRangeError("Historical trend range cannot exceed 10 years."))
            )

        return cleaned
