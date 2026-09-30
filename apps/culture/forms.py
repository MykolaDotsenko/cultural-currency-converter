from __future__ import annotations

from decimal import Decimal

from django import forms
from django.utils import timezone

from apps.countries.models import Country, Currency
from apps.culture.story import CurrencyHistoryRequest, StoryRequest


class StoryRequestForm(forms.Form):
    source_country = forms.CharField(required=False, max_length=2)
    source_currency = forms.CharField(required=False, max_length=3)
    destination_country = forms.CharField(required=False, max_length=2)
    destination_currency = forms.CharField(required=False, max_length=3)
    selected_date = forms.DateField()
    historical = forms.ChoiceField(choices=(("0", "Current"), ("1", "Historical")))

    def clean(self):
        cleaned = super().clean()
        if self.errors:
            return cleaned

        for field_name in ("source_country", "destination_country"):
            code = str(cleaned.get(field_name) or "").upper()
            cleaned[field_name] = code
            if code and not Country.objects.filter(iso2=code).exists():
                self.add_error(field_name, "Unknown country code.")

        for field_name in ("source_currency", "destination_currency"):
            code = str(cleaned.get(field_name) or "").upper()
            cleaned[field_name] = code
            if code and not Currency.objects.filter(code=code).exists():
                self.add_error(field_name, "Unknown currency code.")

        if cleaned["selected_date"] > timezone.localdate():
            self.add_error("selected_date", "Story date cannot be in the future.")

        if cleaned.get("historical") == "0":
            cleaned["selected_date"] = timezone.localdate()

        if not any(
            cleaned.get(field)
            for field in (
                "source_country",
                "source_currency",
                "destination_country",
                "destination_currency",
            )
        ):
            raise forms.ValidationError("Story context requires a country or currency.")

        return cleaned

    def to_story_request(self) -> StoryRequest:
        if not self.is_valid():
            raise ValueError("StoryRequestForm must be valid before conversion.")
        return StoryRequest(
            source_country=self.cleaned_data["source_country"],
            source_currency=self.cleaned_data["source_currency"],
            destination_country=self.cleaned_data["destination_country"],
            destination_currency=self.cleaned_data["destination_currency"],
            selected_date=self.cleaned_data["selected_date"],
            historical=self.cleaned_data["historical"] == "1",
        )


class CurrencyHistoryRequestForm(forms.Form):
    country = forms.CharField(max_length=2)
    currency = forms.CharField(max_length=3)
    selected_date = forms.DateField(required=False)
    historical = forms.ChoiceField(
        required=False,
        choices=(("0", "Current"), ("1", "Historical")),
        initial="0",
    )

    def clean(self):
        cleaned = super().clean()
        if self.errors:
            return cleaned

        country_code = str(cleaned.get("country") or "").upper()
        currency_code = str(cleaned.get("currency") or "").upper()
        cleaned["country"] = country_code
        cleaned["currency"] = currency_code

        if not Country.objects.filter(iso2=country_code).exists():
            self.add_error("country", "Unknown country code.")
        if not Currency.objects.filter(code=currency_code).exists():
            self.add_error("currency", "Unknown currency code.")

        historical = cleaned.get("historical") == "1"
        selected_date = cleaned.get("selected_date")
        today = timezone.localdate()
        if historical:
            if selected_date is None:
                self.add_error("selected_date", "Choose a historical date.")
            elif selected_date > today:
                self.add_error("selected_date", "Currency history date cannot be in the future.")
        else:
            cleaned["selected_date"] = today

        return cleaned

    def to_currency_history_request(self) -> CurrencyHistoryRequest:
        if not self.is_valid():
            raise ValueError("CurrencyHistoryRequestForm must be valid before conversion.")
        return CurrencyHistoryRequest(
            country_code=self.cleaned_data["country"],
            currency_code=self.cleaned_data["currency"],
            selected_date=self.cleaned_data["selected_date"],
            historical=self.cleaned_data.get("historical") == "1",
        )


class CurrentDestinationContextForm(forms.Form):
    country = forms.CharField(max_length=2)
    currency = forms.CharField(max_length=3)
    amount = forms.DecimalField(
        min_value=Decimal("0"),
        max_digits=40,
        decimal_places=12,
    )

    def clean(self):
        cleaned = super().clean()
        if self.errors:
            return cleaned

        country_code = str(cleaned.get("country") or "").upper()
        currency_code = str(cleaned.get("currency") or "").upper()
        cleaned["country"] = country_code
        cleaned["currency"] = currency_code

        if not Country.objects.filter(iso2=country_code, is_active=True).exists():
            self.add_error("country", "Unknown or inactive destination country.")
        if not Currency.objects.filter(code=currency_code).exists():
            self.add_error("currency", "Unknown destination currency.")

        return cleaned
