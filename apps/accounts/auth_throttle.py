"""Cache-backed, privacy-bounded authentication abuse controls.

Counter updates are atomic on Redis. Production requires a shared cache;
a missing cache must never silently disable authentication throttling.
"""

from __future__ import annotations

from django.core.cache import cache
from django.utils.crypto import salted_hmac

_WINDOW_SECONDS = 15 * 60
_LOGIN_USERNAME_LIMIT = 8
_LOGIN_CLIENT_LIMIT = 40
_SIGNUP_CLIENT_LIMIT = 12


class AuthThrottleUnavailable(Exception):
    """The shared throttle state could not be safely verified or updated."""


def _key(action: str, category: str, raw: str) -> str:
    normalized = raw.strip().casefold()[:254]
    digest = salted_hmac("ccc.auth-throttle.v1", normalized).hexdigest()
    return f"ccc:auth-guard:v1:{action}:{category}:{digest}"


def _client_address(remote_addr: str) -> str:
    # REMOTE_ADDR is provided by the trusted ASGI/WSGI server. Never accept
    # user-supplied X-Forwarded-For for throttling.
    return (remote_addr or "unknown-client").strip()[:128]


def _attempts(key: str) -> int:
    try:
        value = cache.get(key, 0)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise AuthThrottleUnavailable()
        return value
    except AuthThrottleUnavailable:
        raise
    except Exception:
        raise AuthThrottleUnavailable() from None


def _record(key: str) -> None:
    try:
        if not cache.add(key, 1, timeout=_WINDOW_SECONDS):
            cache.incr(key)
    except ValueError:
        # An expiring key can vanish between add() and incr(). Re-create it
        # with a bounded lifetime instead of accepting a bad counter state.
        try:
            if not cache.add(key, 1, timeout=_WINDOW_SECONDS):
                raise AuthThrottleUnavailable()
        except Exception:
            raise AuthThrottleUnavailable() from None
    except Exception:
        raise AuthThrottleUnavailable() from None


def _keys_login(username: str, remote_addr: str) -> tuple[str, str]:
    return (
        _key("login", "username", username),
        _key("login", "client", _client_address(remote_addr)),
    )


def login_allowed(*, username: str, remote_addr: str) -> bool:
    account_key, client_key = _keys_login(username, remote_addr)
    return (
        _attempts(account_key) < _LOGIN_USERNAME_LIMIT
        and _attempts(client_key) < _LOGIN_CLIENT_LIMIT
    )


def note_login_failure(*, username: str, remote_addr: str) -> None:
    account_key, client_key = _keys_login(username, remote_addr)
    _record(account_key)
    _record(client_key)


def note_login_success(*, username: str) -> None:
    # Keep client-level failures to protect against multi-account spraying.
    try:
        cache.delete(_key("login", "username", username))
    except Exception:
        raise AuthThrottleUnavailable() from None


def signup_allowed(*, remote_addr: str) -> bool:
    key = _key("signup", "client", _client_address(remote_addr))
    return _attempts(key) < _SIGNUP_CLIENT_LIMIT


def note_signup_attempt(*, remote_addr: str) -> None:
    _record(_key("signup", "client", _client_address(remote_addr)))
