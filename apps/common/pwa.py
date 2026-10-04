from __future__ import annotations

import json

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.templatetags.static import static
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.http import require_GET


_PWA_THEME_COLOR = "#f5f2eb"
_PWA_BACKGROUND_COLOR = "#f5f2eb"


@require_GET
def web_app_manifest(request: HttpRequest) -> HttpResponse:
    """Return a stable same-origin install manifest with no user-specific state."""

    payload = {
        "id": "/",
        "name": "Cultural Currency Converter",
        "short_name": "Cultural Currency",
        "description": "Reference currency conversion with reviewed local money context.",
        "start_url": reverse("converter"),
        "scope": "/",
        "display": "standalone",
        "background_color": _PWA_BACKGROUND_COLOR,
        "theme_color": _PWA_THEME_COLOR,
        "icons": [
            {
                "src": static("pwa/icon-192.png"),
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "any",
            },
            {
                "src": static("pwa/icon-512.png"),
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any maskable",
            },
        ],
        "shortcuts": [
            {
                "name": "Convert",
                "short_name": "Convert",
                "url": reverse("converter"),
            },
            {
                "name": "Explore",
                "short_name": "Explore",
                "url": reverse("explore"),
            },
        ],
    }
    response = HttpResponse(
        json.dumps(payload, separators=(",", ":"), ensure_ascii=True),
        content_type="application/manifest+json",
    )
    response["Cache-Control"] = "public, max-age=3600"
    return response


@require_GET
def service_worker(request: HttpRequest) -> HttpResponse:
    """Serve the root-scoped service worker without routing it through static storage."""

    body = render_to_string(
        "pwa/service_worker.js",
        {
            "offline_url": reverse("offline_shell"),
            "static_url": settings.STATIC_URL,
        },
        request=request,
    )
    response = HttpResponse(body, content_type="text/javascript; charset=utf-8")
    response["Cache-Control"] = "no-cache"
    response["Service-Worker-Allowed"] = "/"
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response


@require_GET
def offline_shell(request: HttpRequest) -> HttpResponse:
    """Return a public, generic offline shell that intentionally contains no account data."""

    response = render(request, "pwa/offline.html")
    response["Cache-Control"] = "public, max-age=300"
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response
