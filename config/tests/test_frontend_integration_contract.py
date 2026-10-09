"""Structural coverage map for critical user-visible integration handoffs.

This deliberately complements (never replaces) rendered web and browser tests.
The map fails when a capability's route or template evidence hook disappears.
"""

from pathlib import Path

import pytest
from django.conf import settings
from django.template.loader import get_template
from django.urls import resolve, reverse


@pytest.mark.parametrize(
    ("route", "kwargs", "template", "evidence_hooks"),
    (
        (
            "converter",
            {},
            "components/converter/primitives.html",
            ("component.rate_meta", "component.smart_summary"),
        ),
        (
            "converter",
            {},
            "components/culture/destination_context.html",
            (
                "destination_context.prices",
                "destination_context.economic.inflation",
                "destination_context.economic.price_level",
                "destination_context.calendar.upcoming",
                "destination_context.payment.rows",
            ),
        ),
        (
            "converter",
            {},
            "components/converter/bilateral_value_lens.html",
            ("source_value_lens.prices", "destination_context_component.prices"),
        ),
        (
            "converter",
            {},
            "components/converter/money_studio.html",
            (
                "'destination_mode'",
                "'destination_comparison'",
                "'shopping_calculation'",
                "'explore'",
            ),
        ),
        (
            "converter",
            {},
            "components/converter/current_panel.html",
            ("money_studio_visible", "components/converter/money_studio.html"),
        ),
        (
            "shopping_calculation",
            {},
            "pages/shopping.html",
            ("product_context.name", "public_prices", "public_prices_message"),
        ),
        (
            "explore",
            {},
            "pages/explore.html",
            ("explore_destinations", "explore_ai_form", "reviewed"),
        ),
        (
            "country_money_profile",
            {"country_code": "JP"},
            "pages/country_money_profile.html",
            (
                "country_profile.payment",
                "country_profile.prices",
                "country_profile.economic.inflation",
                "country_profile.calendar.upcoming",
                "country_profile.converter_url",
                "country_profile.reviewed_cities",
            ),
        ),
        (
            "city_money_profile",
            {"country_code": "JP", "city_slug": "tokyo"},
            "pages/city_money_profile.html",
            ("city_profile.prices", "city_profile.payment", "city_profile.converter_url"),
        ),
        (
            "saved_scenario_detail",
            {"scenario_id": 1},
            "travel/saved_scenario_detail.html",
            ("trip_budget.remaining", "local_context.component"),
        ),
        (
            "money_culture_story",
            {},
            "pages/money_culture_story.html",
            ("story", "components/culture/story.html"),
        ),
        (
            "money_culture_story",
            {},
            "components/culture/story.html",
            ("chapter",),
        ),
        (
            "notification_inbox",
            {},
            "travel/notifications.html",
            ("notification",),
        ),
    ),
)
def test_critical_integration_capability_has_route_template_and_evidence_hook(
    route: str,
    kwargs: dict[str, str | int],
    template: str,
    evidence_hooks: tuple[str, ...],
) -> None:
    url = reverse(route, kwargs=kwargs)
    assert resolve(url).url_name == route
    compiled = get_template(template)
    assert compiled is not None

    source = (Path(settings.BASE_DIR) / "templates" / template).read_text(encoding="utf-8")
    for hook in evidence_hooks:
        assert hook in source, f"{route} lost frontend evidence hook {hook!r}"
