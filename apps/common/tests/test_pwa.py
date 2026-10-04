from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase
from django.urls import reverse
from PIL import Image


class PwaSurfaceTests(SimpleTestCase):
    def test_manifest_is_public_stable_and_installable(self) -> None:
        response = self.client.get(reverse("web_app_manifest"))

        assert response.status_code == 200
        assert response["Content-Type"].startswith("application/manifest+json")
        assert response["Cache-Control"] == "public, max-age=3600"

        payload = json.loads(response.content)
        assert payload["id"] == "/"
        assert payload["start_url"] == "/"
        assert payload["scope"] == "/"
        assert payload["display"] == "standalone"
        assert payload["theme_color"] == "#f5f2eb"
        assert [icon["sizes"] for icon in payload["icons"]] == ["192x192", "512x512"]
        assert payload["icons"][1]["purpose"] == "any maskable"
        assert {shortcut["url"] for shortcut in payload["shortcuts"]} == {"/", "/explore/"}
        assert "saved" not in response.content.decode("utf-8").lower()

    def test_service_worker_is_root_scoped_and_never_caches_navigation_html(self) -> None:
        response = self.client.get(reverse("service_worker"))

        assert response.status_code == 200
        assert response["Content-Type"].startswith("text/javascript")
        assert response["Service-Worker-Allowed"] == "/"
        assert response["Cache-Control"] == "no-cache"

        source = response.content.decode("utf-8")
        assert 'request.mode === "navigate"' in source
        assert "fetch(request).catch(() => caches.match(OFFLINE_URL))" in source
        assert "cache.put(request, response.clone())" in source
        assert "isPublicStaticPath(url)" in source
        assert "/saved/" not in source
        assert "/accounts/" not in source
        assert "/admin/" not in source

    def test_offline_shell_is_generic_self_contained_and_privacy_explicit(self) -> None:
        response = self.client.get(reverse("offline_shell"))

        assert response.status_code == 200
        assert response["Cache-Control"] == "public, max-age=300"
        assert response["X-Robots-Tag"] == "noindex, nofollow"

        html = response.content.decode("utf-8")
        normalized = " ".join(html.split())
        assert "You’re offline." in normalized
        assert (
            "Private account pages and saved-scenario HTML are never cached automatically."
            in normalized
        )
        assert "Offline Destination Pack" in normalized
        assert "<script" not in html.lower()
        assert 'rel="stylesheet"' not in html.lower()

    def test_pwa_icons_are_real_pngs_with_required_dimensions(self) -> None:
        for size in (192, 512):
            path = Path(settings.BASE_DIR) / "static" / "pwa" / f"icon-{size}.png"
            assert path.is_file()
            with Image.open(path) as image:
                assert image.format == "PNG"
                assert image.size == (size, size)
