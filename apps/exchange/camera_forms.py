from __future__ import annotations

from django import forms

from apps.countries.models import Currency
from apps.exchange.forms import parse_amount_text

MAX_CAMERA_UPLOAD_BYTES = 6 * 1024 * 1024
_ALLOWED_CAMERA_MIME_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})


class CameraUploadForm(forms.Form):
    image = forms.FileField(label="Photo or screenshot")
    target_currency = forms.ChoiceField(label="Convert to")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        currencies = list(Currency.objects.filter(is_active=True).order_by("code"))
        self.fields["target_currency"].choices = [
            (currency.code, f"{currency.name} · {currency.code}") for currency in currencies
        ]
        self.fields["image"].widget.attrs.update(
            {
                "class": "qa-file-input",
                "accept": "image/jpeg,image/png,image/webp",
                "capture": "environment",
            }
        )
        self.fields["target_currency"].widget.attrs["class"] = "qa-native-select"

        if not self.is_bound:
            codes = {currency.code for currency in currencies}
            if "EUR" in codes:
                self.initial.setdefault("target_currency", "EUR")
            elif currencies:
                self.initial.setdefault("target_currency", currencies[0].code)

    def add_error(self, field, error):
        super().add_error(field, error)
        if field and field in self.fields:
            self.fields[field].widget.attrs.update(
                {
                    "aria-invalid": "true",
                    "aria-describedby": f"camera_{field}-error",
                }
            )

    def clean_image(self):
        uploaded = self.cleaned_data["image"]
        if uploaded.size > MAX_CAMERA_UPLOAD_BYTES:
            raise forms.ValidationError("Choose an image no larger than 6 MB.")
        content_type = str(getattr(uploaded, "content_type", "") or "").lower()
        if content_type not in _ALLOWED_CAMERA_MIME_TYPES:
            raise forms.ValidationError("Use a JPEG, PNG or WebP image.")
        return uploaded


class CameraConfirmForm(forms.Form):
    extraction_token = forms.CharField(widget=forms.HiddenInput())
    amount = forms.CharField(max_length=64, label="Amount")
    source_currency = forms.ChoiceField(label="Detected currency")
    target_currency = forms.ChoiceField(label="Convert to")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        currencies = list(Currency.objects.filter(is_active=True).order_by("code"))
        self._currency_by_code = {currency.code: currency for currency in currencies}
        choices = [("", "Choose currency")] + [
            (currency.code, f"{currency.name} · {currency.code}") for currency in currencies
        ]
        self.fields["source_currency"].choices = choices
        self.fields["target_currency"].choices = choices
        self.fields["amount"].widget.attrs.update(
            {
                "class": "qa-text-input",
                "inputmode": "decimal",
                "autocomplete": "off",
            }
        )
        self.fields["source_currency"].widget.attrs["class"] = "qa-native-select"
        self.fields["target_currency"].widget.attrs["class"] = "qa-native-select"

    def add_error(self, field, error):
        super().add_error(field, error)
        if field and field in self.fields:
            self.fields[field].widget.attrs.update(
                {
                    "aria-invalid": "true",
                    "aria-describedby": f"camera_confirm_{field}-error",
                }
            )

    def clean(self):
        cleaned = super().clean()
        source_code = str(cleaned.get("source_currency") or "").upper()
        target_code = str(cleaned.get("target_currency") or "").upper()
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

        if source_code and target_code and source_code == target_code:
            self.add_error("target_currency", "Choose a different currency to convert to.")

        return cleaned
