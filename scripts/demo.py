"""Reproducible walk-through of every scenario the assignment asks to demonstrate.

Run it inside the reference container:

    docker compose run --rm app python -m scripts.demo

It works in a fresh temporary folder, uses only synthetic data and never prints
a password. Every scenario ends in an explicit check, and the exit code is 0
only if all of them pass. The automated suite (pytest) remains the evidence:
this script shows the same behaviour step by step for a live demonstration.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from functools import partial
from pathlib import Path

from pvlt.params import CONFIG_A, CONFIG_B, Argon2Params
from pvlt.storage import (
    CorruptedFileError,
    FileStatus,
    FormatError,
    SaveStep,
    atomic_save,
    backup_path,
)
from pvlt.storage.format import DIGEST_LEN, FIELD, FIXED_LEN, sha256
from pvlt.vault import (
    GeneratorSettings,
    ImportDecision,
    TamperedContentError,
    Vault,
    Workspace,
    WrongPasswordError,
    entropy_bits,
)

# Synthetic secrets. They are never printed and never used outside this demo.
MASTER = "demo-maestra-sintetica-1"
NEW_MASTER = "demo-maestra-sintetica-2"
WRONG = "demo-maestra-equivocada"
EXPORT = "demo-exportacion-sintetica"

CONFIGS = {"A": CONFIG_A, "B": CONFIG_B}


class Demo:
    def __init__(self, workdir: Path, params: Argon2Params) -> None:
        self.dir = workdir
        self.params = params
        self.failures = 0

    # --- Output -------------------------------------------------------------

    def title(self, text: str) -> None:
        print(f"\n=== {text} ===")

    def check(self, ok: bool, text: str) -> None:
        print(f"  [{'OK' if ok else 'FALLO'}] {text}")
        if not ok:
            self.failures += 1

    def info(self, text: str) -> None:
        print(f"  - {text}")

    # --- Helpers ------------------------------------------------------------

    def path(self, name: str) -> Path:
        return self.dir / name

    def create(self, name: str, entries: int = 0) -> Vault:
        vault = Vault.create(self.path(name), MASTER, params=self.params)
        for i in range(entries):
            vault.add(**synthetic_entry(i))
        return vault

    def snapshot(self) -> dict[str, bytes]:
        return {
            p.name: p.read_bytes()
            for p in sorted(self.dir.iterdir())
            if p.is_file() and not p.name.endswith(".lock")
        }

    def rejects(
        self,
        action: Callable[[], object],
        expected: type[Exception],
        text: str,
    ) -> None:
        """Run `action`, expect `expected`, and check that no file changed."""
        before = self.snapshot()
        try:
            action()
        except expected as exc:
            same = self.snapshot() == before
            message = "No hay bóveda en esa ruta" if isinstance(exc, FileNotFoundError) else exc
            self.check(same, f"{text}: «{message}», archivos intactos")
        except Exception as exc:
            self.check(
                False, f"{text}: se esperaba {expected.__name__}, llegó {type(exc).__name__}"
            )
        else:
            self.check(False, f"{text}: se aceptó")

    # --- Scenarios ----------------------------------------------------------

    def create_close_reopen(self) -> None:
        self.title("1. Crear, cerrar y reabrir con 1, 100 y 500 entradas (T1)")
        for n in (1, 100, 500):
            name = f"boveda-{n}.pvlt"
            start = time.perf_counter()
            vault = self.create(name, n)
            built = time.perf_counter() - start
            before = [vault.get(e.id) for e in vault.list_entries()]
            vault.lock()
            reopened = Vault.unlock(self.path(name), MASTER)
            after = [reopened.get(e.id) for e in reopened.list_entries()]
            reopened.lock()
            size = self.path(name).stat().st_size
            self.check(
                before == after and len(after) == n,
                f"{n} entrada(s): contenido idéntico tras reabrir ({size} bytes, "
                f"{n} guardado(s) en {built:.1f} s)",
            )
            raw = self.path(name).read_bytes()
            plain = [s.encode() for i in range(n) for s in synthetic_strings(i)]
            self.check(
                not any(s in raw for s in plain),
                "ningún sitio, usuario, contraseña ni nota aparece en claro en el archivo (T3)",
            )

    def operations(self) -> None:
        self.title("2. Operaciones sobre credenciales, generador y bloqueo (T1, T11)")
        clock = FakeClock()
        vault = Vault.create(self.path("boveda.pvlt"), MASTER, params=self.params, clock=clock)
        for i in range(3):
            vault.add(**synthetic_entry(i))
        settings = GeneratorSettings(length=24)
        generated = vault.generate_password(settings)
        entry = vault.add(site="banco.example", username="titular", password=generated)
        self.check(
            len(generated) == 24,
            f"agregar con el generador: 24 caracteres, cota de entropía "
            f"{entropy_bits(settings):.0f} bits",
        )
        found = vault.list_entries("banco")
        self.check([e.id for e in found] == [entry.id], "buscar «banco» devuelve solo esa entrada")
        self.check(vault.get(entry.id).password == generated, "consultar devuelve la contraseña")
        vault.update(entry.id, notes="nota editada")
        self.check(vault.get(entry.id).notes == "nota editada", "modificar la nota")
        vault.delete(entry.id)
        self.check(len(vault) == 3, "eliminar deja 3 entradas")
        generation = vault.generation
        vault.lock()
        reopened = Vault.unlock(self.path("boveda.pvlt"), MASTER, clock=clock)
        self.check(
            len(reopened) == 3 and reopened.generation == generation,
            f"cada cambio se guardó en disco (generación {generation})",
        )
        reopened.update_settings(autolock_seconds=30)
        clock.advance(29)
        self.check(not reopened.is_locked, "a los 29 s de inactividad sigue abierta")
        clock.advance(2)
        self.check(reopened.is_locked, "a los 31 s se bloquea sola (límite configurado en 30 s)")

    def change_password(self) -> None:
        self.title("3. Cambiar la contraseña maestra sin perder registros (T2)")
        path = self.path("boveda.pvlt")
        vault = Vault.unlock(path, MASTER)
        before = [vault.get(e.id) for e in vault.list_entries()]
        vault.change_password(MASTER, NEW_MASTER)
        vault.lock()
        for target, label in ((path, "la bóveda"), (backup_path(path), "el respaldo")):
            opened = Vault.unlock(target, NEW_MASTER)
            same = [opened.get(e.id) for e in opened.list_entries()] == before
            opened.lock()
            self.check(same, f"la contraseña nueva abre {label} con las mismas entradas")
            self.rejects(
                partial(Vault.unlock, target, MASTER),
                WrongPasswordError,
                f"la contraseña anterior ya no abre {label}",
            )

    def wrong_password(self) -> None:
        self.title("4. Contraseña incorrecta y archivos inválidos (T4)")
        path = self.path("boveda.pvlt")
        self.rejects(lambda: Vault.unlock(path, WRONG), WrongPasswordError, "contraseña incorrecta")
        missing = self.path("no-existe.pvlt")
        self.rejects(lambda: Vault.unlock(missing, WRONG), FileNotFoundError, "bóveda inexistente")
        self.check(not missing.exists(), "no se creó ninguna bóveda vacía")

        original = path.read_bytes()
        cases = {
            "archivo truncado": original[:-1],
            "versión de formato desconocida": patch(
                original, FIELD["format_version"].start, b"\x00\x02"
            ),
            "memoria de Argon2id por encima de 4 GiB": patch(
                original, FIELD["m_cost"].start, (4 * 1024 * 1024 + 1).to_bytes(4, "big")
            ),
        }
        for label, data in cases.items():
            with replaced(path, data):
                self.rejects(lambda: Vault.unlock(path, NEW_MASTER), FormatError, label)

    def tampering(self) -> None:
        self.title("5. Manipulación del archivo (T5)")
        path = self.path("boveda.pvlt")
        original = path.read_bytes()
        len_c = len(original) - FIXED_LEN - DIGEST_LEN
        c_start = FIXED_LEN
        tag_c = c_start + len_c - 16
        targets: list[tuple[str, int, type[Exception]]] = [
            ("sal", FIELD["salt"].start, WrongPasswordError),
            ("identificador de bóveda", FIELD["vault_id"].start, WrongPasswordError),
            ("generación", FIELD["generation"].end - 1, WrongPasswordError),
            ("nonce de W", FIELD["nonce_w"].start, WrongPasswordError),
            ("W (DEK cifrada)", FIELD["wrapped_key"].start, WrongPasswordError),
            ("etiqueta de W", FIELD["wrapped_key"].end - 1, WrongPasswordError),
            ("nonce de C", FIELD["nonce_d"].start, TamperedContentError),
            ("contenido C", c_start + 100, TamperedContentError),
            ("etiqueta de C", tag_c, TamperedContentError),
        ]
        self.info("un bit alterado y el resumen SHA-256 recalculado, como haría un atacante:")
        for label, index, expected in targets:
            with replaced(path, redigest(flip_bit(original, index))):
                self.rejects(lambda: Vault.unlock(path, NEW_MASTER), expected, label)

        self.info("un bit alterado sin recalcular el resumen, como en un fallo de disco:")
        with replaced(path, flip_bit(original, c_start + 100)):
            self.rejects(lambda: Vault.unlock(path, NEW_MASTER), CorruptedFileError, "contenido C")

        other = Vault.create(self.path("otra.pvlt"), NEW_MASTER, params=self.params)
        other.add(**synthetic_entry(99))
        other.lock()
        foreign = self.path("otra.pvlt").read_bytes()
        if len(foreign) == len(original):
            swapped = redigest(original[:c_start] + foreign[c_start:])
            with replaced(path, swapped):
                self.rejects(
                    lambda: Vault.unlock(path, NEW_MASTER),
                    TamperedContentError,
                    "C de otra bóveda con la misma contraseña",
                )

    def interrupted_save(self) -> None:
        self.title("6. Fallo durante el guardado y recuperación (T7)")
        for step in SaveStep:
            case = self.dir / f"fallo-{step.value}"
            case.mkdir()
            path = case / "boveda.pvlt"
            vault = Vault.create(path, MASTER, params=self.params)
            vault.add(**synthetic_entry(1))  # generation 2, the backup holds generation 1
            vault.lock()
            current = path.read_bytes()
            next_version = prepare_next_version(case, current)
            with suppress(SimulatedCrashError):
                atomic_save(path, next_version, fault_hook=crash_at(step))
            with Workspace(path) as ws:
                cleaned = len(ws.report.removed_temporaries)
                opened = Vault.unlock(path, MASTER)
                entries = len(opened)
                opened.lock()
            version = "la nueva" if entries == 2 else "la anterior"
            self.check(
                entries in (1, 2),
                f"caída tras «{step.value}»: abre {version} íntegra "
                f"({cleaned} temporal(es) eliminado(s) al arrancar)",
            )

        self.info("un byte dañado en la bóveda, con el respaldo intacto:")
        path = self.path("boveda.pvlt")
        damaged = flip_bit(path.read_bytes(), FIXED_LEN + 50)
        path.write_bytes(damaged)
        with Workspace(path) as ws:
            self.check(
                ws.report.vault is FileStatus.CORRUPTED and ws.report.can_restore_backup,
                "al arrancar se detecta el daño y se ofrece el respaldo",
            )
            self.rejects(
                lambda: Vault.unlock(path, NEW_MASTER),
                CorruptedFileError,
                "abrir no restaura nada por su cuenta",
            )
            kept = ws.restore_backup()
        opened = Vault.unlock(path, NEW_MASTER)
        kept_name = kept.name if kept is not None else "?"
        self.check(
            kept is not None and kept.read_bytes() == damaged and len(opened) == 3,
            f"tras confirmar, se restaura el respaldo y el dañado se conserva como {kept_name}",
        )
        opened.lock()

    def export_import(self) -> None:
        self.title("7. Exportar e importar solo en formato cifrado (T8)")
        source = Vault.unlock(self.path("boveda.pvlt"), NEW_MASTER)
        exported = self.path("exportacion.pvlt")
        source.export(exported, EXPORT)
        source.lock()
        raw = exported.read_bytes()
        plain = [s.encode() for i in range(3) for s in synthetic_strings(i)]
        self.check(not any(s in raw for s in plain), "la exportación no contiene texto claro")

        target = self.create("destino.pvlt", 1)  # entry 0 already exists there
        self.rejects(
            lambda: target.import_preview(exported, WRONG),
            WrongPasswordError,
            "importar con una contraseña de exportación equivocada",
        )
        self.rejects(
            lambda: target.import_preview(self.path("boveda.pvlt"), EXPORT),
            FormatError,
            "importar la bóveda misma en lugar de una exportación",
        )
        preview = target.import_preview(exported, EXPORT)
        conflicts = preview.conflicts
        self.check(
            len(preview.items) == 3 and len(conflicts) == 1,
            "vista previa: 3 entradas, 1 en conflicto por sitio y usuario",
        )
        decisions = {item.entry.id: ImportDecision.KEEP_BOTH for item in conflicts}
        result = target.import_apply(preview, decisions)
        self.check(
            (result.added, result.kept_both) == (2, 1) and len(target) == 4,
            "aplicar conservando ambas: 2 nuevas, 1 duplicada con id nuevo, 4 en total",
        )
        target.lock()

    def run(self) -> int:
        print(f"Carpeta de trabajo: {self.dir}")
        print(
            f"Argon2id: {self.params.m_cost // 1024} MiB, {self.params.t_cost} pasadas, "
            f"{self.params.parallelism} carriles"
        )
        self.create_close_reopen()
        self.operations()
        self.change_password()
        self.wrong_password()
        self.tampering()
        self.interrupted_save()
        self.export_import()
        self.title("8. Experimentos (E1, E2, E3)")
        self.info("se ejecutan aparte: python -m bench.run_all (resultados en bench/results/)")
        print()
        if self.failures:
            print(f"{self.failures} comprobación(es) fallaron.")
            return 1
        print("Todas las comprobaciones pasaron.")
        return 0


# --- Synthetic data ----------------------------------------------------------


def synthetic_entry(i: int) -> dict[str, str]:
    site, username, password, notes = synthetic_strings(i)
    return {"site": site, "username": username, "password": password, "notes": notes}


def synthetic_strings(i: int) -> tuple[str, str, str, str]:
    return (
        f"sitio-{i:03d}.example",
        f"usuario-{i:03d}",
        f"clave-sintetica-{i:03d}-{hashlib.sha256(str(i).encode()).hexdigest()[:12]}",
        f"nota sintética {i:03d}",
    )


class FakeClock:
    """Monotonic clock that the demo advances by hand, to show the inactivity lock."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


