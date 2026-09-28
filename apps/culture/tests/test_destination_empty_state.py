from __future__ import annotations

from django.template.loader import render_to_string
from django.test import SimpleTestCase


class DestinationContextEmptyTemplateTests(SimpleTestCase):
    def test_selected_country_explains_review_gate_without_placeholder_content(self):
        html = render_to_string(
            "components/culture/destination_context_empty.html",
            {
                "destination": {
                    "country_code": "FI",
                    "country_name": "Finland",
                }
            },
        )

        self.assertIn("Finland context is being reviewed.", html)
        self.assertIn("source and freshness review", html)
        self.assertIn("no provisional guidance is shown here", html)
        self.assertNotIn("still being curated", html)

    def test_currency_only_state_invites_country_context_without_questioning_conversion(self):
        html = render_to_string(
            "components/culture/destination_context_empty.html",
            {
                "destination": {
                    "country_code": "",
                    "country_name": "No country context",
                }
            },
        )

        self.assertIn("Choose a destination country to add local meaning.", html)
        self.assertIn("Your currency conversion is complete.", html)
        self.assertIn("reviewed local", html)
        self.assertNotIn("Destination context is still being curated", html)
