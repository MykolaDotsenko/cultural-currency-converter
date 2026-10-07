"""URL configuration for Cultural Currency Converter."""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from apps.common.health import health_live, health_ready
from apps.common.pwa import offline_shell, service_worker, web_app_manifest
from apps.common.security import csp_report
from apps.common.views import converter_preview, rate_series_preview, shell_preview
from apps.culture.views import (
    city_money_profile,
    current_destination_context,
    explore,
    explore_explanation,
    money_culture_story,
)
from apps.exchange.api_v1 import api_v1_conversion, api_v1_reference, api_v1_root
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
from apps.travel.notification_web import (
    configure_saved_scenario_notification,
    delete_saved_scenario_notification,
    mark_all_notifications_read,
    mark_notification_read,
    notification_inbox,
)
from apps.travel.offline_pack_web import download_offline_destination_pack, offline_trip_snapshot
from apps.travel.share_web import scenario_share_card, scenario_share_card_svg
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
    clear_saved_currencies,
    clear_saved_places,
    delete_favourite,
    delete_recent_conversion,
    delete_saved_comparison,
    delete_saved_currency,
    delete_saved_place,
    save_comparison,
    save_currency,
    save_place,
    saved_currencies_status,
    saved_currency_options,
    saved_places_status,
    saved_state,
    sync_favourites,
    sync_saved_currencies,
    sync_saved_places,
)

urlpatterns = [
    path("api/v1/", api_v1_root, name="api_v1_root"),
    path("api/v1/reference/", api_v1_reference, name="api_v1_reference"),
    path("api/v1/conversions/", api_v1_conversion, name="api_v1_conversion"),
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
    path("share/conversion/", share_conversion_card, name="share_conversion_card"),
    path("share/travel/", scenario_share_card, name="share_scenario_card"),
    path("share/travel/card.svg", scenario_share_card_svg, name="share_scenario_card_svg"),
    path(
        "share/conversion/card.svg",
        share_conversion_card_svg,
        name="share_conversion_card_svg",
    ),
    path("shopping/", shopping_calculation, name="shopping_calculation"),
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
    path("saved/notifications/", notification_inbox, name="notification_inbox"),
    path(
        "saved/notifications/read-all/",
        mark_all_notifications_read,
        name="mark_all_notifications_read",
    ),
    path(
        "saved/notifications/<int:delivery_id>/read/",
        mark_notification_read,
        name="mark_notification_read",
    ),
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
        "saved/scenarios/<int:scenario_id>/notifications/configure/",
        configure_saved_scenario_notification,
        name="configure_saved_scenario_notification",
    ),
    path(
        "saved/scenarios/<int:scenario_id>/notifications/<str:notification_type>/delete/",
        delete_saved_scenario_notification,
        name="delete_saved_scenario_notification",
    ),
    path(
        "saved/scenarios/<int:scenario_id>/offline-pack/",
        download_offline_destination_pack,
        name="download_offline_destination_pack",
    ),
    path(
        "saved/scenarios/<int:scenario_id>/offline-snapshot/",
        offline_trip_snapshot,
        name="offline_trip_snapshot",
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
    path("saved/currencies/options/", saved_currency_options, name="saved_currency_options"),
    path("saved/currencies/state/", saved_currencies_status, name="saved_currencies_status"),
    path("saved/currencies/sync/", sync_saved_currencies, name="sync_saved_currencies"),
    path("saved/currencies/create/", save_currency, name="save_currency"),
    path(
        "saved/currencies/<int:currency_id>/delete/",
        delete_saved_currency,
        name="delete_saved_currency",
    ),
    path("saved/currencies/clear/", clear_saved_currencies, name="clear_saved_currencies"),
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
    path("manifest.webmanifest", web_app_manifest, name="web_app_manifest"),
    path("service-worker.js", service_worker, name="service_worker"),
    path("offline/", offline_shell, name="offline_shell"),
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
