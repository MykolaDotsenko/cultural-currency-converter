from __future__ import annotations

from django.template.loader import render_to_string
from django.test import SimpleTestCase, override_settings

from apps.common.presentation.converter_preview import build_converter_preview_context


@override_settings(
    DEBUG=True,
    VITE_DEV_SERVER_ENABLED=True,
    VITE_DEV_SERVER_ORIGIN="http://127.0.0.1:5173",
)
class ConverterPrimitivePreviewTests(SimpleTestCase):
    def test_preview_renders_component_contract_without_claiming_live_fx(self) -> None:
        response = self.client.get("/_design/converter/")

        self.assertEqual(response.status_code, 200)
        html = response.content.decode()

        self.assertEqual(html.count("<h1"), 1)
        self.assertIn("Illustrative component data · not a rate quote.", html)
        self.assertNotIn(">LIVE<", html)
        self.assertIn('inputmode="decimal"', html)
        self.assertIn(
            'aria-describedby="preview-amount-currency preview-amount-message"',
            html,
        )
        self.assertIn('type="submit"', html)
        self.assertIn('aria-label="Swap source and destination"', html)
        self.assertIn('id="preview-source"', html)
        self.assertIn('id="preview-destination"', html)
        self.assertIn('aria-haspopup="dialog"', html)
        self.assertIn("<details", html)
        self.assertIn("Source details", html)

    def test_amount_error_retains_value_and_exposes_programmatic_error_state(self) -> None:
        response = self.client.get("/_design/converter/")
        html = response.content.decode()

        self.assertIn('value="abc"', html)
        self.assertIn('aria-invalid="true"', html)
        self.assertIn('id="preview-amount-error-message"', html)
        self.assertIn("Enter an amount such as 1234.56 or 1234,56.", html)

    def test_country_and_currency_identity_survives_without_media(self) -> None:
        response = self.client.get("/_design/converter/")
        html = response.content.decode()

        self.assertIn("Finland", html)
        self.assertIn("Euro · EUR", html)
        self.assertIn("Japan", html)
        self.assertIn("Japanese yen · JPY", html)
        self.assertIn("Finnish markka · FIM", html)
        self.assertIn('id="preview-historical-status"', html)
        self.assertIn(
            'aria-labelledby="preview-historical-label preview-historical-country '
            'preview-historical-currency preview-historical-status"',
            html,
        )
        self.assertIn(">Historical<", html)

    def test_bilateral_workspace_preserves_semantic_source_to_destination_order(self) -> None:
        response = self.client.get("/_design/converter/")
        html = response.content.decode()

        workspace_start = html.index('class="qa-workspace"')
        workspace_end = html.index("Illustrative layout fixture only.", workspace_start)
        workspace = html[workspace_start:workspace_end]

        self.assertLess(workspace.index(">From<"), workspace.index(">To<"))
        self.assertLess(
            workspace.index('id="workspace-source"'),
            workspace.index('id="workspace-destination"'),
        )
        self.assertIn('data-country-theme="fi"', workspace)
        self.assertIn('data-country-theme="jp"', workspace)
        self.assertIn('aria-live="polite"', workspace)
        self.assertIn('id="workspace-reference-result-title"', workspace)
        self.assertEqual(html.count('id="workspace-reference-result-title"'), 1)

    def test_bilateral_workspace_is_a_layout_fixture_not_business_behavior(self) -> None:
        response = self.client.get("/_design/converter/")
        html = response.content.decode()

        self.assertIn("PR2E validates composition and reflow", html)
        self.assertIn("FX behavior remains", html)
        self.assertNotIn("hx-post=", html)
        self.assertNotIn("hx-get=", html)

    def test_named_partial_loader_renders_status_badge_in_isolation(self) -> None:
        html = render_to_string(
            "components/converter/primitives.html#status-badge",
            {"component": {"kind": "cached", "label": "Cached"}},
        )

        self.assertIn("qa-status-badge--cached", html)
        self.assertIn(">Cached<", html)

    @override_settings(DEBUG=False)
    def test_preview_is_not_public_outside_debug(self) -> None:
        response = self.client.get("/_design/converter/")

        self.assertEqual(response.status_code, 404)


class ConverterPreviewContextTests(SimpleTestCase):
    def test_preview_context_marks_every_result_as_illustrative(self) -> None:
        context = build_converter_preview_context()

        self.assertIn("not a rate quote", str(context["preview_disclaimer"]).lower())
        self.assertEqual(context["reference_result"]["status"]["label"], "Reference rate")
        self.assertEqual(context["cached_result"]["status"]["label"], "Cached")
