"""T13 over HTTP: token, session cookie, CSRF, Host, Origin, headers and page hygiene.

The browser half of T13 (escaped notes, iframe and cross-site requests from a
real page) is in `test_browser.py`.
"""

from __future__ import annotations

import re
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from pvlt.web.app import STATIC_DIR
from pvlt.web.security import SECURITY_HEADERS, Guard
from tests.web.conftest import MASTER, NOTES, Harness

# Every API route with a body that would be accepted if the request were authorized.
API_ROUTES: list[tuple[str, str, dict[str, object] | None]] = [
    ("GET", "/api/status", None),
    ("POST", "/api/restore-backup", {"confirm": True}),
    ("POST", "/api/create", {"password": MASTER, "confirm": MASTER, "config": "A"}),
    ("POST", "/api/unlock", {"password": MASTER}),
    ("POST", "/api/lock", None),
    ("GET", "/api/entries", None),
    ("POST", "/api/entries", {"site": "s", "password": "p"}),
    ("GET", "/api/entries/x", None),
    ("GET", "/api/entries/x/password", None),
    ("PUT", "/api/entries/x", {"site": "s"}),
    ("DELETE", "/api/entries/x", None),
    ("POST", "/api/generate", {}),
    ("GET", "/api/settings", None),
    ("PUT", "/api/settings", {"autolock_seconds": 60}),
    ("POST", "/api/change-password", {"current": "a", "new": "b", "confirm": "b"}),
    ("GET", "/api/files", None),
    ("POST", "/api/export", {"filename": "e.pvlt", "password": "p", "confirm": "p"}),
    ("POST", "/api/import/preview", {"filename": "e.pvlt", "password": "p"}),
    ("POST", "/api/import/apply", {"preview_id": "x"}),
]

ROUTE_IDS = [f"{method} {path}" for method, path, _ in API_ROUTES]


def call(client: TestClient, method: str, path: str, body: object) -> httpx.Response:
    return client.request(method, path, json=body)


# --- Startup token and session cookie ------------------------------------------------


def test_token_redeems_once(harness: Harness) -> None:
    first = harness.client.post("/api/session", json={"token": harness.token})
    assert first.status_code == 200
    again = harness.client.post("/api/session", json={"token": harness.token})
    assert again.status_code == 401
    assert again.json()["error"] == "token"


def test_wrong_token_is_rejected_and_does_not_burn_the_real_one(harness: Harness) -> None:
    wrong = harness.client.post("/api/session", json={"token": "x" * 43})
    assert wrong.status_code == 401
    assert harness.client.post("/api/session", json={"token": harness.token}).status_code == 200


def test_token_is_never_accepted_in_the_url(harness: Harness) -> None:
    response = harness.client.post(f"/api/session?token={harness.token}", json={})
    assert response.status_code == 422
    assert harness.client.post("/api/session", json={"token": harness.token}).status_code == 200


def test_session_cookie_attributes(harness: Harness) -> None:
    response = harness.client.post("/api/session", json={"token": harness.token})
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("pvlt_session=")
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie or "SameSite=Strict" in cookie
    assert "Path=/" in cookie
    assert "Max-Age" not in cookie and "expires" not in cookie.casefold()
    assert response.json()["csrf"] not in cookie


def test_guard_tokens_have_256_bits() -> None:
    guard = Guard(1234, "t")
    pair = guard.redeem("t")
    assert pair is not None
    for value in pair:
        assert len(value) == 43  # 32 bytes in unpadded base64url
    assert guard.allowed_hosts == {"127.0.0.1:1234", "localhost:1234"}
    assert guard.allowed_origins == {"http://127.0.0.1:1234", "http://localhost:1234"}


# --- 401 without cookie, 403 without CSRF --------------------------------------------


