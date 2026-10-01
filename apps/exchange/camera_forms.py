from __future__ import annotations

from django import forms

from apps.countries.models import Currency
from apps.exchange.camera_media import MAX_CAMERA_UPLOAD_BYTES
from apps.exchange.forms import parse_amount_text


def _active_currency_choices() -> list[tuple[str, str]]:
    return [
        (currency.code, f"{currency.name} · {currency.code}")
        for currency in Currency.objects.filter(is_active=True).order_by("code")
    ]


class CameraUploadForm(forms.Form):
    image = forms.FileField(
        label="Photo or screenshot",
        widget=forms.ClearableFileInput(
            attrs={
                "class": "qa-camera-file-input",
                "accept": "image/jpeg,image/png,image/webp",
                "capture": "environment",
            }
        ),
    )
    expected_currency = forms.ChoiceField(
        required=False,
        label="Price currency hint",
    )
    target_currency = forms.ChoiceField(
        label="Convert to",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        choices = _active_currency_choices()
        self.fields["expected_currency"].choices = [("", "Not sure")] + choices
        self.fields["target_currency"].choices = choices
        self.fields["expected_currency"].widget.attrs["class"] = "qa-native-select"
        self.fields["target_currency"].widget.attrs["class"] = "qa-native-select"

    def add_error(self, field, error):
        super().add_error(field, error)
        if field and field in self.fields:
            self.fields[field].widget.attrs.update(
                {
                    "aria-invalid": "true",
                    "aria-describedby": f"{field}-error",
                }
            )

    def clean_image(self):
        uploaded = self.cleaned_data["image"]
        size = getattr(uploaded, "size", None)
        if not isinstance(size, int) or size <= 0:
            raise forms.ValidationError("Choose a non-empty image.")
        if size > MAX_CAMERA_UPLOAD_BYTES:
            raise forms.ValidationError("Image must be 6 MB or smaller.")
        return uploaded


class CameraConfirmForm(forms.Form):
    extraction_token = forms.CharField(widget=forms.HiddenInput())
    amount = forms.CharField(max_length=64, label="Detected amount")
    currency = forms.ChoiceField(label="Detected currency")
    target_currency = forms.ChoiceField(label="Convert to")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        currencies = list(Currency.objects.filter(is_active=True).order_by("code"))
        self._currency_by_code = {currency.code: currency for currency in currencies}
        choices = [(currency.code, f"{currency.name} · {currency.code}") for currency in currencies]
        self.fields["currency"].choices = choices
        self.fields["target_currency"].choices = choices
        self.fields["amount"].widget.attrs.update(
            {
                "class": "qa-text-input",
                "inputmode": "decimal",
                "autocomplete": "off",
            }
        )
        self.fields["currency"].widget.attrs["class"] = "qa-native-select"
        self.fields["target_currency"].widget.attrs["class"] = "qa-native-select"

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
        currency = self._currency_by_code.get(str(cleaned.get("currency") or "").upper())
        raw_amount = cleaned.get("amount")
        if currency is not None and raw_amount is not None:
            try:
                cleaned["amount_decimal"] = parse_amount_text(
                    str(raw_amount),
                    minor_units=currency.minor_units,
                )
            except forms.ValidationError as exc:
                self.add_error("amount", exc)
        return cleaned
