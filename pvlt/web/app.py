"""FastAPI application: routes over `pvlt.vault`, behind the guard of `security.py`.

One process serves one vault. The `Workspace` opened at startup holds the lock
for the whole life of the server. Routes are synchronous and run in a thread
pool, so every access to the session goes through one mutex.

No route takes user data in the URL: search runs in the page over the listing,
and every secret travels in a JSON body or a JSON response. Entry ids, which
are random UUIDs, are the only values that appear in a path.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Final

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from pvlt.params import CONFIG_A, CONFIG_B, CONFIG_C, Argon2Params
from pvlt.storage import CorruptedFileError, FileStatus, FormatError, RecoveryReport
from pvlt.vault import (
    Entry,
    EntrySummary,
    GeneratorSettings,
    ImportDecision,
    ImportPreview,
    SessionLockedError,
    Settings,
    ValidationError,
    Vault,
    VaultExistsError,
    Workspace,
    entropy_bits,
    generate,
)
from pvlt.vault.model import Clock, Now, utc_now
from pvlt.web import schemas
from pvlt.web.errors import WebError, error_response, invalid, translate
from pvlt.web.security import (
    CSRF_HEADER,
    SECURITY_HEADERS,
    SESSION_COOKIE,
    Guard,
    new_token,
)

STATIC_DIR: Final = Path(__file__).parent / "static"

CONFIGS: Final[dict[str, Argon2Params]] = {"A": CONFIG_A, "B": CONFIG_B, "C": CONFIG_C}

# Export and import files live next to the vault and are named, never given as a path.
FILENAME_RE: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}\.pvlt")

DECISIONS: Final[dict[str, ImportDecision]] = {
    "skip": ImportDecision.SKIP,
    "replace": ImportDecision.REPLACE,
    "keep_both": ImportDecision.KEEP_BOTH,
}

AUTOLOCK_POLL_SECONDS: Final = 5.0

Json = dict[str, Any]


class WebState:
    """The session of the single local user: at most one unlocked vault."""

    def __init__(self, workspace: Workspace, *, clock: Clock, now: Now) -> None:
        self.workspace = workspace
        self.clock = clock
        self.now = now
        self.vault: Vault | None = None
        self.preview: tuple[str, ImportPreview] | None = None
        self.mutex = threading.RLock()

    def __repr__(self) -> str:
        return f"WebState(unlocked={self.vault is not None})"

    def unlocked(self) -> Vault:
        """The open vault, or `SessionLockedError` if it was locked or timed out."""
        if self.vault is None or self.vault.is_locked:
            self.forget()
            raise SessionLockedError
        return self.vault

    def forget(self) -> None:
        """Lock the vault (erases the KEK) and drop every reference to its content."""
        if self.vault is not None:
            self.vault.lock()
        self.vault = None
        self.preview = None

    def expire(self) -> None:
        """Called periodically so the KEK is erased on time even if nobody asks."""
        with self.mutex:
            if self.vault is not None and self.vault.is_locked:
                self.forget()

    def file(self, name: str) -> Path:
        """An export or import file in the vault directory. Rejects paths and vault files."""
        if FILENAME_RE.fullmatch(name) is None or name == self.workspace.path.name:
            raise ValidationError("filename")
        return self.workspace.path.parent / name


# --- Serialization ------------------------------------------------------------


def status_body(state: WebState) -> Json:
    report: RecoveryReport = state.workspace.report
    vault = state.vault if state.vault is not None and not state.vault.is_locked else None
    return {
        "vault_name": state.workspace.path.name,
        "vault": report.vault.value,
        "backup": report.backup.value,
        "vault_generation": report.vault_generation,
        "backup_generation": report.backup_generation,
        "can_restore_backup": report.can_restore_backup,
        "possible_rollback": report.possible_rollback,
        "removed_temporaries": len(report.removed_temporaries),
        "unlocked": vault is not None,
        "seconds_until_autolock": vault.seconds_until_autolock() if vault is not None else 0,
    }


def summary_body(entry: EntrySummary | Entry) -> Json:
    return {
        "id": entry.id,
        "site": entry.site,
        "username": entry.username,
        "modified": entry.modified,
    }


def detail_body(entry: Entry) -> Json:
    """Everything except the password, which is requested on its own."""
    return {**summary_body(entry), "notes": entry.notes, "created": entry.created}


def generator_body(settings: GeneratorSettings) -> Json:
    return {
        "length": settings.length,
        "lower": settings.lower,
        "upper": settings.upper,
        "digits": settings.digits,
        "symbols": settings.symbols,
    }


def settings_body(settings: Settings) -> Json:
    return {
        "autolock_seconds": settings.autolock_seconds,
        "generator": generator_body(settings.generator),
    }


def to_generator(body: schemas.GeneratorBody) -> GeneratorSettings:
    return GeneratorSettings(
        length=body.length,
        lower=body.lower,
        upper=body.upper,
        digits=body.digits,
        symbols=body.symbols,
    )


def require_readable(report: RecoveryReport) -> None:
    """Fail before running Argon2id if the vault cannot be opened anyway."""
    if report.vault is FileStatus.MISSING:
        raise FileNotFoundError
    if report.vault is FileStatus.UNRECOGNIZED:
        raise FormatError("startup")
    if report.vault is FileStatus.CORRUPTED:
        raise CorruptedFileError


def same_twice(value: str, confirm: str) -> None:
    if value != confirm:
        raise WebError(422, "mismatch", "Las contraseñas no coinciden", "confirm")


# --- Request guard ------------------------------------------------------------


def check_request(guard: Guard, request: Request) -> Response | None:
    """Host, Origin, session cookie and CSRF, in that order. None means allowed."""
    if not guard.host_allowed(request.headers.get("host")):
        return error_response(403, "host", "Host no permitido")
    if not guard.origin_allowed(request.headers.get("origin"), request.method):
        return error_response(403, "origin", "Origen no permitido")
    path = request.url.path
    if not path.startswith("/api/"):
        return None
    if path == "/api/session" and request.method == "POST":
        return None  # the token exchange, authenticated by the startup token itself
    if not guard.session_valid(request.cookies.get(SESSION_COOKIE)):
        return error_response(401, "no_session", "Sesión no válida. Abre la URL que mostró pvlt.")
    if not guard.csrf_valid(request.headers.get(CSRF_HEADER)):
        return error_response(403, "csrf", "Falta el token CSRF o no es válido")
    return None


async def invalid_body(request: Request, exc: Exception) -> Response:
    """Replaces FastAPI's handler, which would echo the submitted values back."""
    field = "body"
    if isinstance(exc, RequestValidationError) and exc.errors():
        loc = exc.errors()[0].get("loc", ())
        names = [str(part) for part in loc if isinstance(part, str) and part != "body"]
        field = ".".join(names) or "body"
    return invalid(field)


