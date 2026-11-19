"""HTTP hardening of the local server (docs/diseno.md, section 8).

Who may talk to the server is decided here, before any route runs:

- `Host` must be `127.0.0.1:<port>` or `localhost:<port>` (DNS rebinding).
- `Origin`, when present, must be one of those two origins, and every request
  that changes state must carry it (CSRF from another site).
- Every `/api` request except the token exchange needs the session cookie
  (401) and the CSRF header (403). Both are compared in constant time.

The startup token travels only in the URL fragment, which the browser never
sends. The page posts it once in the body of `POST /api/session` and receives
the `HttpOnly`, `SameSite=Strict` session cookie and the CSRF token. After that
first exchange the startup token is forgotten and can never be used again.
"""

from __future__ import annotations

import hmac
import secrets
import threading
from typing import Final

TOKEN_BYTES: Final = 32  # 256 bits
SESSION_COOKIE: Final = "pvlt_session"
CSRF_HEADER: Final = "x-csrf-token"

SAFE_METHODS: Final = frozenset({"GET", "HEAD", "OPTIONS"})

# Every response carries these. `frame-ancestors 'none'` and X-Frame-Options stop
# the page from loading inside a frame. CORP keeps other sites from embedding
# the JSON responses. There is deliberately no CORS header at all.
SECURITY_HEADERS: Final[dict[str, str]] = {
    "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'",
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Cross-Origin-Resource-Policy": "same-origin",
}


def new_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def _matches(given: str | None, expected: str | None) -> bool:
    if given is None or expected is None:
        return False
    return hmac.compare_digest(given.encode("utf-8"), expected.encode("utf-8"))


class Guard:
    """Startup token, session cookie and CSRF token of the single local user."""

    def __init__(self, port: int, startup_token: str) -> None:
        self.allowed_hosts: Final = frozenset({f"127.0.0.1:{port}", f"localhost:{port}"})
        self.allowed_origins: Final = frozenset(f"http://{h}" for h in self.allowed_hosts)
        self._startup_token: str | None = startup_token
        self._session: str | None = None
        self._csrf: str | None = None
        self._mutex = threading.Lock()

    def __repr__(self) -> str:
        return f"Guard(redeemed={self._startup_token is None})"

    def host_allowed(self, host: str | None) -> bool:
        return host is not None and host in self.allowed_hosts

    def origin_allowed(self, origin: str | None, method: str) -> bool:
        """A foreign Origin is always refused. A missing one only on safe methods."""
        if origin is None:
            return method in SAFE_METHODS
        return origin in self.allowed_origins

    def redeem(self, token: str) -> tuple[str, str] | None:
        """Exchange the startup token for (session, csrf). Works exactly once."""
        with self._mutex:
            if not _matches(token, self._startup_token):
                return None
            self._startup_token = None
            self._session = new_token()
            self._csrf = new_token()
            return self._session, self._csrf

    def session_valid(self, cookie: str | None) -> bool:
        return _matches(cookie, self._session)

    def csrf_valid(self, header: str | None) -> bool:
        return _matches(header, self._csrf)
