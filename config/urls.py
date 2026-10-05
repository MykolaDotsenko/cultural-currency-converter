"""URL configuration for Cultural Currency Converter."""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from apps.common.health import health_live, health_ready
from apps.common.security import csp_report
from apps.common.views import converter_preview, rate_series_preview, shell_preview
from apps.culture.views import (
    city_money_profile,
    current_destination_context,
    explore,
    explore_explanation,
    money_culture_story,
)
from apps.exchange.views import (
    budget_explanation,
    budget_interpretation,
    comparison_explanation,
    conversion_explanation,
    converter,
    destination_comparison,
    destination_mode,
    historical_series,
    payment_estimate,
    picker_options,
    same_amount_destinations,
    share_conversion_card,
    share_conversion_card_svg,
    shopping_calculation,
)
from apps.travel.camera_web import add_confirmed_camera_spend, camera_scan_saved_scenario
from apps.travel.offline_pack_web import download_offline_destination_pack
from apps.travel.scenario_web import (
    add_saved_scenario_spend,
    delete_saved_scenario,
    delete_saved_scenario_spend,
    recheck_saved_scenario,
    save_budget_scenario,
    save_shopping_scenario,
    saved_scenario_detail,
)
from apps.travel.views import (
    clear_favourites,
    clear_recent_conversions,
    clear_saved_places,
    delete_favourite,
    delete_recent_conversion,
    delete_saved_comparison,
    delete_saved_place,
    save_comparison,
    save_place,
    saved_places_status,
    saved_state,
    sync_favourites,
    sync_saved_places,
)

urlpatterns = [
    path("", converter, name="converter"),
    path("destination/", destination_mode, name="destination_mode"),
    path("compare/", destination_comparison, name="destination_comparison"),
    path("compare/explain/", comparison_explanation, name="comparison_explanation"),
    path(
        "explore/same-amount/",
        same_amount_destinations,
        name="same_amount_destinations",
    ),
    path("explore/", explore, name="explore"),
    path("explore/explain/", explore_explanation, name="explore_explanation"),
    path(
        "city/<str:country_code>/<slug:city_slug>/",
        city_money_profile,
        name="city_money_profile",
    ),
    path("picker/options/", picker_options, name="picker_options"),
    path("conversion/explain/", conversion_explanation, name="conversion_explanation"),
    path("shopping/", shopping_calculation, name="shopping_calculation"),
    path("share/conversion/", share_conversion_card, name="share_conversion_card"),
    path(
        "share/conversion/card.svg",
        share_conversion_card_svg,
        name="share_conversion_card_svg",
    ),
    path("payment/estimate/", payment_estimate, name="payment_estimate"),
    path("budget/interpret/", budget_interpretation, name="budget_interpretation"),
    path("budget/explain/", budget_explanation, name="budget_explanation"),
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
        "saved/scenarios/shopping/create/",
        save_shopping_scenario,
        name="save_shopping_scenario",
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
        "saved/scenarios/<int:scenario_id>/offline-pack/",
        download_offline_destination_pack,
        name="download_offline_destination_pack",
    ),
    path(
        "saved/scenarios/<int:scenario_id>/camera/",
        camera_scan_saved_scenario,
        name="camera_scan_saved_scenario",
    ),
    path(
        "saved/scenarios/<int:scenario_id>/camera/spend/add/",
        add_confirmed_camera_spend,
        name="add_confirmed_camera_spend",
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
    path("saved/places/sync/", sync_saved_places, name="sync_saved_places"),
    path("saved/places/create/", save_place, name="save_place"),
    path("saved/places/state/", saved_places_status, name="saved_places_status"),
    path(
        "saved/places/<int:place_id>/delete/",
        delete_saved_place,
        name="delete_saved_place",
    ),
    path("saved/places/clear/", clear_saved_places, name="clear_saved_places"),
    path("saved/comparisons/create/", save_comparison, name="save_comparison"),
    path(
        "saved/comparisons/<int:comparison_id>/delete/",
        delete_saved_comparison,
        name="delete_saved_comparison",
    ),
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
