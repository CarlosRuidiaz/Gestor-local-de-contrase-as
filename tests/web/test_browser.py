"""Browser tests with Playwright against the real server: T12, the browser half of T13, and T9 URLs.

Chromium runs headless inside the container. The page clock is installed before
loading, so the 20-second clipboard timer is advanced without waiting for real.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from playwright.sync_api import Browser, BrowserContext, Page, Playwright, expect, sync_playwright

from tests.web.conftest import ENTRY_PASSWORD, MASTER, NOTES, SECRETS, SITE, USER, LiveServer

pytestmark = pytest.mark.browser

EVIL = "http://evil.test"
CLIPBOARD_SECONDS = 20


@pytest.fixture(scope="module")
def playwright() -> Iterator[Playwright]:
    with sync_playwright() as p:
        yield p


@pytest.fixture(scope="module")
def browser(playwright: Playwright) -> Iterator[Browser]:
    try:
        browser = playwright.chromium.launch()
    except Exception as exc:  # pragma: no cover - only when Chromium is not installed
        pytest.skip(f"Chromium no disponible: {type(exc).__name__}")
    yield browser
    browser.close()


@pytest.fixture
def context(browser: Browser, live_server: LiveServer) -> Iterator[BrowserContext]:
    context = browser.new_context()
    context.grant_permissions(["clipboard-read", "clipboard-write"], origin=live_server.base)
    yield context
    context.close()


@pytest.fixture
def page(context: BrowserContext) -> Page:
    page = context.new_page()
    page.set_default_timeout(30_000)
    return page


def visible(page: Page, selector: str) -> None:
    expect(page.locator(selector)).to_be_visible()


def open_app(page: Page, server: LiveServer) -> None:
    page.goto(server.url)
    expect(page.locator("#view-boot")).to_be_hidden()


def create_vault(page: Page) -> None:
    visible(page, "#view-create")
    page.fill("#create-password", MASTER)
    page.fill("#create-confirm", MASTER)
    page.select_option("#create-config", "A")
    page.click("#create-form button[type=submit]")
    visible(page, "#view-main")


def add_entry(page: Page, *, site: str = SITE, notes: str = NOTES) -> None:
    page.click("#new-entry-button")
    page.fill("#entry-site", site)
    page.fill("#entry-username", USER)
    page.fill("#entry-password", ENTRY_PASSWORD)
    page.fill("#entry-notes", notes)
    page.click("#entry-form button[type=submit]")
    visible(page, "#panel-detail")


def clipboard(page: Page) -> str:
    text: str = page.evaluate("navigator.clipboard.readText()")
    return text


# --- T12 ----------------------------------------------------------------------------------


def test_t12_clipboard_is_cleared_after_20_seconds(page: Page, live_server: LiveServer) -> None:
    page.clock.install()
    open_app(page, live_server)
    create_vault(page)
    add_entry(page)

    page.click("#entries-body button:has-text('Copiar')")
    expect(page.locator("#notice")).to_contain_text("se vaciará en 20 s")
    assert clipboard(page) == ENTRY_PASSWORD

    page.clock.run_for((CLIPBOARD_SECONDS - 1) * 1000)
    assert clipboard(page) == ENTRY_PASSWORD

    page.clock.run_for(2000)
    expect(page.locator("#notice")).to_have_text("Portapapeles vaciado.")
    assert clipboard(page) == ""


def test_t12_a_second_copy_restarts_the_timer(page: Page, live_server: LiveServer) -> None:
    page.clock.install()
    open_app(page, live_server)
    create_vault(page)
    add_entry(page)

    page.click("#detail-copy")
    expect(page.locator("#notice")).to_be_visible()
    page.clock.run_for(15_000)
    expect(page.locator("#notice")).to_be_hidden()  # the notice lasts 8 s
    page.click("#detail-copy")
    expect(page.locator("#notice")).to_be_visible()  # the second copy finished
    page.clock.run_for(15_000)
    assert clipboard(page) == ENTRY_PASSWORD
    page.clock.run_for(6000)
    assert clipboard(page) == ""


# --- T13 in the browser -------------------------------------------------------------------


def test_t13_html_in_entries_is_shown_as_text(page: Page, live_server: LiveServer) -> None:
    payload = '<img src=x onerror="window.__pwned = 1"><script>window.__pwned = 2</script><b>b</b>'
    open_app(page, live_server)
    create_vault(page)
    add_entry(page, site=payload, notes=payload)

    expect(page.locator("#detail-notes")).to_have_text(payload)
    expect(page.locator("#detail-site")).to_have_text(payload)
    expect(page.locator("#entries-body td").first).to_have_text(payload)
    assert page.locator("#app img, #app script, #app b").count() == 0
    assert page.evaluate("window.__pwned") is None


def test_t13_the_app_cannot_be_framed(page: Page, live_server: LiveServer) -> None:
    html = f'<html><body><iframe id="f" src="{live_server.base}/"></iframe></body></html>'
    page.route(f"{EVIL}/**", lambda route: route.fulfill(body=html, content_type="text/html"))
    responses = []
    page.on("response", lambda r: responses.append(r) if r.url == f"{live_server.base}/" else None)
    page.goto(f"{EVIL}/")
    page.wait_for_timeout(1500)

    child = page.frames[1] if len(page.frames) > 1 else None
    assert child is not None
    # The browser refuses to render it: the frame never gets the application's DOM.
    assert child.url != f"{live_server.base}/"
    assert child.query_selector("#app") is None
    for response in responses:
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


def test_t13_a_foreign_page_cannot_act_on_the_session(
    page: Page, context: BrowserContext, live_server: LiveServer
) -> None:
    open_app(page, live_server)
    create_vault(page)
    add_entry(page)

    attack = f"""<html><body><script>
      const base = "{live_server.base}";
      window.results = [];
      for (const [method, path] of [["POST", "/api/lock"], ["DELETE", "/api/entries/x"],
                                    ["GET", "/api/entries"]]) {{
        fetch(base + path, {{ method, credentials: "include", mode: "no-cors" }})
          .then(() => results.push("sent"), () => results.push("blocked"));
        fetch(base + path, {{ method, credentials: "include" }})
          .then(r => r.text().then(t => results.push("read:" + t)), () => results.push("cors"));
      }}
    </script></body></html>"""
    evil = context.new_page()
    evil.route(f"{EVIL}/**", lambda route: route.fulfill(body=attack, content_type="text/html"))
    evil.goto(f"{EVIL}/")
    evil.wait_for_function("window.results && window.results.length === 6")
    results: list[str] = evil.evaluate("window.results")
    assert not [r for r in results if r.startswith("read:")], "a foreign page read a response"
    evil.close()

    # The session is still open and the entry is still there.
    status = page.evaluate(
        """async () => (await fetch("/api/status", {
          headers: {"X-CSRF-Token": sessionStorage.getItem("pvlt.csrf")},
        })).json()"""
    )
    assert status["unlocked"] is True
    expect(page.locator("#entries-body tr")).to_have_count(1)


# --- T9 in the browser: URL, history and storage --------------------------------------


def test_t9_no_secret_in_any_url_and_the_token_leaves_the_address_bar(
    page: Page, live_server: LiveServer
) -> None:
    urls: list[str] = []
    page.on("request", lambda request: urls.append(request.url))
    console: list[str] = []
    page.on("console", lambda msg: console.append(msg.text) if msg.type == "error" else None)

    open_app(page, live_server)
    assert page.url == f"{live_server.base}/"

    create_vault(page)
    add_entry(page)
    page.fill("#search", SITE[:8])
    page.click("#detail-show")
    expect(page.locator("#detail-password")).to_have_text(ENTRY_PASSWORD)
    page.click("#lock-button")
    visible(page, "#view-unlock")
    page.fill("#unlock-password", MASTER)
    page.click("#unlock-form button[type=submit]")
    visible(page, "#view-main")

    assert urls
    for url in urls:
        assert live_server.token not in url
        for secret in SECRETS:
            assert secret not in url
    assert not [m for m in console if "Content Security Policy" in m], console

    stored: str = page.evaluate("JSON.stringify(Object.entries(sessionStorage))")
    for secret in SECRETS:
        assert secret not in stored
    assert page.evaluate("Object.keys(localStorage).length") == 0


def test_locking_clears_the_page(page: Page, live_server: LiveServer) -> None:
    open_app(page, live_server)
    create_vault(page)
    add_entry(page)
    page.click("#detail-show")
    page.click("#lock-button")
    visible(page, "#view-unlock")
    body: str = page.evaluate("document.body.innerText")
    for value in (ENTRY_PASSWORD, SITE, USER, NOTES):
        assert value not in body
    assert page.locator("#entries-body tr").count() == 0


def test_reload_keeps_the_session_but_a_used_link_does_not_work_again(
    page: Page, context: BrowserContext, live_server: LiveServer
) -> None:
    open_app(page, live_server)
    create_vault(page)
    page.reload()
    visible(page, "#view-main")

    other = context.new_page()
    other.goto(live_server.url)
    visible(other, "#view-no-session")
    expect(other.locator("#no-session-reason")).to_contain_text("ya se usó")
    other.close()
