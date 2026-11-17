"""Command-line interface: commands, startup recovery, error translation and secret handling.

`getpass` and `input` are replaced by a scripted terminal. Every password and
entry here is synthetic. The vaults use the fast Argon2id configuration A.
"""

from __future__ import annotations

import argparse
import ast
import getpass
import subprocess
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

import pytest

from pvlt import cli
from pvlt.storage import CorruptedFileError, FormatError, VaultLockedError, backup_path
from pvlt.vault import (
    EntryNotFoundError,
    SessionLockedError,
    TamperedContentError,
    ValidationError,
    Vault,
    VaultExistsError,
    Workspace,
    WrongPasswordError,
)
from tests.storage.helpers import flip_bit, patch

MASTER = "synthetic-cli-master-Ñ-001"
NEW_MASTER = "synthetic-cli-new-master-002"
EXPORT = "synthetic-cli-export-003"
ENTRY_PASSWORD = "SYNTHETIC-entry-secret-004"
SITE = "sitio-sintetico.example"
USER = "usuario.sintetico"
NOTES = "nota sintética con ñ"

# Offset inside C, past the 59-byte header, W and len_C, for the damage tests.
OFFSET_IN_C = 300


@dataclass
class Result:
    code: int
    out: str
    err: str


class Terminal:
    """Scripted terminal. Secrets go through `getpass`, visible answers through `input`."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.secrets: list[str] = []
        self.lines: list[str] = []
        self.secret_prompts: list[str] = []
        monkeypatch.setattr(getpass, "getpass", self._getpass)
        monkeypatch.setattr("builtins.input", self._input)

    def _getpass(self, prompt: str = "Password: ", stream: object = None) -> str:
        self.secret_prompts.append(prompt)
        if not self.secrets:
            raise EOFError
        return self.secrets.pop(0)

    def _input(self, prompt: str = "") -> str:
        if not self.lines:
            raise EOFError
        return self.lines.pop(0)


@pytest.fixture
def term(monkeypatch: pytest.MonkeyPatch) -> Terminal:
    monkeypatch.delenv(cli.VAULT_DIR_ENV, raising=False)
    return Terminal(monkeypatch)


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return tmp_path / "boveda.pvlt"


@pytest.fixture
def run(term: Terminal, capsys: pytest.CaptureFixture[str]) -> Callable[..., Result]:
    def _run(*argv: str, secrets: Iterable[str] = (), lines: Iterable[str] = ()) -> Result:
        term.secrets = list(secrets)
        term.lines = list(lines)
        code = cli.main(list(argv))
        captured = capsys.readouterr()
        assert not term.secrets, "the command did not ask for every scripted secret"
        assert "Traceback" not in captured.err
        return Result(code, captured.out, captured.err)

    return _run


def create(run, path: Path, password: str = MASTER) -> None:
    result = run("create", "--vault", str(path), "--config", "A", secrets=[password, password])
    assert result.code == cli.EXIT_OK, result.err


def add(run, path: Path, i: int = 0, password: str = MASTER) -> str:
    result = run(
        "add",
        "--vault",
        str(path),
        secrets=[password, f"{ENTRY_PASSWORD}-{i}", f"{ENTRY_PASSWORD}-{i}"],
        lines=[f"{i}-{SITE}", f"{USER}.{i}", NOTES],
    )
    assert result.code == cli.EXIT_OK, result.err
    return result.out.strip().rsplit(" ", 1)[-1]


def other_files(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir() if p.suffix != ".lock")


# --- create and unlock --------------------------------------------------------


def test_create_then_unlock_lists_an_empty_vault(run, path: Path) -> None:
    create(run, path)
    assert path.is_file()
    result = run("unlock", "--vault", str(path), secrets=[MASTER])
    assert result.code == cli.EXIT_OK
    assert "0 entradas, generación 1" in result.out
    assert "(sin entradas)" in result.out


def test_create_asks_twice_and_rejects_a_mismatch(run, path: Path) -> None:
    result = run("create", "--vault", str(path), "--config", "A", secrets=[MASTER, NEW_MASTER])
    assert result.code == cli.EXIT_MISMATCH
    assert "no coinciden" in result.err
    assert other_files(path.parent) == []


def test_create_rejects_a_short_password_before_deriving(run, term: Terminal, path: Path) -> None:
    result = run("create", "--vault", str(path), "--config", "A", secrets=["short"])
    assert result.code == cli.EXIT_INVALID
    assert len(term.secret_prompts) == 1
    assert other_files(path.parent) == []


def test_create_refuses_an_existing_vault_without_asking(run, term: Terminal, path: Path) -> None:
    create(run, path)
    before = path.read_bytes()
    term.secret_prompts.clear()
    result = run("create", "--vault", str(path), "--config", "A")
    assert result.code == cli.EXIT_EXISTS
    assert term.secret_prompts == []
    assert path.read_bytes() == before


def test_config_is_case_insensitive(run, path: Path) -> None:
    result = run("create", "--vault", str(path), "--config", "a", secrets=[MASTER, MASTER])
    assert result.code == cli.EXIT_OK
    assert "configuración A" in result.out


def test_default_path_comes_from_the_environment(
    run, path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(cli.VAULT_DIR_ENV, str(path.parent))
    result = run("create", "--config", "A", secrets=[MASTER, MASTER])
    assert result.code == cli.EXIT_OK
    assert path.is_file()


def test_default_path_without_environment_is_the_working_directory(
    run, path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(path.parent)
    assert cli.default_vault_path() == Path(cli.VAULT_FILENAME)
    result = run("create", "--config", "A", secrets=[MASTER, MASTER])
    assert result.code == cli.EXIT_OK
    assert path.is_file()


# --- entries ------------------------------------------------------------------


def test_add_list_and_get(run, path: Path) -> None:
    create(run, path)
    entry_id = add(run, path)

    listed = run("list", "--vault", str(path), secrets=[MASTER])
    assert listed.code == cli.EXIT_OK
    assert entry_id in listed.out
    assert f"0-{SITE}" in listed.out
    assert ENTRY_PASSWORD not in listed.out
    assert NOTES not in listed.out

    hidden = run("get", "--vault", str(path), entry_id, secrets=[MASTER])
    assert hidden.code == cli.EXIT_OK
    assert NOTES in hidden.out
    assert ENTRY_PASSWORD not in hidden.out
    assert "(oculta, usa --show)" in hidden.out

    shown = run("get", "--vault", str(path), entry_id, "--show", secrets=[MASTER])
    assert f"{ENTRY_PASSWORD}-0" in shown.out


def test_add_rejects_a_mismatched_entry_password(run, path: Path) -> None:
    create(run, path)
    result = run(
        "add",
        "--vault",
        str(path),
        secrets=[MASTER, ENTRY_PASSWORD, "other"],
        lines=[SITE, USER, ""],
    )
    assert result.code == cli.EXIT_MISMATCH
    assert len(Vault.unlock(path, MASTER)) == 0


def test_add_with_an_empty_site_is_invalid(run, path: Path) -> None:
    create(run, path)
    result = run(
        "add",
        "--vault",
        str(path),
        secrets=[MASTER, ENTRY_PASSWORD, ENTRY_PASSWORD],
        lines=["", USER, ""],
    )
    assert result.code == cli.EXIT_INVALID
    assert "sitio" in result.err


def test_add_with_a_generated_password(run, path: Path) -> None:
    create(run, path)
    result = run(
        "add",
        "--vault",
        str(path),
        "--generate",
        "--length",
        "32",
        "--no-symbols",
        secrets=[MASTER],
        lines=[SITE, USER, ""],
    )
    assert result.code == cli.EXIT_OK
    assert "bits" in result.err
    vault = Vault.unlock(path, MASTER)
    (summary,) = vault.list_entries()
    password = vault.get(summary.id).password
    assert len(password) == 32
    assert password.isalnum()
    assert password not in result.out + result.err


def test_list_search_reads_the_query_from_the_terminal(run, path: Path) -> None:
    create(run, path)
    first = add(run, path, 1)
    second = add(run, path, 2)
    result = run("list", "--vault", str(path), "--search", secrets=[MASTER], lines=["2-"])
    assert result.code == cli.EXIT_OK
    assert second in result.out
    assert first not in result.out


def test_get_unknown_entry(run, path: Path) -> None:
    create(run, path)
    unknown = "00000000-0000-4000-8000-000000000000"
    result = run("get", "--vault", str(path), unknown, secrets=[MASTER])
    assert result.code == cli.EXIT_ENTRY_NOT_FOUND
    assert "La entrada no existe" in result.err


# --- opening failures ---------------------------------------------------------


def test_wrong_password(run, path: Path) -> None:
    create(run, path)
    result = run("unlock", "--vault", str(path), secrets=[NEW_MASTER])
    assert result.code == cli.EXIT_WRONG_PASSWORD
    assert result.err.strip() == "Error: Contraseña incorrecta."


def test_missing_vault_fails_before_asking_and_creates_nothing(
    run, term: Terminal, path: Path
) -> None:
    result = run("unlock", "--vault", str(path))
    assert result.code == cli.EXIT_NO_VAULT
    assert "create" in result.err
    assert term.secret_prompts == []
    assert other_files(path.parent) == []


def test_unrecognized_file_fails_before_asking(run, term: Terminal, path: Path) -> None:
    path.write_bytes(b"not a vault at all")
    result = run("unlock", "--vault", str(path))
    assert result.code == cli.EXIT_FORMAT
    assert "Formato no reconocido" in result.err
    assert term.secret_prompts == []
    assert path.read_bytes() == b"not a vault at all"


def test_corrupted_vault_without_backup(run, path: Path) -> None:
    create(run, path)
    damaged = flip_bit(path.read_bytes(), OFFSET_IN_C)
    path.write_bytes(damaged)
    result = run("unlock", "--vault", str(path))
    assert result.code == cli.EXIT_CORRUPTED
    assert "Archivo dañado" in result.err
    assert path.read_bytes() == damaged


def test_tampered_content_with_recomputed_digest(run, path: Path) -> None:
    create(run, path)
    data = path.read_bytes()
    path.write_bytes(patch(data, OFFSET_IN_C, bytes([data[OFFSET_IN_C] ^ 1])))
    result = run("unlock", "--vault", str(path), secrets=[MASTER])
    assert result.code == cli.EXIT_TAMPERED
    assert "Contenido manipulado" in result.err


def test_vault_open_in_another_process(run, path: Path) -> None:
    create(run, path)
    with Workspace(path):
        result = run("unlock", "--vault", str(path))
    assert result.code == cli.EXIT_IN_USE
    assert "otro proceso" in result.err


def test_cancelling_a_prompt(run, path: Path) -> None:
    result = run("create", "--vault", str(path), "--config", "A")  # no scripted answer: EOF
    assert result.code == cli.EXIT_CANCELLED
    assert "cancelada" in result.err
    assert other_files(path.parent) == []


def test_unexpected_failure_shows_only_the_class(
    run, path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    create(run, path)

    def boom(*_args: object, **_kwargs: object) -> Vault:
        raise RuntimeError(MASTER)

    monkeypatch.setattr(Vault, "unlock", boom)
    result = run("unlock", "--vault", str(path), secrets=[MASTER])
    assert result.code == 1
    assert "RuntimeError" in result.err
    assert MASTER not in result.err


@pytest.mark.parametrize(
    ("exc", "code", "text"),
    [
        (FormatError("magic"), cli.EXIT_FORMAT, "Formato no reconocido"),
        (CorruptedFileError(), cli.EXIT_CORRUPTED, "Archivo dañado"),
        (WrongPasswordError(), cli.EXIT_WRONG_PASSWORD, "Contraseña incorrecta"),
        (TamperedContentError(), cli.EXIT_TAMPERED, "Contenido manipulado"),
        (SessionLockedError(), cli.EXIT_SESSION_LOCKED, "La bóveda está bloqueada"),
        (ValidationError("site"), cli.EXIT_INVALID, "Dato inválido: sitio"),
        (EntryNotFoundError(), cli.EXIT_ENTRY_NOT_FOUND, "La entrada no existe"),
        (VaultExistsError(), cli.EXIT_EXISTS, "Ya existe un archivo en esa ruta"),
        (VaultLockedError(), cli.EXIT_IN_USE, "otro proceso"),
        (FileNotFoundError(2, "No such file", MASTER), cli.EXIT_NO_VAULT, "No hay bóveda"),
        (PermissionError(13, "Permission denied", MASTER), cli.EXIT_IO, "Permission denied"),
        (cli.CliError("Mensaje fijo", 42), 42, "Mensaje fijo"),
    ],
)
def test_every_known_failure_has_its_message_and_code(exc: Exception, code: int, text: str) -> None:
    translated = cli.translate(exc)
    assert translated is not None
    message, got = translated
    assert got == code
    assert got != cli.EXIT_OK
    assert text in message
    assert MASTER not in message


def test_exit_codes_are_distinct() -> None:
    codes = [v for k, v in vars(cli).items() if k.startswith("EXIT_") and k != "EXIT_OK"]
    assert len(codes) == len(set(codes))
    assert cli.EXIT_OK not in codes


# --- startup recovery ---------------------------------------------------------


def _three_generations(run, path: Path) -> None:
    """Vault at generation 3 with two entries, backup at generation 2 with one."""
    create(run, path)
    add(run, path, 1)
    add(run, path, 2)


def test_damaged_vault_offers_the_backup_and_restores_it(run, path: Path) -> None:
    _three_generations(run, path)
    path.write_bytes(flip_bit(path.read_bytes(), OFFSET_IN_C))

    result = run("unlock", "--vault", str(path), secrets=[MASTER], lines=["s"])
    assert result.code == cli.EXIT_OK, result.err
    assert "La bóveda está dañada" in result.err
    assert "Respaldo restaurado" in result.err
    assert "1 entradas, generación 2" in result.out
    assert any(name.startswith("boveda.pvlt.damaged-") for name in other_files(path.parent))
    assert backup_path(path).is_file()


def test_declining_the_backup_changes_nothing(run, term: Terminal, path: Path) -> None:
    _three_generations(run, path)
    damaged = flip_bit(path.read_bytes(), OFFSET_IN_C)
    path.write_bytes(damaged)
    files_before = other_files(path.parent)
    term.secret_prompts.clear()

    result = run("unlock", "--vault", str(path), lines=["n"])
    assert result.code == cli.EXIT_CORRUPTED
    assert term.secret_prompts == []
    assert path.read_bytes() == damaged
    assert other_files(path.parent) == files_before


def test_missing_vault_with_a_good_backup_offers_it(run, path: Path) -> None:
    _three_generations(run, path)
    path.unlink()
    result = run("list", "--vault", str(path), secrets=[MASTER], lines=["sí"])
    assert result.code == cli.EXIT_OK, result.err
    assert "No hay bóveda en esa ruta, pero el respaldo está bien" in result.err


def test_possible_rollback_is_reported(run, path: Path) -> None:
    _three_generations(run, path)
    current, older = path.read_bytes(), backup_path(path).read_bytes()
    path.write_bytes(older)
    backup_path(path).write_bytes(current)

    result = run("unlock", "--vault", str(path), secrets=[MASTER])
    assert result.code == cli.EXIT_OK
    assert "podría ser una copia antigua" in result.err
    assert "generación 3 frente a 2" in result.err


def test_leftover_temporaries_are_reported(run, path: Path) -> None:
    create(run, path)
    path.with_name(path.name + ".tmp").write_bytes(b"leftover")
    result = run("unlock", "--vault", str(path), secrets=[MASTER])
    assert result.code == cli.EXIT_OK
    assert "se eliminaron 1 temporales" in result.err


# --- master password ----------------------------------------------------------


def test_change_password(run, path: Path) -> None:
    _three_generations(run, path)
    result = run("change-password", "--vault", str(path), secrets=[MASTER, NEW_MASTER, NEW_MASTER])
    assert result.code == cli.EXIT_OK, result.err

    assert run("unlock", "--vault", str(path), secrets=[MASTER]).code == (cli.EXIT_WRONG_PASSWORD)
    assert "2 entradas" in run("unlock", "--vault", str(path), secrets=[NEW_MASTER]).out
    # The backup was rewritten with the new password too.
    with pytest.raises(WrongPasswordError):
        Vault.unlock(backup_path(path), MASTER)
    assert len(Vault.unlock(backup_path(path), NEW_MASTER)) == 2


def test_change_password_with_a_wrong_current_password(run, path: Path) -> None:
    create(run, path)
    before = path.read_bytes()
    result = run("change-password", "--vault", str(path), secrets=[NEW_MASTER])
    assert result.code == cli.EXIT_WRONG_PASSWORD
    assert path.read_bytes() == before


# --- export and import --------------------------------------------------------


@pytest.fixture
def exported(run, tmp_path: Path) -> Path:
    """An export with two entries, `1-...` and `2-...`."""
    source = tmp_path / "origen" / "boveda.pvlt"
    source.parent.mkdir()
    _three_generations(run, source)
    destination = tmp_path / "exportacion.pvlt"
    result = run(
        "export", "--vault", str(source), str(destination), secrets=[MASTER, EXPORT, EXPORT]
    )
    assert result.code == cli.EXIT_OK, result.err
    assert "Exportadas 2 entradas" in result.out
    return destination


def test_export_refuses_an_existing_destination_without_asking(
    run, term: Terminal, path: Path, exported: Path
) -> None:
    create(run, path)
    before = exported.read_bytes()
    term.secret_prompts.clear()
    result = run("export", "--vault", str(path), str(exported))
    assert result.code == cli.EXIT_EXISTS
    assert term.secret_prompts == []
    assert exported.read_bytes() == before


def test_export_overwrite(run, path: Path, exported: Path) -> None:
    create(run, path)
    result = run(
        "export",
        "--vault",
        str(path),
        str(exported),
        "--overwrite",
        secrets=[MASTER, EXPORT, EXPORT],
    )
    assert result.code == cli.EXIT_OK
    assert "Exportadas 0 entradas" in result.out


def test_import_asks_for_each_conflict(run, path: Path, exported: Path) -> None:
    create(run, path)
    add(run, path, 1)  # same site and username as the first exported entry

    result = run(
        "import", "--vault", str(path), str(exported), secrets=[MASTER, EXPORT], lines=["s"]
    )
    assert result.code == cli.EXIT_OK, result.err
    assert "2 entradas, 1 en conflicto" in result.out
    assert "mismo sitio y usuario" in result.out
    assert (
        "1 añadidas, 1 sustituidas, 0 duplicadas con identificador nuevo, 0 omitidas" in result.out
    )
    assert len(Vault.unlock(path, MASTER)) == 2


def test_import_without_an_answer_skips_the_conflict(run, path: Path, exported: Path) -> None:
    create(run, path)
    add(run, path, 1)
    result = run("import", "--vault", str(path), str(exported), secrets=[MASTER, EXPORT])
    assert result.code == cli.EXIT_OK
    assert (
        "1 añadidas, 0 sustituidas, 0 duplicadas con identificador nuevo, 1 omitidas" in result.out
    )


def test_import_with_a_fixed_decision(run, path: Path, exported: Path) -> None:
    create(run, path)
    add(run, path, 1)
    result = run(
        "import",
        "--vault",
        str(path),
        str(exported),
        "--on-conflict",
        "keep-both",
        secrets=[MASTER, EXPORT],
    )
    assert result.code == cli.EXIT_OK
    assert "1 duplicadas" in result.out
    assert len(Vault.unlock(path, MASTER)) == 3


def test_import_with_a_wrong_export_password(run, path: Path, exported: Path) -> None:
    create(run, path)
    result = run("import", "--vault", str(path), str(exported), secrets=[MASTER, NEW_MASTER])
    assert result.code == cli.EXIT_WRONG_PASSWORD


def test_import_of_a_vault_is_rejected(run, path: Path, tmp_path: Path) -> None:
    create(run, path)
    other = tmp_path / "otra" / "boveda.pvlt"
    other.parent.mkdir()
    create(run, other)
    # The purpose byte is checked when the file is opened, before running Argon2id.
    result = run("import", "--vault", str(path), str(other), secrets=[MASTER, EXPORT])
    assert result.code == cli.EXIT_FORMAT


def test_import_of_a_missing_file(run, term: Terminal, path: Path, tmp_path: Path) -> None:
    create(run, path)
    term.secret_prompts.clear()
    result = run("import", "--vault", str(path), str(tmp_path / "no-existe.pvlt"))
    assert result.code == cli.EXIT_NO_VAULT
    assert term.secret_prompts == []


# --- generator ----------------------------------------------------------------


def test_generate_needs_no_vault(run, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = run("generate", "--length", "40", "--no-symbols", "--no-upper")
    assert result.code == cli.EXIT_OK
    password = result.out.strip()
    assert len(password) == 40
    assert password.isalnum() and password == password.lower()
    assert "Entropía: 206.8 bits" in result.err
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "argv",
    [
        ["generate", "--length", "7"],
        ["generate", "--length", "129"],
        ["generate", "--no-lower", "--no-upper", "--no-digits", "--no-symbols"],
    ],
)
def test_generate_rejects_invalid_settings(run, argv: list[str]) -> None:
    result = run(*argv)
    assert result.code == cli.EXIT_INVALID
    assert "generador" in result.err


# --- secrets never leave through arguments, environment or output -------------


def test_no_option_accepts_a_secret() -> None:
    """Rule 3: there is no way to pass a password, site, username or note as an argument."""
    parser = cli.build_parser()
    subparsers = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    forbidden = ("pass", "secret", "site", "user", "note", "query", "contra")
    for name, sub in subparsers.choices.items():
        for action in sub._actions:
            for option in [*action.option_strings, action.dest]:
                assert not any(word in option.lower() for word in forbidden), (name, option)


def test_only_the_vault_directory_is_read_from_the_environment() -> None:
    source = Path(cli.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    reads = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr in {"environ", "getenv"}
    ]
    assert len(reads) == 1
    assert "os.environ.get(VAULT_DIR_ENV)" in source


def test_secrets_never_appear_in_argv_or_output(run, path: Path, tmp_path: Path) -> None:
    secrets = (MASTER, NEW_MASTER, EXPORT, ENTRY_PASSWORD)
    argvs = [
        ["create", "--vault", str(path), "--config", "A"],
        ["add", "--vault", str(path)],
        ["unlock", "--vault", str(path)],
        ["list", "--vault", str(path)],
        ["export", "--vault", str(path), str(tmp_path / "exp.pvlt")],
        ["change-password", "--vault", str(path)],
    ]
    answers = [
        [MASTER, MASTER],
        [MASTER, ENTRY_PASSWORD, ENTRY_PASSWORD],
        [MASTER],
        [MASTER],
        [MASTER, EXPORT, EXPORT],
        [MASTER, NEW_MASTER, NEW_MASTER],
    ]
    for argv, secrets_in in zip(argvs, answers, strict=True):
        lines = [SITE, USER, NOTES] if argv[0] == "add" else []
        result = run(*argv, secrets=secrets_in, lines=lines)
        assert result.code == cli.EXIT_OK, (argv, result.err)
        for secret in secrets:
            assert all(secret not in arg for arg in argv)
            assert secret not in result.out
            assert secret not in result.err
        for value in (SITE, USER, NOTES):
            assert all(value not in arg for arg in argv)
    assert all(s not in " ".join(sys.argv) for s in secrets)


def test_module_entry_point() -> None:
    """`python -m pvlt.cli` works and needs no password to show its help."""
    completed = subprocess.run(
        [sys.executable, "-m", "pvlt.cli", "--help"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=60,
        cwd=Path(cli.__file__).parent.parent,
    )
    assert completed.returncode == 0
    for command in ("create", "unlock", "list", "get", "add", "change-password", "export"):
        assert command in completed.stdout


def test_files_left_after_a_session(run, path: Path) -> None:
    """Only the vault and its backup remain. No temporary or plaintext file is left."""
    _three_generations(run, path)
    assert other_files(path.parent) == ["boveda.pvlt", "boveda.pvlt.bak"]
