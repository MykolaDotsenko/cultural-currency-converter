"""Origin-pinned HTTPS transport for untrusted public-data HTTP redirects.

Verifying response.geturl() is too late: urllib's default redirect handler has
already sent the next request. Check the target *before* following a Location
header, and reject caller-supplied initial URLs outside the pinned origin.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


def is_trusted_https_url(url: str, hostname: str) -> bool:
    try:
        parsed = urlsplit(url)
        return (
            parsed.scheme == "https"
            and parsed.hostname == hostname
            and parsed.port in (None, 443)
            and parsed.username is None
            and parsed.password is None
        )
    except (TypeError, ValueError):
        return False


class PinnedHTTPSRedirectHandler(HTTPRedirectHandler):
    def __init__(self, hostname: str):
        self.hostname = hostname

    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> Request | None:
        if not is_trusted_https_url(newurl, self.hostname):
            raise HTTPError(
                req.full_url,
                code,
                "Public-data redirect outside the pinned HTTPS origin",
                headers,
                fp,
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def make_pinned_https_urlopen(hostname: str) -> Callable[..., Any]:
    """Create an opener that cannot follow cross-origin/downgrade redirects."""
    opener = build_opener(PinnedHTTPSRedirectHandler(hostname))

    def open_request(request: Request, *, timeout: float) -> Any:
        if not is_trusted_https_url(request.full_url, hostname):
            raise HTTPError(
                request.full_url, 400, "Unexpected public-data request origin", None, None
            )
        return opener.open(request, timeout=timeout)

    return open_request
