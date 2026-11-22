"""Minimal command-line interface, for the backup demo and the experiments.

Every password is read with `getpass`, never from an argument or an environment
variable (rule 3). Sites, usernames, notes and search terms are read from the
terminal too, so that no user data ends up in the process arguments (rule 2).
Only the vault path, entry ids and generator options travel as arguments.

Each run is one process: it opens a `Workspace` (lock and recovery), runs one
command and locks the vault before exiting. Every failure becomes a fixed
message in Spanish and a non-zero exit code, never a traceback.

    python -m pvlt.cli create | unlock | list | get | add | change-password
                       | export | import | generate
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Final

from pvlt.params import CONFIG_A, CONFIG_B, CONFIG_C, Argon2Params
from pvlt.storage import (
    CorruptedFileError,
    FileStatus,
    FormatError,
    RecoveryReport,
    VaultLockedError,
)
from pvlt.vault import (
    ConflictReason,
    EntryNotFoundError,
    EntrySummary,
    GeneratorSettings,
    ImportDecision,
    SessionLockedError,
    TamperedContentError,
    ValidationError,
    Vault,
    VaultExistsError,
    Workspace,
    WrongPasswordError,
    entropy_bits,
    generate,
)
from pvlt.vault.vault import MASTER_PASSWORD_MAX_LEN, MASTER_PASSWORD_MIN_LEN

VAULT_FILENAME: Final = "boveda.pvlt"
VAULT_DIR_ENV: Final = "PVLT_VAULT_DIR"

CONFIGS: Final[dict[str, Argon2Params]] = {"A": CONFIG_A, "B": CONFIG_B, "C": CONFIG_C}

# Exit codes. 2 is what argparse uses for a malformed command line.
EXIT_OK: Final = 0
EXIT_USAGE: Final = 2
EXIT_FORMAT: Final = 3
EXIT_CORRUPTED: Final = 4
EXIT_WRONG_PASSWORD: Final = 5
EXIT_TAMPERED: Final = 6
EXIT_SESSION_LOCKED: Final = 7
EXIT_INVALID: Final = 8
EXIT_ENTRY_NOT_FOUND: Final = 9
EXIT_EXISTS: Final = 10
EXIT_IN_USE: Final = 11
EXIT_NO_VAULT: Final = 12
EXIT_MISMATCH: Final = 13
EXIT_IO: Final = 14
EXIT_CANCELLED: Final = 130

# Names of the fields a ValidationError can carry, as the user knows them.
FIELD_LABELS: Final[dict[str, str]] = {
    "site": "sitio",
    "username": "usuario",
    "password": "contraseña",
    "notes": "notas",
    "id": "identificador",
    "entries": "la bóveda admite como máximo 500 entradas",
    "generator.length": "longitud del generador (8 a 128)",
    "generator.classes": "el generador necesita al menos una clase de caracteres",
    "generator": "configuración del generador",
    "m_cost": "memoria de Argon2id",
}

CONFLICT_REASONS: Final[dict[ConflictReason, str]] = {
    ConflictReason.SAME_ID: "mismo identificador",
    ConflictReason.SAME_SITE_AND_USERNAME: "mismo sitio y usuario",
}

DECISIONS: Final[dict[str, ImportDecision]] = {
    "skip": ImportDecision.SKIP,
    "replace": ImportDecision.REPLACE,
    "keep-both": ImportDecision.KEEP_BOTH,
}


class CliError(Exception):
    """A failure detected by the interface itself, with its message and exit code."""

    def __init__(self, message: str, code: int) -> None:
        super().__init__(message)
        self.code = code


class Cancelled(Exception):
    """The user interrupted a prompt (Ctrl+C or end of input)."""


# --- Terminal input -----------------------------------------------------------


def ask_secret(prompt: str) -> str:
    """Read a secret without echo. The only way a password enters the program."""
    try:
        return getpass.getpass(prompt)
    except (EOFError, KeyboardInterrupt):
        raise Cancelled from None


def ask(prompt: str) -> str:
    """Read a visible line from the terminal (site, username, notes, answers)."""
    try:
        return input(prompt)
    except (EOFError, KeyboardInterrupt):
        raise Cancelled from None


def confirm(prompt: str) -> bool:
    """Yes or no question. Anything other than an explicit yes is a no."""
    try:
        answer = ask(f"{prompt} [s/N]: ")
    except Cancelled:
        return False
    return answer.strip().casefold() in {"s", "si", "sí", "y", "yes"}


def ask_new_secret(what: str) -> str:
    """Ask a new password twice and check its length before running Argon2id."""
    first = ask_secret(f"Nueva {what}: ")
    if not MASTER_PASSWORD_MIN_LEN <= len(first) <= MASTER_PASSWORD_MAX_LEN:
        raise CliError(
            f"La {what} debe tener entre {MASTER_PASSWORD_MIN_LEN} y "
            f"{MASTER_PASSWORD_MAX_LEN} caracteres",
            EXIT_INVALID,
        )
    if ask_secret(f"Repite la {what}: ") != first:
        raise CliError("Las contraseñas no coinciden", EXIT_MISMATCH)
    return first


def out(text: str = "") -> None:
    print(text, file=sys.stdout)


def err(text: str) -> None:
    print(text, file=sys.stderr)


# --- Startup ------------------------------------------------------------------


def default_vault_path() -> Path:
    directory = os.environ.get(VAULT_DIR_ENV)
    return Path(directory) / VAULT_FILENAME if directory else Path(VAULT_FILENAME)


def handle_recovery(ws: Workspace) -> None:
    """Report what the startup pass found and offer the backup when it applies."""
    report = ws.report
    if report.removed_temporaries:
        err(
            f"Aviso: se eliminaron {len(report.removed_temporaries)} temporales "
            "de un guardado interrumpido."
        )
    if report.possible_rollback:
        err(
            f"Aviso: el respaldo es más reciente que la bóveda (generación "
            f"{report.backup_generation} frente a {report.vault_generation}). "
            "La bóveda podría ser una copia antigua."
        )
    if report.can_restore_backup:
        state = {
            FileStatus.MISSING: "No hay bóveda en esa ruta",
            FileStatus.UNRECOGNIZED: "La bóveda tiene un formato no reconocido",
            FileStatus.CORRUPTED: "La bóveda está dañada",
        }[report.vault]
        err(f"{state}, pero el respaldo está bien (generación {report.backup_generation}).")
        if confirm("¿Restaurar el respaldo? El archivo actual se conserva aparte"):
            kept = ws.restore_backup()
            err("Respaldo restaurado.")
            if kept is not None:
                err(f"El archivo anterior se guardó como {kept.name}.")


def require_readable(report: RecoveryReport) -> None:
    """Fail before asking for the password if the vault cannot be opened anyway."""
    if report.vault is FileStatus.MISSING:
        raise FileNotFoundError
    if report.vault is FileStatus.UNRECOGNIZED:
        raise FormatError("startup")
    if report.vault is FileStatus.CORRUPTED:
        raise CorruptedFileError


def unlock(ws: Workspace) -> Vault:
    require_readable(ws.report)
    return Vault.unlock(ws.path, ask_secret("Contraseña maestra: "))


# --- Output -------------------------------------------------------------------


def print_entries(entries: Sequence[EntrySummary]) -> None:
    if not entries:
        out("(sin entradas)")
        return
    for e in entries:
        user = e.username or "-"
        out(f"{e.id}  {e.site}  {user}  {e.modified}")


def print_generated(password: str, settings: GeneratorSettings) -> None:
    out(password)
    err(f"Entropía: {entropy_bits(settings):.1f} bits (cota superior)")


# --- Commands -----------------------------------------------------------------


def cmd_create(args: argparse.Namespace, ws: Workspace) -> None:
    if ws.report.vault is not FileStatus.MISSING:
        raise VaultExistsError
    password = ask_new_secret("contraseña maestra")
    vault = Vault.create(ws.path, password, params=CONFIGS[args.config])
    vault.lock()
    out(f"Bóveda creada en {ws.path} (configuración {args.config}).")


def cmd_unlock(args: argparse.Namespace, ws: Workspace) -> None:
    vault = unlock(ws)
    try:
        out(f"Bóveda abierta: {len(vault)} entradas, generación {vault.generation}.")
        print_entries(vault.list_entries())
    finally:
        vault.lock()


def cmd_list(args: argparse.Namespace, ws: Workspace) -> None:
    vault = unlock(ws)
    try:
        query = ask("Buscar (sitio o usuario): ") if args.search else ""
        print_entries(vault.list_entries(query))
    finally:
        vault.lock()


def cmd_get(args: argparse.Namespace, ws: Workspace) -> None:
    vault = unlock(ws)
    try:
        entry = vault.get(args.id)
        out(f"Sitio:       {entry.site}")
        out(f"Usuario:     {entry.username}")
        out(f"Contraseña:  {entry.password if args.show else '(oculta, usa --show)'}")
        out(f"Notas:       {entry.notes}")
        out(f"Creada:      {entry.created}")
        out(f"Modificada:  {entry.modified}")
    finally:
        vault.lock()


def cmd_add(args: argparse.Namespace, ws: Workspace) -> None:
    vault = unlock(ws)
    try:
        site = ask("Sitio: ")
        username = ask("Usuario (opcional): ")
        notes = ask("Notas (opcional): ")
        if args.generate:
            settings = generator_settings(args)
            password = vault.generate_password(settings)
            err(f"Contraseña generada: {entropy_bits(settings):.1f} bits (cota superior).")
        else:
            password = ask_secret("Contraseña de la entrada: ")
            if ask_secret("Repite la contraseña de la entrada: ") != password:
                raise CliError("Las contraseñas no coinciden", EXIT_MISMATCH)
        entry = vault.add(site=site, username=username, password=password, notes=notes)
        out(f"Entrada añadida: {entry.id}")
    finally:
        vault.lock()


def cmd_change_password(args: argparse.Namespace, ws: Workspace) -> None:
    require_readable(ws.report)
    current = ask_secret("Contraseña maestra actual: ")
    vault = Vault.unlock(ws.path, current)
    try:
        new = ask_new_secret("contraseña maestra")
        vault.change_password(current, new)
        out("Contraseña maestra cambiada. El respaldo también usa la nueva.")
    finally:
        vault.lock()


def cmd_export(args: argparse.Namespace, ws: Workspace) -> None:
    destination = Path(args.destination)
    if not args.overwrite and os.path.lexists(destination):
        raise VaultExistsError
    vault = unlock(ws)
    try:
        password = ask_new_secret("contraseña de exportación")
        vault.export(destination, password, overwrite=args.overwrite)
        out(f"Exportadas {len(vault)} entradas a {destination}.")
    finally:
        vault.lock()


def cmd_import(args: argparse.Namespace, ws: Workspace) -> None:
    source = Path(args.source)
    if not source.is_file():
        raise CliError("No existe el archivo a importar", EXIT_NO_VAULT)
    vault = unlock(ws)
    try:
        preview = vault.import_preview(source, ask_secret("Contraseña de exportación: "))
        conflicts = preview.conflicts
        out(f"El archivo tiene {len(preview.items)} entradas, {len(conflicts)} en conflicto.")

        decisions: dict[str, ImportDecision] = {}
        for item in conflicts:
            if args.on_conflict != "ask":
                decisions[item.entry.id] = DECISIONS[args.on_conflict]
                continue
            reason = CONFLICT_REASONS[item.conflict_reason] if item.conflict_reason else "conflicto"
            out(f"Conflicto ({reason}): {item.entry.site}  {item.entry.username or '-'}")
            decisions[item.entry.id] = ask_decision()

        result = vault.import_apply(preview, decisions)
        out(
            f"Importación aplicada: {result.added} añadidas, {result.replaced} sustituidas, "
            f"{result.kept_both} duplicadas con identificador nuevo, {result.skipped} omitidas."
        )
    finally:
        vault.lock()


def ask_decision() -> ImportDecision:
    """A missing or unknown answer skips the entry, which destroys nothing."""
    try:
        answer = ask("  [o]mitir, [s]ustituir o [c]onservar ambas (o): ").strip().casefold()
    except Cancelled:
        return ImportDecision.SKIP
    return {"s": ImportDecision.REPLACE, "c": ImportDecision.KEEP_BOTH}.get(
        answer[:1], ImportDecision.SKIP
    )


def generator_settings(args: argparse.Namespace) -> GeneratorSettings:
    return GeneratorSettings(
        length=args.length,
        lower=not args.no_lower,
        upper=not args.no_upper,
        digits=not args.no_digits,
        symbols=not args.no_symbols,
    )


def cmd_generate(args: argparse.Namespace) -> None:
    settings = generator_settings(args)
    print_generated(generate(settings), settings)


# --- Errors -------------------------------------------------------------------


def translate(exc: BaseException) -> tuple[str, int] | None:
    """Fixed user message and exit code of a known failure. Never shows user data."""
    match exc:
        case CliError():
            return str(exc), exc.code
        case FormatError():
            return str(exc), EXIT_FORMAT
        case CorruptedFileError():
            return (
                f"{exc}. Si hay un respaldo válido, el programa ofrece restaurarlo al arrancar",
                EXIT_CORRUPTED,
            )
        case WrongPasswordError():
            return str(exc), EXIT_WRONG_PASSWORD
        case TamperedContentError():
            return str(exc), EXIT_TAMPERED
        case SessionLockedError():
            return str(exc), EXIT_SESSION_LOCKED
        case ValidationError():
            return f"{exc}: {FIELD_LABELS.get(exc.field, exc.field)}", EXIT_INVALID
        case EntryNotFoundError():
            return str(exc), EXIT_ENTRY_NOT_FOUND
        case VaultExistsError():
            return str(exc), EXIT_EXISTS
        case VaultLockedError():
            return str(exc), EXIT_IN_USE
        case FileNotFoundError():
            return "No hay bóveda en esa ruta. Créala con 'create'", EXIT_NO_VAULT
        case OSError():
            # strerror is the system's text, without the file name or contents.
            detail = exc.strerror or "error del sistema"
            return f"No se pudo leer o escribir el archivo: {detail}", EXIT_IO
    return None


# --- Command line -------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pvlt-cli",
        description="Gestor local de contraseñas. Las contraseñas se piden siempre por "
        "teclado, nunca como argumento.",
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="orden")

    vault_opts = argparse.ArgumentParser(add_help=False)
    vault_opts.add_argument(
        "--vault",
        type=Path,
        default=None,
        metavar="RUTA",
        help=f"archivo de la bóveda (por defecto ${VAULT_DIR_ENV}/{VAULT_FILENAME} "
        f"o ./{VAULT_FILENAME})",
    )

    gen_opts = argparse.ArgumentParser(add_help=False)
    gen_opts.add_argument("--length", type=int, default=GeneratorSettings().length)
    gen_opts.add_argument("--no-lower", action="store_true", help="sin minúsculas")
    gen_opts.add_argument("--no-upper", action="store_true", help="sin mayúsculas")
    gen_opts.add_argument("--no-digits", action="store_true", help="sin dígitos")
    gen_opts.add_argument("--no-symbols", action="store_true", help="sin símbolos")

    p = sub.add_parser("create", parents=[vault_opts], help="crear una bóveda vacía")
    p.add_argument(
        "--config",
        choices=sorted(CONFIGS),
        default="B",
        type=str.upper,
        help="configuración de Argon2id (por defecto B)",
    )
    p.set_defaults(handler=cmd_create)

    p = sub.add_parser("unlock", parents=[vault_opts], help="abrir la bóveda y listarla")
    p.set_defaults(handler=cmd_unlock)

    p = sub.add_parser("list", parents=[vault_opts], help="listar entradas sin contraseñas")
    p.add_argument("--search", action="store_true", help="pedir por teclado un texto para filtrar")
    p.set_defaults(handler=cmd_list)

    p = sub.add_parser("get", parents=[vault_opts], help="mostrar una entrada")
    p.add_argument("id", help="identificador de la entrada (lo muestra 'list')")
    p.add_argument("--show", action="store_true", help="mostrar también la contraseña")
    p.set_defaults(handler=cmd_get)

    p = sub.add_parser("add", parents=[vault_opts, gen_opts], help="añadir una entrada")
    p.add_argument("--generate", action="store_true", help="generar la contraseña")
    p.set_defaults(handler=cmd_add)

    p = sub.add_parser(
        "change-password", parents=[vault_opts], help="cambiar la contraseña maestra"
    )
    p.set_defaults(handler=cmd_change_password)

    p = sub.add_parser("export", parents=[vault_opts], help="exportar a un archivo cifrado")
    p.add_argument("destination", metavar="DESTINO")
    p.add_argument("--overwrite", action="store_true", help="sobrescribir el destino")
    p.set_defaults(handler=cmd_export)

    p = sub.add_parser("import", parents=[vault_opts], help="importar una exportación")
    p.add_argument("source", metavar="ORIGEN")
    p.add_argument(
        "--on-conflict",
        choices=["ask", *DECISIONS],
        default="ask",
        help="qué hacer con los conflictos (por defecto preguntar uno a uno)",
    )
    p.set_defaults(handler=cmd_import)

    p = sub.add_parser("generate", parents=[gen_opts], help="generar una contraseña")
    p.set_defaults(handler=None)

    return parser


def run(args: argparse.Namespace) -> None:
    if args.command == "generate":
        cmd_generate(args)
        return
    handler: Callable[[argparse.Namespace, Workspace], None] = args.handler
    path: Path = args.vault if args.vault is not None else default_vault_path()
    with Workspace(path) as ws:
        handle_recovery(ws)
        handler(args, ws)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        run(args)
    except (Cancelled, KeyboardInterrupt):
        err("Operación cancelada.")
        return EXIT_CANCELLED
    except Exception as exc:
        known = translate(exc)
        if known is None:
            # Unknown failure: report only its class, never its text or traceback.
            err(f"Error inesperado ({type(exc).__name__}).")
            return 1
        message, code = known
        err(f"Error: {message}.")
        return code
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
