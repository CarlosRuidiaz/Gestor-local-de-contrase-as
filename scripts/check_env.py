"""Verify the library assumptions made by the design (docs/diseno.md).

Prints one line per check and exits with status 1 if a hard requirement fails.
Uses only public synthetic data (RFC test vectors). Nothing secret is printed.

Usage: python scripts/check_env.py
"""

from __future__ import annotations

import os
import platform
import sys
import time

import cryptography
from cryptography.hazmat.backends.openssl import backend
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

HARD_FAILURES: list[str] = []


def report(name: str, value: object, ok: bool | None = None) -> None:
    mark = {True: "OK ", False: "FALLA", None: "INFO"}[ok]
    print(f"[{mark:5}] {name}: {value}")


def hard(name: str, value: object, ok: bool) -> None:
    report(name, value, ok)
    if not ok:
        HARD_FAILURES.append(name)


def check_versions() -> None:
    report("Python", platform.python_version(), sys.version_info[:2] == (3, 12))
    report("Plataforma", f"{platform.system()} {platform.release()} {platform.machine()}")
    report("Núcleos lógicos", os.cpu_count())
    report("cryptography", cryptography.__version__)
    report("OpenSSL", backend.openssl_version_text())


def check_chacha_rfc8439() -> None:
    """RFC 8439 section 2.8.2."""
    key = bytes(range(0x80, 0xA0))
    nonce = bytes.fromhex("070000004041424344454647")
    aad = bytes.fromhex("50515253c0c1c2c3c4c5c6c7")
    plaintext = (
        b"Ladies and Gentlemen of the class of '99: If I could offer you "
        b"only one tip for the future, sunscreen would be it."
    )
    expected_tag = bytes.fromhex("1ae10b594f09e26a7e902ecbd0600691")
    out = ChaCha20Poly1305(key).encrypt(nonce, plaintext, aad)
    hard(
        "ChaCha20-Poly1305 vector RFC 8439 §2.8.2",
        "coincide" if out[-16:] == expected_tag else "NO coincide",
        out[-16:] == expected_tag and out[:4] == bytes.fromhex("d31a8d34"),
    )

    for kind in (bytes, bytearray, memoryview):
        try:
            ChaCha20Poly1305(kind(key)).encrypt(nonce, b"x", None)  # type: ignore[arg-type]
            report(f"ChaCha20Poly1305 acepta clave {kind.__name__}", "sí", True)
        except Exception as exc:
            report(f"ChaCha20Poly1305 acepta clave {kind.__name__}", type(exc).__name__, None)


def check_argon2id() -> None:
    try:
        from cryptography.hazmat.primitives.kdf.argon2 import Argon2id
    except ImportError:
        hard("Argon2id disponible", "no existe kdf.argon2.Argon2id", False)
        return
    hard("Argon2id disponible", "sí", True)

    # RFC 9106 section 5.3 (Argon2id, version 0x13).
    expected = bytes.fromhex("0d640df58d78766c08c037a34a8b53c9d01ef0452d75b65eb52520e96b01e659")
    try:
        kdf = Argon2id(
            salt=bytes([0x02]) * 16,
            length=32,
            iterations=3,
            lanes=4,
            memory_cost=32,
            ad=bytes([0x04]) * 12,
            secret=bytes([0x03]) * 8,
        )
        out = kdf.derive(bytes([0x01]) * 32)
        hard(
            "Argon2id vector RFC 9106 §5.3 (implica v1.3, secret y ad)",
            "coincide" if out == expected else "NO coincide",
            out == expected,
        )
    except Exception as exc:
        hard("Argon2id vector RFC 9106 §5.3", f"{type(exc).__name__}: {exc}", False)

    has_into = hasattr(Argon2id, "derive_into")
    report("Argon2id.derive_into", "existe" if has_into else "no existe", None)
    if has_into:
        buf = bytearray(32)
        try:
            kdf = Argon2id(salt=bytes(16), length=32, iterations=1, lanes=1, memory_cost=8)
            n = kdf.derive_into(b"synthetic", buf)  # type: ignore[attr-defined]
            report("derive_into sobre bytearray", f"escribe {n} bytes", any(buf))
        except Exception as exc:
            report("derive_into sobre bytearray", f"{type(exc).__name__}: {exc}", False)

    # Rough multithreading probe: same memory and passes, 1 lane vs 4 lanes.
    # CPU time above wall time means several cores worked. E1 measures this properly.
    for lanes in (1, 4):
        kdf = Argon2id(salt=bytes(16), length=32, iterations=3, lanes=lanes, memory_cost=65536)
        w0, c0 = time.perf_counter(), time.process_time()
        kdf.derive(b"synthetic")
        wall, cpu = time.perf_counter() - w0, time.process_time() - c0
        report(
            f"Argon2id 64 MiB, t=3, lanes={lanes}",
            f"pared {wall:.3f} s, CPU {cpu:.3f} s, razón CPU/pared {cpu / wall:.2f}",
        )


def main() -> int:
    check_versions()
    check_chacha_rfc8439()
    check_argon2id()
    if HARD_FAILURES:
        print(
            f"\nRequisitos incumplidos: {len(HARD_FAILURES)}. "
            "Hay que documentarlos como desviación del diseño."
        )
        return 1
    print("\nTodos los requisitos duros se cumplen.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