@pytest.mark.parametrize(("method", "path", "body"), API_ROUTES, ids=ROUTE_IDS)
def test_api_without_cookie_is_401(harness: Harness, method: str, path: str, body: object) -> None:
    response = call(harness.client, method, path, body)
    assert response.status_code == 401
    assert response.json()["error"] == "no_session"


@pytest.mark.parametrize(("method", "path", "body"), API_ROUTES, ids=ROUTE_IDS)
def test_api_without_csrf_is_403(web: Harness, method: str, path: str, body: object) -> None:
    del web.client.headers["X-CSRF-Token"]
    response = call(web.client, method, path, body)
    assert response.status_code == 403
    assert response.json()["error"] == "csrf"


@pytest.mark.parametrize(("method", "path", "body"), API_ROUTES, ids=ROUTE_IDS)
def test_api_with_wrong_csrf_is_403(web: Harness, method: str, path: str, body: object) -> None:
    web.client.headers["X-CSRF-Token"] = "A" * 43
    response = call(web.client, method, path, body)
    assert response.status_code == 403


def test_forged_cookie_is_401(web: Harness) -> None:
    web.client.cookies.set("pvlt_session", "A" * 43)
    assert web.client.get("/api/status").status_code == 401


def test_nothing_changes_without_csrf(web: Harness, vault_path: Path) -> None:
    del web.client.headers["X-CSRF-Token"]
    web.client.post("/api/create", json={"password": MASTER, "confirm": MASTER, "config": "A"})
    assert not vault_path.exists()


# --- Host and Origin -------------------------------------------------------------------


@pytest.mark.parametrize(
    "host",
    ["evil.example", "evil.example:8765", "127.0.0.1:9999", "localhost", "127.0.0.1", "[::1]:8765"],
)
@pytest.mark.parametrize("path", ["/", "/static/app.js", "/api/status", "/api/session"])
def test_foreign_host_is_403(web: Harness, host: str, path: str) -> None:
    method = "POST" if path == "/api/session" else "GET"
    response = web.client.request(method, path, headers={"Host": host})
    assert response.status_code == 403
    assert response.json()["error"] == "host"


@pytest.mark.parametrize(
    "origin",
    [
        "http://evil.example",
        "null",
        "http://127.0.0.1:9999",
        "https://127.0.0.1:8765",
        "http://127.0.0.1:8765.evil.example",
    ],
)
@pytest.mark.parametrize("method", ["GET", "POST"])
def test_foreign_origin_is_403(web: Harness, origin: str, method: str) -> None:
    path = "/api/status" if method == "GET" else "/api/lock"
    response = web.client.request(method, path, headers={"Origin": origin})
    assert response.status_code == 403
    assert response.json()["error"] == "origin"


def test_post_without_origin_is_403(web: Harness) -> None:
    del web.client.headers["Origin"]
    response = web.client.post("/api/lock")
    assert response.status_code == 403
    assert response.json()["error"] == "origin"


def test_token_exchange_without_origin_is_403(harness: Harness) -> None:
    del harness.client.headers["Origin"]
    response = harness.client.post("/api/session", json={"token": harness.token})
    assert response.status_code == 403


def test_get_without_origin_is_allowed(web: Harness) -> None:
    del web.client.headers["Origin"]
    assert web.client.get("/api/status").status_code == 200
    assert web.client.get("/").status_code == 200


def test_localhost_host_and_origin_are_accepted(harness: Harness) -> None:
    client = TestClient(
        harness.app,
        base_url="http://localhost:8765",
        headers={"Origin": "http://localhost:8765"},
    )
    response = client.post("/api/session", json={"token": harness.token})
    assert response.status_code == 200
    client.headers["X-CSRF-Token"] = response.json()["csrf"]
    assert client.get("/api/status").status_code == 200


# --- Response headers and CORS -------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/"),
        ("GET", "/static/app.js"),
        ("GET", "/static/app.css"),
        ("GET", "/api/status"),
        ("GET", "/api/entries"),
        ("GET", "/no-existe"),
        ("POST", "/api/lock"),
    ],
)
def test_security_headers_everywhere(web: Harness, method: str, path: str) -> None:
    response = web.client.request(method, path)
    for name, value in SECURITY_HEADERS.items():
        assert response.headers[name] == value, name
    assert "access-control-allow-origin" not in response.headers


