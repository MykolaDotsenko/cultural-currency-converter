"""URL configuration for Cultural Currency Converter."""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from apps.common.health import health_live, health_ready
from apps.common.security import csp_report
from apps.common.views import converter_preview, rate_series_preview, shell_preview
from apps.culture.views import current_destination_context, money_culture_story
from apps.exchange.views import (
    budget_interpretation,
    conversion_explanation,
    converter,
    destination_comparison,
    destination_mode,
    historical_series,
    payment_estimate,
    picker_options,
)
from apps.travel.scenario_web import (
    add_saved_scenario_spend,
    delete_saved_scenario,
    delete_saved_scenario_spend,
    recheck_saved_scenario,
    save_budget_scenario,
    saved_scenario_detail,
)
from apps.travel.views import (
    clear_favourites,
    clear_recent_conversions,
    delete_favourite,
    delete_recent_conversion,
    saved_state,
    sync_favourites,
)

urlpatterns = [
    path("", converter, name="converter"),
    path("destination/", destination_mode, name="destination_mode"),
    path("compare/", destination_comparison, name="destination_comparison"),
    path("picker/options/", picker_options, name="picker_options"),
    path("conversion/explain/", conversion_explanation, name="conversion_explanation"),
    path("payment/estimate/", payment_estimate, name="payment_estimate"),
    path("budget/interpret/", budget_interpretation, name="budget_interpretation"),
    path("story/", money_culture_story, name="money_culture_story"),
    path(
        "destination/current-context/",
        current_destination_context,
        name="current_destination_context",
    ),
    path("historical/series/", historical_series, name="historical_series"),
    path("saved/", saved_state, name="saved_state"),
    path(
        "saved/scenarios/budget/create/",
        save_budget_scenario,
        name="save_budget_scenario",
    ),
    path(
        "saved/scenarios/<int:scenario_id>/",
        saved_scenario_detail,
        name="saved_scenario_detail",
    ),
    path(
        "saved/scenarios/<int:scenario_id>/recheck/",
        recheck_saved_scenario,
        name="recheck_saved_scenario",
    ),
    path(
        "saved/scenarios/<int:scenario_id>/spend/add/",
        add_saved_scenario_spend,
        name="add_saved_scenario_spend",
    ),
    path(
        "saved/scenarios/<int:scenario_id>/spend/<int:entry_id>/delete/",
        delete_saved_scenario_spend,
        name="delete_saved_scenario_spend",
    ),
    path(
        "saved/scenarios/<int:scenario_id>/delete/",
        delete_saved_scenario,
        name="delete_saved_scenario",
    ),
    path("saved/favourites/sync/", sync_favourites, name="sync_favourites"),
    path(
        "saved/favourites/<int:favourite_id>/delete/",
        delete_favourite,
        name="delete_favourite",
    ),
    path("saved/favourites/clear/", clear_favourites, name="clear_favourites"),
    path(
        "saved/history/<int:recent_id>/delete/",
        delete_recent_conversion,
        name="delete_recent_conversion",
    ),
    path(
        "saved/history/clear/",
        clear_recent_conversions,
        name="clear_recent_conversions",
    ),
    path("accounts/", include("apps.accounts.urls")),
    path("health/live/", health_live, name="health_live"),
    path("health/ready/", health_ready, name="health_ready"),
    path("security/csp-report/", csp_report, name="csp_report"),
    path("admin/", admin.site.urls),
    path("_design/shell/", shell_preview, name="shell_preview"),
    path("_design/converter/", converter_preview, name="converter_preview"),
    path("_design/rate-series/", rate_series_preview, name="rate_series_preview"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
