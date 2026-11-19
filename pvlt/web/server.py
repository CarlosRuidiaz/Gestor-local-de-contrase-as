"""Startup of the local server: lock, token, socket, URL and uvicorn.

    python -m pvlt.web [--vault RUTA] [--port N] [--no-browser]

Outside Docker the server listens on 127.0.0.1 with a random port and opens the
browser. Inside the container (`PVLT_IN_DOCKER=1`) it listens on 0.0.0.0:8765,
which compose publishes only on the host's 127.0.0.1, and prints the URL.

The access log is disabled and the server only logs warnings, whose texts are
uvicorn's own and never carry request data.
"""

from __future__ import annotations

import argparse
import os
import signal
import socket
import sys
import webbrowser
from collections.abc import Sequence
from pathlib import Path
from typing import Final

import uvicorn

from pvlt.storage import VaultLockedError
from pvlt.vault import Workspace
from pvlt.web.app import create_app
from pvlt.web.security import Guard, new_token

VAULT_FILENAME: Final = "boveda.pvlt"
VAULT_DIR_ENV: Final = "PVLT_VAULT_DIR"
DOCKER_ENV: Final = "PVLT_IN_DOCKER"
DOCKER_PORT: Final = 8765

EXIT_OK: Final = 0
EXIT_IN_USE: Final = 11
EXIT_IO: Final = 14


def default_vault_path() -> Path:
    directory = os.environ.get(VAULT_DIR_ENV)
    return Path(directory) / VAULT_FILENAME if directory else Path(VAULT_FILENAME)


def in_docker() -> bool:
    return os.environ.get(DOCKER_ENV) == "1"


def bind(host: str, port: int) -> socket.socket:
    """Bind before printing the URL, so the port is known and already listening."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((host, port))
        sock.listen(64)
    except BaseException:
        sock.close()
        raise
    return sock


def _interrupt(signum: int, frame: object) -> None:
    raise KeyboardInterrupt


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m pvlt.web",
        description="Interfaz web local de pvlt. La contraseña maestra se escribe en la página.",
    )
    parser.add_argument(
        "--vault",
        type=Path,
        default=None,
        metavar="RUTA",
        help=f"archivo de la bóveda (por defecto ${VAULT_DIR_ENV}/{VAULT_FILENAME} "
        f"o ./{VAULT_FILENAME})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help=f"puerto (por defecto {DOCKER_PORT} en Docker y uno aleatorio fuera)",
    )
    parser.add_argument("--no-browser", action="store_true", help="no abrir el navegador")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    path: Path = args.vault if args.vault is not None else default_vault_path()
    docker = in_docker()
    host = "0.0.0.0" if docker else "127.0.0.1"  # noqa: S104 - inside the container only
    port: int = args.port if args.port is not None else (DOCKER_PORT if docker else 0)

    try:
        workspace = Workspace(path)
    except VaultLockedError as exc:
        print(f"Error: {exc}.", file=sys.stderr)
        return EXIT_IN_USE
    except OSError as exc:
        print(f"Error: no se pudo abrir la bóveda: {exc.strerror or 'error'}.", file=sys.stderr)
        return EXIT_IO

    with workspace:
        try:
            sock = bind(host, port)
        except OSError as exc:
            print(f"Error: no se pudo abrir el puerto: {exc.strerror or 'error'}.", file=sys.stderr)
            return EXIT_IO
        port = sock.getsockname()[1]
        token = new_token()
        app = create_app(workspace, Guard(port, token))
        url = f"http://127.0.0.1:{port}/#t={token}"

        print(f"pvlt escucha en http://127.0.0.1:{port}/ (bóveda: {path})", flush=True)
        print(f"Abre esta URL en el navegador: {url}", flush=True)
        print("El enlace sirve una sola vez. Ctrl+C cierra pvlt y bloquea la bóveda.", flush=True)
        if not docker and not args.no_browser:
            webbrowser.open(url)

        config = uvicorn.Config(
            app,
            log_level="warning",
            access_log=False,
            server_header=False,
            date_header=False,
        )
        # uvicorn shuts down gracefully on SIGINT or SIGTERM (the lifespan locks the
        # vault) and then raises the signal again. SIGTERM is turned into the same
        # KeyboardInterrupt as Ctrl+C so both end here, without a traceback.
        signal.signal(signal.SIGTERM, _interrupt)
        try:
            uvicorn.Server(config).run(sockets=[sock])
        except KeyboardInterrupt:
            pass
        finally:
            sock.close()
    print("pvlt cerrado. La bóveda quedó bloqueada.", flush=True)
    return EXIT_OK