def test_security_headers_on_rejections(harness: Harness) -> None:
    for response in (
        harness.client.get("/api/status"),  # 401
        harness.client.get("/", headers={"Host": "evil.example"}),  # 403
    ):
        assert (
            response.headers["Content-Security-Policy"]
            == SECURITY_HEADERS["Content-Security-Policy"]
        )
        assert response.headers["Cache-Control"] == "no-store"


def test_csp_forbids_frames_and_foreign_sources() -> None:
    csp = SECURITY_HEADERS["Content-Security-Policy"]
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp


def test_no_cors_preflight(web: Harness) -> None:
    response = web.client.options(
        "/api/lock",
        headers={
            "Origin": "http://evil.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-csrf-token",
        },
    )
    assert response.status_code == 403
    assert not any(h.startswith("access-control-") for h in response.headers)


def test_api_docs_are_disabled(web: Harness) -> None:
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert web.client.get(path).status_code == 404


# --- Stored HTML comes back as data ------------------------------------------------------


def test_html_in_notes_is_returned_as_json_data(unlocked: Harness) -> None:
    payload = '<img src=x onerror="alert(1)"><script>alert(2)</script>'
    entry_id = unlocked.add(notes=payload, site=payload)
    response = unlocked.client.get(f"/api/entries/{entry_id}")
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["notes"] == payload
    assert response.json()["site"] == payload


def test_validation_errors_do_not_echo_the_input(unlocked: Harness) -> None:
    secret = f"{NOTES}-echo"
    for body in (
        {"password": 12345, "unknown": secret},
        {"site": secret, "password": secret, "extra": secret},
        {"site": [secret], "password": secret},
    ):
        response = unlocked.client.post("/api/entries", json=body)
        assert response.status_code == 422
        assert secret not in response.text
        assert "12345" not in response.text
        assert response.json()["error"] == "invalid"


def test_malformed_json_is_422_without_echo(unlocked: Harness) -> None:
    raw = '{"password": "' + MASTER + '"'
    response = unlocked.client.post(
        "/api/unlock", content=raw, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422
    assert MASTER not in response.text


# --- The page itself ----------------------------------------------------------------------


def test_page_has_no_inline_code_and_no_external_sources() -> None:
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html) is None, "inline script"
    assert re.search(r"<style", html) is None
    assert re.search(r"\sstyle=", html) is None
    assert re.search(r"\son[a-z]+=", html) is None, "inline event handler"
    for url in re.findall(r'(?:src|href)="([^"]+)"', html):
        assert url.startswith("/static/") or url == "/", url


def test_script_never_writes_html() -> None:
    source = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    lines = source.splitlines()
    js = "\n".join(line for line in lines if not line.strip().startswith("//"))
    for forbidden in (
        "innerHTML",
        "outerHTML",
        "insertAdjacentHTML",
        "document.write",
        "eval(",
        "new Function",
        "localStorage",
    ):
        assert forbidden not in js, forbidden
    assert "textContent" in js


def test_master_password_fields_use_new_password_autocomplete() -> None:
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    password_inputs = re.findall(r"<input[^>]*type=\"password\"[^>]*>", html)
    assert password_inputs
    for tag in password_inputs:
        assert 'autocomplete="new-password"' in tag, tag


def test_forms_never_submit_with_get() -> None:
    """A form submitted before the script loads must not put a password in the URL."""
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    forms = re.findall(r"<form[^>]*>", html)
    assert forms
    for tag in forms:
        assert 'method="post"' in tag, tag


def test_page_recommends_not_saving_the_master_password() -> None:
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert "no permitas que el navegador guarde la contraseña maestra" in html
