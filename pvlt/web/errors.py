"""Translation of every failure into a JSON response with a fixed Spanish message.

The body is `{"error": code, "message": text}` plus `field` for invalid input.
No response, and no log line, ever carries a value sent by the user or read
from the vault. An unknown failure reports only its class name.
"""

from __future__ import annotations

from typing import Final

from fastapi.responses import JSONResponse

from pvlt.storage import CorruptedFileError, FormatError, VaultLockedError
from pvlt.vault import (
    EntryNotFoundError,
    SessionLockedError,
    TamperedContentError,
    ValidationError,
    VaultExistsError,
    WrongPasswordError,
)

# Names of the fields a ValidationError can carry, as the user knows them.
FIELD_LABELS: Final[dict[str, str]] = {
    "site": "sitio",
    "username": "usuario",
    "password": "contraseña",
    "new": "contraseña nueva",
    "current": "contraseña actual",
    "confirm": "confirmación",
    "notes": "notas",
    "id": "identificador",
    "entries": "la bóveda admite como máximo 500 entradas",
    "generator.length": "longitud del generador (8 a 128)",
    "generator.classes": "el generador necesita al menos una clase de caracteres",
    "generator": "configuración del generador",
    "autolock_seconds": "bloqueo por inactividad (30 a 3600 segundos)",
    "m_cost": "memoria de Argon2id",
    "config": "configuración de Argon2id",
    "filename": "nombre de archivo",
    "decisions": "decisiones de importación",
    "preview_id": "vista previa",
    "body": "cuerpo de la petición",
}


class WebError(Exception):
    """A failure detected by the web layer itself."""

    def __init__(self, status: int, code: str, message: str, field: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.field = field


def error_response(status: int, code: str, message: str, field: str | None = None) -> JSONResponse:
    body: dict[str, str] = {"error": code, "message": message}
    if field is not None:
        body["field"] = field
    return JSONResponse(body, status_code=status)


def invalid(field: str) -> JSONResponse:
    return error_response(422, "invalid", f"Dato inválido: {FIELD_LABELS.get(field, field)}", field)


def translate(exc: BaseException) -> JSONResponse:
    """Map a failure to its response. The text comes from the class, never from data."""
    match exc:
        case WebError():
            return error_response(exc.status, exc.code, str(exc), exc.field)
        case FormatError():
            return error_response(422, "format", str(exc))
        case CorruptedFileError():
            return error_response(422, "corrupted", str(exc))
        case WrongPasswordError():
            return error_response(400, "wrong_password", str(exc))
        case TamperedContentError():
            return error_response(422, "tampered", str(exc))
        case SessionLockedError():
            return error_response(423, "locked", str(exc))
        case ValidationError():
            return invalid(exc.field)
        case EntryNotFoundError():
            return error_response(404, "not_found", str(exc))
        case VaultExistsError():
            return error_response(409, "exists", str(exc))
        case VaultLockedError():
            return error_response(409, "in_use", str(exc))
        case FileNotFoundError():
            return error_response(404, "no_vault", "No hay bóveda en esa ruta")
        case OSError():
            # strerror is the system's text, without the file name or contents.
            detail = exc.strerror or "error del sistema"
            return error_response(500, "io", f"No se pudo leer o escribir el archivo: {detail}")
    return error_response(500, "unexpected", f"Error inesperado ({type(exc).__name__})")
