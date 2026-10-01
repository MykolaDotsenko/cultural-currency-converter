from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import uuid4

from django import forms

from apps.exchange.camera import (
    MAX_CAMERA_UPLOAD_BYTES,
    CameraTokenError,
    load_camera_candidate_token,
    load_confirmed_camera_amount_token,
)
from apps.exchange.forms import parse_amount_text


def camera_scope_for_scenario(scenario_id: int) -> str:
    return f"saved-scenario:{scenario_id}"


class CameraUploadForm(forms.Form):
    image = forms.FileField(
        label="Photo or screenshot",
        widget=forms.ClearableFileInput(
            attrs={
                "accept": "image/jpeg,image/png,image/webp",
                "capture": "environment",
                "class": "qa-file-input",
            }
        ),
    )

    def clean_image(self):
        image = self.cleaned_data["image"]
        if image.size <= 0:
            raise forms.ValidationError("Choose an image to scan.")
        if image.size > MAX_CAMERA_UPLOAD_BYTES:
            raise forms.ValidationError("Image is too large. Use an image up to 8 MiB.")

        content_type = str(getattr(image, "content_type", "") or "").split(";", 1)[0].lower()
        if content_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise forms.ValidationError("Use a JPEG, PNG or WebP image.")
        return image


class CameraCandidateConfirmationForm(forms.Form):
    candidate_token = forms.CharField(widget=forms.HiddenInput())
    amount = forms.CharField(
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
        *args: Any,
        scenario_id: int,
        destination_currency_code: str,
        destination_minor_units: int,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.scope = camera_scope_for_scenario(scenario_id)
        self.destination_currency_code = destination_currency_code.upper()
        self.destination_minor_units = destination_minor_units
        self.fields["amount"].label = f"Confirm amount in {self.destination_currency_code}"

    def add_error(self, field: str | None, error: Any) -> None:
        super().add_error(field, error)
        if field == "amount":
            self.fields["amount"].widget.attrs.update(
                {
                    "aria-invalid": "true",
                    "aria-describedby": "camera_amount-error",
                }
            )

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean() or {}
        token = cleaned.get("candidate_token")
        if not token:
            return cleaned

        try:
            snapshot = load_camera_candidate_token(
                str(token),
                expected_scope=self.scope,
            )
        except CameraTokenError as exc:
            raise forms.ValidationError(str(exc)) from exc

        if snapshot.currency_code and snapshot.currency_code != self.destination_currency_code:
            raise forms.ValidationError(
                f"The image appears to use {snapshot.currency_code}, but this saved trip uses "
                f"{self.destination_currency_code}. Scan a matching price or add the spend manually."
            )

        raw = cleaned.get("amount")
        if raw is None or self.has_error("amount"):
            return cleaned
        try:
            amount = parse_amount_text(
                str(raw),
                minor_units=self.destination_minor_units,
            )
        except forms.ValidationError as exc:
            self.add_error("amount", exc)
            return cleaned

        if amount <= Decimal("0"):
            self.add_error("amount", "Enter an amount greater than zero.")
            return cleaned

        cleaned["candidate_snapshot"] = snapshot
        cleaned["confirmed_amount"] = amount
        return cleaned


class CameraSpendHandoffForm(forms.Form):
    """Consume a signed confirmed camera amount without trusting a posted amount."""

    confirmed_camera_token = forms.CharField(widget=forms.HiddenInput())
    submission_key = forms.UUIDField(widget=forms.HiddenInput())

    def __init__(
        self,
        *args: Any,
        scenario_id: int,
        destination_currency_code: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.scope = camera_scope_for_scenario(scenario_id)
        self.destination_currency_code = destination_currency_code.upper().strip()
        if not self.is_bound:
            self.fields["submission_key"].initial = uuid4()

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean() or {}
        token = cleaned.get("confirmed_camera_token")
        if not token:
            return cleaned

        try:
            snapshot = load_confirmed_camera_amount_token(
                str(token),
                expected_scope=self.scope,
            )
        except CameraTokenError as exc:
            raise forms.ValidationError(str(exc)) from exc

        if snapshot.currency_code != self.destination_currency_code:
            raise forms.ValidationError(
                f"The confirmed camera amount uses {snapshot.currency_code}, but this saved trip "
                f"uses {self.destination_currency_code}."
            )

        cleaned["confirmed_snapshot"] = snapshot
        return cleaned