# --- Byte-level manipulation (what A2 and A3 can do) -------------------------


def flip_bit(data: bytes, index: int) -> bytes:
    out = bytearray(data)
    out[index] ^= 0x01
    return bytes(out)


def patch(data: bytes, start: int, replacement: bytes) -> bytes:
    return redigest(data[:start] + replacement + data[start + len(replacement) :])


def redigest(data: bytes) -> bytes:
    body = data[:-DIGEST_LEN]
    return body + sha256(body)


@contextmanager
def replaced(path: Path, data: bytes) -> Iterator[None]:
    """Put `data` in place of the file for the duration of the block."""
    original = path.read_bytes()
    path.write_bytes(data)
    try:
        yield
    finally:
        path.write_bytes(original)


class SimulatedCrashError(Exception):
    pass


def crash_at(step: SaveStep) -> Callable[[SaveStep], None]:
    def hook(reached: SaveStep) -> None:
        if reached is step:
            raise SimulatedCrashError(step.value)

    return hook


def prepare_next_version(case: Path, current: bytes) -> bytes:
    """Produce the file a real save would write next, in a scratch copy."""
    scratch = case / "copia"
    scratch.mkdir()
    copy = scratch / "boveda.pvlt"
    copy.write_bytes(current)
    vault = Vault.unlock(copy, MASTER)
    vault.add(**synthetic_entry(2))
    vault.lock()
    data = copy.read_bytes()
    shutil.rmtree(scratch)
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.demo",
        description="Demostración reproducible de pvlt con datos sintéticos.",
    )
    parser.add_argument(
        "--config",
        choices=sorted(CONFIGS),
        default="A",
        help="configuración de Argon2id (A por defecto, como las pruebas funcionales)",
    )
    parser.add_argument("--keep", action="store_true", help="no borrar la carpeta de trabajo")
    args = parser.parse_args(argv)

    workdir = Path(tempfile.mkdtemp(prefix="pvlt-demo-"))
    try:
        return Demo(workdir, CONFIGS[args.config]).run()
    finally:
        if args.keep:
            print(f"Los archivos quedan en {workdir}")
        else:
            shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
