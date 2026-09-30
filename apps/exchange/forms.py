from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from django import forms
from django.utils import timezone

from apps.countries.models import Country, CountryCurrency, Currency
from apps.exchange.domain import RateSeriesRangeError, normalize_currency_code
from apps.exchange.payment_estimate import MAX_FX_MARKUP_PERCENT

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
        return cleaned

    @property
    def historical_mode(self) -> bool:
        if self.is_bound:
            return self.data.get("rate_mode") == RATE_MODE_HISTORICAL
        return self.initial.get("rate_mode") == RATE_MODE_HISTORICAL

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
                "max": format(MAX_FX_MARKUP_PERCENT, "f"),
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
        self.fields["destination_fixed_fee"].label = (
            f"Fixed local fee in {destination_currency_code}"
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