# --- Application --------------------------------------------------------------


def create_app(
    workspace: Workspace,
    guard: Guard,
    *,
    clock: Clock = time.monotonic,
    now: Now = utc_now,
    autolock_poll: float = AUTOLOCK_POLL_SECONDS,
) -> FastAPI:
    state = WebState(workspace, clock=clock, now=now)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        stop = threading.Event()

        def watch() -> None:
            while not stop.wait(autolock_poll):
                state.expire()

        watcher = threading.Thread(target=watch, name="pvlt-autolock", daemon=True)
        watcher.start()
        try:
            yield
        finally:
            # Closing the program locks the vault.
            stop.set()
            watcher.join(timeout=autolock_poll + 1)
            with state.mutex:
                state.forget()

    app = FastAPI(
        title="pvlt",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.web = state
    app.add_exception_handler(RequestValidationError, invalid_body)

    @app.middleware("http")
    async def guard_requests(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        try:
            response = check_request(guard, request) or await call_next(request)
        except Exception as exc:
            # Caught here so no traceback reaches the server log.
            response = translate(exc)
        for name, value in SECURITY_HEADERS.items():
            response.headers[name] = value
        return response

    # --- Page -------------------------------------------------------------------

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html", media_type="text/html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    # --- Session ----------------------------------------------------------------

    @app.post("/api/session")
    def open_session(body: schemas.TokenBody) -> Response:
        pair = guard.redeem(body.token)
        if pair is None:
            return error_response(
                401, "token", "El enlace de inicio ya se usó o no es válido. Reinicia pvlt."
            )
        session, csrf = pair
        response = JSONResponse({"csrf": csrf})
        response.set_cookie(SESSION_COOKIE, session, httponly=True, samesite="strict", path="/")
        return response

    @app.get("/api/status")
    def get_status() -> Json:
        with state.mutex:
            return status_body(state)

    @app.post("/api/restore-backup")
    def restore_backup(body: schemas.ConfirmBody) -> Json:
        if not body.confirm:
            raise ValidationError("confirm")
        with state.mutex:
            if not state.workspace.refresh().can_restore_backup:
                raise WebError(409, "no_backup", "No hay un respaldo que restaurar")
            kept = state.workspace.restore_backup()
            return {**status_body(state), "kept": kept.name if kept is not None else None}

    @app.post("/api/create")
    def create(body: schemas.CreateBody) -> Json:
        same_twice(body.password, body.confirm)
        with state.mutex:
            state.forget()
            if state.workspace.refresh().vault is not FileStatus.MISSING:
                raise VaultExistsError
            state.vault = Vault.create(
                state.workspace.path,
                body.password,
                params=CONFIGS[body.config],
                clock=state.clock,
                now=state.now,
            )
            state.workspace.refresh()
            return status_body(state)

    @app.post("/api/unlock")
    def unlock(body: schemas.UnlockBody) -> Json:
        with state.mutex:
            state.forget()
            require_readable(state.workspace.refresh())
            state.vault = Vault.unlock(
                state.workspace.path, body.password, clock=state.clock, now=state.now
            )
            return status_body(state)

    @app.post("/api/lock")
    def lock() -> Json:
        with state.mutex:
            state.forget()
            return status_body(state)

    # --- Entries ----------------------------------------------------------------

    @app.get("/api/entries")
    def list_entries() -> Json:
        with state.mutex:
            return {"entries": [summary_body(e) for e in state.unlocked().list_entries()]}

    @app.post("/api/entries")
    def add_entry(body: schemas.EntryBody) -> Json:
        with state.mutex:
            entry = state.unlocked().add(
                site=body.site, username=body.username, password=body.password, notes=body.notes
            )
            return detail_body(entry)

    @app.get("/api/entries/{entry_id}")
    def get_entry(entry_id: str) -> Json:
        with state.mutex:
            return detail_body(state.unlocked().get(entry_id))

    @app.get("/api/entries/{entry_id}/password")
    def get_password(entry_id: str) -> Json:
        with state.mutex:
            return {"password": state.unlocked().get(entry_id).password}

    @app.put("/api/entries/{entry_id}")
    def update_entry(entry_id: str, body: schemas.EntryUpdateBody) -> Json:
        with state.mutex:
            entry = state.unlocked().update(
                entry_id,
                site=body.site,
                username=body.username,
                password=body.password,
                notes=body.notes,
            )
            return detail_body(entry)

    @app.delete("/api/entries/{entry_id}")
    def delete_entry(entry_id: str) -> Json:
        with state.mutex:
            state.unlocked().delete(entry_id)
            return {"deleted": entry_id}

    # --- Generator and settings -------------------------------------------------

    @app.post("/api/generate")
    def generate_password(body: schemas.GeneratorBody) -> Json:
        settings = to_generator(body)
        return {"password": generate(settings), "entropy_bits": entropy_bits(settings)}

    @app.get("/api/settings")
    def get_settings() -> Json:
        with state.mutex:
            return settings_body(state.unlocked().settings)

    @app.put("/api/settings")
    def update_settings(body: schemas.SettingsBody) -> Json:
        generator = to_generator(body.generator) if body.generator is not None else None
        with state.mutex:
            settings = state.unlocked().update_settings(
                autolock_seconds=body.autolock_seconds, generator=generator
            )
            return settings_body(settings)

    # --- Master password, export and import -------------------------------------

    @app.post("/api/change-password")
    def change_password(body: schemas.ChangePasswordBody) -> Json:
        same_twice(body.new, body.confirm)
        with state.mutex:
            state.unlocked().change_password(body.current, body.new)
            state.workspace.refresh()
            return status_body(state)

    @app.get("/api/files")
    def list_files() -> Json:
        with state.mutex:
            state.unlocked()
            directory = state.workspace.path.parent
            names = sorted(
                p.name
                for p in directory.glob("*.pvlt")
                if p.is_file()
                and p.name != state.workspace.path.name
                and FILENAME_RE.fullmatch(p.name)
            )
            return {"files": names}

    @app.post("/api/export")
    def export(body: schemas.ExportBody) -> Json:
        same_twice(body.password, body.confirm)
        with state.mutex:
            vault = state.unlocked()
            destination = state.file(body.filename)
            vault.export(destination, body.password, overwrite=body.overwrite)
            return {"filename": destination.name, "entries": len(vault)}

    @app.post("/api/import/preview")
    def import_preview(body: schemas.ImportPreviewBody) -> Json:
        with state.mutex:
            vault = state.unlocked()
            source = state.file(body.filename)
            if not source.is_file():
                raise WebError(404, "no_file", "No existe el archivo a importar", "filename")
            preview = vault.import_preview(source, body.password)
            preview_id = new_token()
            state.preview = (preview_id, preview)
            items = [
                {
                    **summary_body(item.entry),
                    "conflict": item.conflict_reason.value if item.conflict_reason else None,
                }
                for item in preview.items
            ]
            return {
                "preview_id": preview_id,
                "items": items,
                "conflicts": len(preview.conflicts),
            }

    @app.post("/api/import/apply")
    def import_apply(body: schemas.ImportApplyBody) -> Json:
        with state.mutex:
            vault = state.unlocked()
            if state.preview is None or state.preview[0] != body.preview_id:
                raise WebError(
                    409,
                    "no_preview",
                    "La vista previa ya no es válida. Repite la importación",
                    "preview_id",
                )
            preview = state.preview[1]
            decisions = {key: DECISIONS[value] for key, value in body.decisions.items()}
            result = vault.import_apply(preview, decisions)
            state.preview = None
            return {
                "added": result.added,
                "replaced": result.replaced,
                "kept_both": result.kept_both,
                "skipped": result.skipped,
            }

    return app
