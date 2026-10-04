from django.contrib.auth.views import LoginView, LogoutView
from django.urls import path

from apps.accounts.forms import QuietAuthenticationForm
from apps.accounts.views import (
    delete_account,
    delete_budget_preset_view,
    delete_fee_profile,
    profile,
    signup,
    update_home_currency_preference,
    update_recent_history_preference,
)

urlpatterns = [
    path(
        "login/",
        LoginView.as_view(
            template_name="accounts/login.html",
            authentication_form=QuietAuthenticationForm,
            redirect_authenticated_user=True,
        ),
        name="login",
    ),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("signup/", signup, name="signup"),
    path("profile/", profile, name="profile"),
    path(
        "home-currency/",
        update_home_currency_preference,
        name="update_home_currency_preference",
    ),
    path(
        "recent-history/",
        update_recent_history_preference,
        name="update_recent_history_preference",
    ),
    path(
        "fee-profiles/<int:profile_id>/delete/",
        delete_fee_profile,
        name="delete_fee_profile",
    ),
    path(
        "budget-presets/<int:preset_id>/delete/",
        delete_budget_preset_view,
        name="delete_budget_preset",
    ),
    path("delete/", delete_account, name="delete_account"),
]
