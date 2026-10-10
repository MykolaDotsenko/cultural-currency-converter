from __future__ import annotations

from django.test import SimpleTestCase, override_settings


@override_settings(
    DEBUG=True,
    VITE_DEV_SERVER_ENABLED=True,
    VITE_DEV_SERVER_ORIGIN="http://127.0.0.1:5173",
)
class QuietAtlasShellPreviewTests(SimpleTestCase):
    def test_shell_preview_renders_semantic_landmarks_and_vite_entry(self) -> None:
        response = self.client.get("/_design/shell/")

        self.assertEqual(response.status_code, 200)
        html = response.content.decode()

        self.assertEqual(html.count("<h1"), 1)
        self.assertIn("<header", html)
        self.assertIn('<main id="main-content"', html)
        self.assertIn("<footer", html)
        self.assertIn('href="#main-content">Skip to content</a>', html)
        self.assertIn("http://127.0.0.1:5173/@vite/client", html)
        self.assertIn("http://127.0.0.1:5173/frontend/src/app.ts", html)

    def test_shell_preview_exposes_bilateral_context_without_controls(self) -> None:
        response = self.client.get("/_design/shell/")

        self.assertContains(response, 'data-country-theme="fi"')
        self.assertContains(response, 'data-country-theme="jp"')
        self.assertContains(response, "Finland")
        self.assertContains(response, "Euro · EUR")
        self.assertContains(response, "Japan")
        self.assertContains(response, "Japanese yen · JPY")
        self.assertNotContains(response, "<form")
        self.assertNotContains(response, 'id="converter-panel"')

    @override_settings(DEBUG=False)
    def test_shell_preview_is_not_public_outside_debug(self) -> None:
        response = self.client.get("/_design/shell/")

        self.assertEqual(response.status_code, 404)

    def test_global_navigation_is_reachable_on_foundation_preview(self) -> None:
        response = self.client.get("/_design/shell/")
        html = response.content.decode()

        self.assertEqual(html.count('aria-label="Primary navigation"'), 1)
        self.assertIn('aria-label="Cultural Currency — open converter"', html)
        for path in ("/", "/destination/", "/compare/", "/explore/", "/saved/"):
            self.assertIn(f'href="{path}"', html)
        for label in ("Convert", "Plan", "Compare", "Explore", "Saved"):
            self.assertIn(f">{label}</a>", html)
        self.assertNotIn("header_actions", html)
