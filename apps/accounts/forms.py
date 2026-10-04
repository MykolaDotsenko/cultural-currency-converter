from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from apps.accounts.models import NotificationPreference
from apps.countries.models import Currency

User = get_user_model()


class QuietAuthenticationForm(AuthenticationForm):
    def __init__(self, request=None, *args, **kwargs):
        super().__init__(*args, request=request, **kwargs)
        self.fields["username"].widget.attrs.pop("autofocus", None)
        self.fields["username"].widget.attrs.update(
            {"class": "qa-text-input", "autocomplete": "username"}
        )
        self.fields["password"].widget.attrs.update(
            {"class": "qa-text-input", "autocomplete": "current-password"}
        )


class SignUpForm(UserCreationForm):
    class Meta:
        model = User
        fields = ("username",)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.pop("autofocus", None)
        self.fields["username"].widget.attrs.update(
            {"class": "qa-text-input", "autocomplete": "username"}
        )
        self.fields["password1"].widget.attrs.update(
            {"class": "qa-text-input", "autocomplete": "new-password"}
        )
        self.fields["password2"].widget.attrs.update(
            {"class": "qa-text-input", "autocomplete": "new-password"}
        )


class HomeCurrencyPreferenceForm(forms.Form):
    home_currency = forms.ChoiceField(
        required=False,
        label="Home currency",
    )

    def __init__(self, *args, current_code: str = "", **kwargs):
        super().__init__(*args, **kwargs)
        currencies = list(Currency.objects.filter(is_active=True).order_by("code"))
        self._currency_by_code = {currency.code: currency for currency in currencies}
        self.fields["home_currency"].choices = [("", "No saved default")] + [
            (currency.code, f"{currency.name} · {currency.code}") for currency in currencies
        ]
        self.fields["home_currency"].widget.attrs["class"] = "qa-native-select"
        if not self.is_bound and current_code in self._currency_by_code:
            self.initial["home_currency"] = current_code

    def clean_home_currency(self):
        code = str(self.cleaned_data["home_currency"] or "").upper().strip()
        if code and code not in self._currency_by_code:
            raise forms.ValidationError("Choose an active currency.")
        return code


class PaymentFeeProfileNameForm(forms.Form):
    profile_name = forms.CharField(
        max_length=80,
        label="Profile name",
        widget=forms.TextInput(
            attrs={
                "class": "qa-text-input",
                "autocomplete": "off",
                "placeholder": "e.g. Travel card",
            }
        ),
    )

    def clean_profile_name(self):
        return " ".join(self.cleaned_data["profile_name"].split())


class BudgetPresetNameForm(forms.Form):
    preset_name = forms.CharField(
        max_length=80,
        label="Preset name",
        widget=forms.TextInput(
            attrs={
                "class": "qa-text-input",
                "autocomplete": "off",
                "placeholder": "e.g. Weekend city",
            }
        ),
    )

    def clean_preset_name(self):
        return " ".join(self.cleaned_data["preset_name"].split())


class PreTripNotificationPreferenceForm(forms.Form):
    enabled = forms.BooleanField(
        required=False,
        label="Enable pre-trip reminders",
        widget=forms.CheckboxInput(),
    )
    timezone_name = forms.CharField(
        max_length=64,
        label="Timezone",
        initial="UTC",
        widget=forms.TextInput(
            attrs={
                "class": "qa-text-input",
                "autocomplete": "off",
                "spellcheck": "false",
                "placeholder": "Europe/Helsinki",
            }
        ),
    )
    cadence = forms.ChoiceField(
        label="Cadence",
        choices=NotificationPreference.Cadence.choices,
        initial=NotificationPreference.Cadence.ONCE,
        widget=forms.Select(attrs={"class": "qa-native-select"}),
    )
    lead_days = forms.IntegerField(
        min_value=1,
        max_value=30,
        label="Remind me this many days before travel",
        initial=3,
        widget=forms.NumberInput(
            attrs={
                "class": "qa-text-input",
                "min": "1",
                "max": "30",
                "step": "1",
                "inputmode": "numeric",
            }
        ),
    )
    delivery_channel = forms.ChoiceField(
        label="Delivery",
        choices=NotificationPreference.DeliveryChannel.choices,
        initial=NotificationPreference.DeliveryChannel.IN_APP,
        widget=forms.Select(attrs={"class": "qa-native-select"}),
    )

    def __init__(
        self,
        *args,
        preference: NotificationPreference | None = None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        if not self.is_bound and preference is not None:
            self.initial.update(
                {
                    "enabled": preference.enabled,
                    "timezone_name": preference.timezone_name,
                    "cadence": preference.cadence,
                    "lead_days": preference.lead_days,
                    "delivery_channel": preference.delivery_channel,
                }
            )

    def clean_timezone_name(self):
        timezone_name = " ".join(self.cleaned_data["timezone_name"].split())
        try:
            ZoneInfo(timezone_name)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise forms.ValidationError(
                "Enter a valid IANA timezone, for example Europe/Helsinki."
            ) from exc
        return timezone_name


class DeleteAccountForm(forms.Form):
    password = forms.CharField(
        label="Current password",
        strip=False,
        widget=forms.PasswordInput(
            attrs={"class": "qa-text-input", "autocomplete": "current-password"}
        ),
    )

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_password(self):
        password = self.cleaned_data["password"]
        if not self.user.check_password(password):
            raise forms.ValidationError("The password is incorrect.")
        return password
