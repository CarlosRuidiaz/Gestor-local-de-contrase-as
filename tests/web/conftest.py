"""Shared fixtures of the web tests. Every password and entry here is synthetic.

Two ways to reach the application:

- `harness`: the FastAPI app in process with `TestClient`, a fake clock and a
  vault in a temporary directory. Fast, used by the API and HTTP security tests.
- `live_server`: `python -m pvlt.web` as a real subprocess on a random port,
  used by T9 (logs, arguments, files) and by the browser tests.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pvlt.vault import Workspace
from pvlt.web.app import WebState, create_app
from pvlt.web.security import Guard, new_token

PORT = 8765
BASE = f"http://127.0.0.1:{PORT}"

MASTER = "synthetic-web-master-Ñ-001"
NEW_MASTER = "synthetic-web-new-master-002"
WRONG = "synthetic-web-wrong-003"
EXPORT = "synthetic-web-export-004"
ENTRY_PASSWORD = "SYNTHETIC-web-entry-secret-005"
SITE = "sitio-web-sintetico.example"
USER = "usuario.web.sintetico"
NOTES = "nota web sintética con ñ"

SECRETS = (MASTER, NEW_MASTER, WRONG, EXPORT, ENTRY_PASSWORD, SITE, USER, NOTES)

URL_RE = re.compile(r"http://127\.0\.0\.1:(\d+)/#t=([A-Za-z0-9_-]+)")


class FakeClock:
    """Monotonic clock under test control, for the inactivity lock."""

    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def fixed_now() -> str:
    return "2026-11-19T12:00:00Z"


@dataclass
class Harness:
    app: FastAPI
    client: TestClient
    token: str
    workspace: Workspace
    clock: FakeClock

    @property
    def state(self) -> WebState:
        state: WebState = self.app.state.web
        return state

    @property
    def path(self) -> Path:
        return self.workspace.path

    def login(self) -> str:
        response = self.client.post("/api/session", json={"token": self.token})
        assert response.status_code == 200, response.text
        csrf: str = response.json()["csrf"]
        self.client.headers["X-CSRF-Token"] = csrf
        return csrf

    def create(self, password: str = MASTER) -> None:
        response = self.client.post(
            "/api/create", json={"password": password, "confirm": password, "config": "A"}
        )
        assert response.status_code == 200, response.text

    def add(self, i: int = 0, **overrides: str) -> str:
        body = {
            "site": f"{SITE}-{i}",
            "username": f"{USER}-{i}",
            "password": f"{ENTRY_PASSWORD}-{i}",
            "notes": f"{NOTES} {i}",
            **overrides,
        }
        response = self.client.post("/api/entries", json=body)
        assert response.status_code == 200, response.text
        entry_id: str = response.json()["id"]
        return entry_id


def build_harness(vault_path: Path, clock: FakeClock, autolock_poll: float = 5.0) -> Harness:
    workspace = Workspace(vault_path)
    token = new_token()
    app = create_app(
        workspace, Guard(PORT, token), clock=clock, now=fixed_now, autolock_poll=autolock_poll
    )
    client = TestClient(app, base_url=BASE, headers={"Origin": BASE})
    return Harness(app, client, token, workspace, clock)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def vault_path(tmp_path: Path) -> Path:
    return tmp_path / "boveda.pvlt"


@pytest.fixture
def harness(vault_path: Path, clock: FakeClock) -> Iterator[Harness]:
    """App in process, before the token exchange. The lifespan runs inside `with`."""
    h = build_harness(vault_path, clock)
    with h.client:
        yield h
    h.workspace.close()


@pytest.fixture
def web(harness: Harness) -> Harness:
    """Session open (cookie and CSRF), no vault yet."""
    harness.login()
    return harness


@pytest.fixture
def unlocked(web: Harness) -> Harness:
    """An empty vault created through the API with configuration A, left unlocked."""
    web.create()
    return web


# --- Live server --------------------------------------------------------------------


@dataclass
class LiveServer:
    process: subprocess.Popen[str]
    vault_path: Path
    port: int
    token: str
    lines: list[str] = field(default_factory=list)
    requested_urls: list[str] = field(default_factory=list)

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def url(self) -> str:
        return f"{self.base}/#t={self.token}"

    def client(self) -> httpx.Client:
        """HTTP client that records every URL it requests, for T9."""

        def record(request: httpx.Request) -> None:
            self.requested_urls.append(str(request.url))

        return httpx.Client(
            base_url=self.base,
            headers={"Origin": self.base},
            event_hooks={"request": [record]},
            timeout=60,
        )

    def stop(self) -> str:
        """Graceful stop where the platform allows it. Returns everything it printed."""
        if self.process.poll() is None:
            if sys.platform == "win32":
                self.process.terminate()
            else:
                self.process.send_signal(2)  # SIGINT, as Ctrl+C
            try:
                self.process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        time.sleep(0.1)  # let the reader thread drain the pipe
        return "".join(self.lines)


def start_server(vault_path: Path, *extra: str) -> tuple[subprocess.Popen[str], list[str]]:
    env = {k: v for k, v in os.environ.items() if k != "PVLT_IN_DOCKER"}
    env["PYTHONUNBUFFERED"] = "1"
    process = subprocess.Popen(  # noqa: S603 - fixed command, synthetic path
        [
            sys.executable,
            "-m",
            "pvlt.web",
            "--vault",
            str(vault_path),
            "--port",
            "0",
            "--no-browser",
            *extra,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        env=env,
    )
    lines: list[str] = []

    def read() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            lines.append(line)

    threading.Thread(target=read, daemon=True).start()
    return process, lines


def wait_for_url(lines: list[str], process: subprocess.Popen[str]) -> re.Match[str]:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        for line in list(lines):
            match = URL_RE.search(line)
            if match:
                return match
        if process.poll() is not None:
            break
        time.sleep(0.05)
    process.kill()
    raise AssertionError("the server did not print its URL:\n" + "".join(lines))


@pytest.fixture
def live_server(tmp_path: Path) -> Iterator[LiveServer]:
    vault_path = tmp_path / "boveda.pvlt"
    process, lines = start_server(vault_path)
    match = wait_for_url(lines, process)
    server = LiveServer(process, vault_path, int(match.group(1)), match.group(2), lines)
    try:
        yield server
    finally:
        server.stop()
