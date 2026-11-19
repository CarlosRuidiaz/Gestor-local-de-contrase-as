"""T9 with the real server: logs, temporary files, process arguments, environment and URLs.

`python -m pvlt.web` runs as a subprocess. Every operation that handles a
secret is exercised, including failures, and then each place where a secret
could leak is searched for every synthetic value.
"""

from __future__ import annotations

import socket
import sys
import time
from pathlib import Path

import pytest

from tests.web.conftest import (
    ENTRY_PASSWORD,
    EXPORT,
    MASTER,
    NEW_MASTER,
    NOTES,
    SECRETS,
    SITE,
    USER,
    WRONG,
    LiveServer,
    start_server,
)


def exercise(server: LiveServer) -> None:
    """Every route that receives or returns a secret, successful and failing."""
    with server.client() as client:
        csrf = client.post("/api/session", json={"token": server.token}).json()["csrf"]
        client.headers["X-CSRF-Token"] = csrf

        assert (
            client.post(
                "/api/create", json={"password": MASTER, "confirm": MASTER, "config": "A"}
            ).status_code
            == 200
        )
        entry = client.post(
            "/api/entries",
            json={"site": SITE, "username": USER, "password": ENTRY_PASSWORD, "notes": NOTES},
        ).json()
        assert client.get(f"/api/entries/{entry['id']}/password").json()["password"] == (
            ENTRY_PASSWORD
        )
        assert client.get("/api/entries").status_code == 200

        # Failures that carry secrets in their request bodies.
        assert (
            client.post(
                "/api/entries", json={"site": SITE, "password": ENTRY_PASSWORD, "extra": NOTES}
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/entries", json={"site": "", "username": USER, "password": ENTRY_PASSWORD}
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/change-password",
                json={"current": WRONG, "new": NEW_MASTER, "confirm": NEW_MASTER},
            ).status_code
            == 400
        )

        assert (
            client.post(
                "/api/export",
                json={
                    "filename": "exportacion.pvlt",
                    "password": EXPORT,
                    "confirm": EXPORT,
                },
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/api/import/preview", json={"filename": "exportacion.pvlt", "password": WRONG}
            ).status_code
            == 400
        )
        assert (
            client.post(
                "/api/import/preview", json={"filename": "exportacion.pvlt", "password": EXPORT}
            ).status_code
            == 200
        )

        assert (
            client.post(
                "/api/change-password",
                json={"current": MASTER, "new": NEW_MASTER, "confirm": NEW_MASTER},
            ).status_code
            == 200
        )
        assert client.post("/api/lock").status_code == 200
        assert client.post("/api/unlock", json={"password": WRONG}).status_code == 400
        assert client.post("/api/unlock", json={"password": NEW_MASTER}).status_code == 200


def assert_clean(text: str | bytes, where: str) -> None:
    for secret in SECRETS:
        needle = secret.encode("utf-8") if isinstance(text, bytes) else secret
        assert needle not in text, f"{where} contiene un dato sintético"


def test_t9_no_secret_in_logs_files_arguments_environment_or_urls(
    live_server: LiveServer,
) -> None:
    exercise(live_server)

    # Arguments and environment of the running server (Linux, the reference platform).
    if sys.platform.startswith("linux"):
        proc = Path(f"/proc/{live_server.process.pid}")
        assert_clean((proc / "cmdline").read_bytes(), "los argumentos del proceso")
        assert_clean((proc / "environ").read_bytes(), "el entorno del proceso")

    # Every file the server left in the vault directory, temporaries included.
    directory = live_server.vault_path.parent
    names = sorted(p.name for p in directory.iterdir())
    assert not [n for n in names if n.endswith(".tmp")], names
    for path in directory.iterdir():
        if path.is_file() and path.suffix != ".lock":
            assert_clean(path.read_bytes(), path.name)

    # URLs requested: secrets travel only in bodies.
    assert live_server.requested_urls
    for url in live_server.requested_urls:
        assert_clean(url, "una URL")
        assert live_server.token not in url

    # Everything the server printed, until it stopped.
    output = live_server.stop()
    assert_clean(output, "la salida del servidor")
    assert "Traceback" not in output
    assert "/api/" not in output, "el log de acceso debe estar desactivado"


@pytest.mark.skipif(sys.platform == "win32", reason="Ctrl+C real solo en POSIX")
def test_ctrl_c_stops_cleanly_and_locks(live_server: LiveServer) -> None:
    with live_server.client() as client:
        csrf = client.post("/api/session", json={"token": live_server.token}).json()["csrf"]
        client.headers["X-CSRF-Token"] = csrf
        client.post("/api/create", json={"password": MASTER, "confirm": MASTER, "config": "A"})
    output = live_server.stop()
    assert live_server.process.returncode == 0
    assert "La bóveda quedó bloqueada" in output


def test_printed_url_carries_the_token_only_in_the_fragment(live_server: LiveServer) -> None:
    first_lines = "".join(live_server.lines)
    assert f"/#t={live_server.token}" in first_lines
    assert f"?t={live_server.token}" not in first_lines
    assert len(live_server.token) == 43


def test_second_server_on_the_same_vault_is_refused(live_server: LiveServer) -> None:
    process, lines = start_server(live_server.vault_path)
    assert process.wait(timeout=30) == 11
    time.sleep(0.2)  # let the reader thread drain the pipe
    assert "La bóveda ya está abierta en otro proceso" in "".join(lines)


def test_listens_only_on_loopback(live_server: LiveServer) -> None:
    with socket.create_connection(("127.0.0.1", live_server.port), timeout=5):
        pass
    host = socket.gethostbyname(socket.gethostname())
    if host.startswith("127."):
        pytest.skip("el equipo no tiene otra dirección que la de loopback")
    with pytest.raises(OSError), socket.create_connection((host, live_server.port), timeout=2):
        pass
