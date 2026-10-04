from __future__ import annotations

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

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
