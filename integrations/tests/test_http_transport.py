from __future__ import annotations

from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request

import pytest

from integrations.http_transport import (
    PinnedHTTPSRedirectHandler,
    is_trusted_https_url,
    make_pinned_https_urlopen,
)


@pytest.mark.parametrize(
    "url",
    [
        "http://prices.openfoodfacts.org/api/v1/prices",
        "https://127.0.0.1/latest",
        "https://169.254.169.254/latest/meta-data",
        "https://prices.openfoodfacts.org.evil.example/redirect",
        "https://prices.openfoodfacts.org:8443/api/v1/prices",
        "https://user@prices.openfoodfacts.org/api/v1/prices",
        "https://prices.openfoodfacts.org@evil.example/api/v1/prices",
        "https://prices.openfoodfacts.org:invalid/api/v1/prices",
        "//prices.openfoodfacts.org/api/v1/prices",
    ],
)
def test_off_origin_or_downgraded_urls_are_rejected_before_followup(url):
    assert not is_trusted_https_url(url, "prices.openfoodfacts.org")
    handler = PinnedHTTPSRedirectHandler("prices.openfoodfacts.org")
    request = Request("https://prices.openfoodfacts.org/api/v1/prices")
    with pytest.raises(HTTPError, match="outside the pinned HTTPS origin"):
        handler.redirect_request(request, None, 302, "Found", {}, url)


def test_same_origin_https_redirect_is_still_supported():
    handler = PinnedHTTPSRedirectHandler("prices.openfoodfacts.org")
    request = Request("https://prices.openfoodfacts.org/api/v1/prices")
    followed = handler.redirect_request(
        request,
        None,
        302,
        "Found",
        {},
        "https://prices.openfoodfacts.org/api/v1/prices/?page=1",
    )
    assert followed is not None
    assert followed.full_url == "https://prices.openfoodfacts.org/api/v1/prices/?page=1"


def test_initial_url_is_guarded_before_opener_can_make_network_request():
    fake_opener = Mock()
    with patch("integrations.http_transport.build_opener", return_value=fake_opener):
        safe_open = make_pinned_https_urlopen("world.openfoodfacts.org")
    with pytest.raises(HTTPError, match="Unexpected public-data request origin"):
        safe_open(Request("https://example.org/private"), timeout=5)
    fake_opener.open.assert_not_called()

    expected = Request("https://world.openfoodfacts.org/api/v3.6/product/12345678.json")
    safe_open(expected, timeout=6)
    fake_opener.open.assert_called_once_with(expected, timeout=6)


def test_untrusted_final_provider_url_can_be_detected_defensively():
    assert is_trusted_https_url(
        "https://world.openfoodfacts.org/api/v3.6/product/12345678.json",
        "world.openfoodfacts.org",
    )
    assert not is_trusted_https_url(
        "https://world.openbeautyfacts.org/api/v3.6/product/12345678.json",
        "world.openfoodfacts.org",
    )
