"""Shared fixtures of the vault tests. Every password and entry here is synthetic."""

from __future__ import annotations

from pathlib import Path

import pytest

from pvlt.params import CONFIG_A
from pvlt.vault import Vault

MASTER = "synthetic-master-Ñ-密码-001"
OTHER = "synthetic-other-password-002"
EXPORT = "synthetic-export-password-003"


class FakeClock:
    """Monotonic clock under test control, for the inactivity lock."""

    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def fixed_now() -> str:
    return "2026-11-16T12:00:00Z"


def synthetic_entry(i: int) -> dict[str, str]:
    return {
        "site": f"sitio-sintetico-{i:03d}.example",
        "username": f"usuario.sintetico.{i:03d}",
        "password": f"CLAVE-SINTETICA-{i:03d}-zxqj",
        "notes": f"nota sintética número {i:03d} con ñ y 日本語",
    }


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def vault_path(tmp_path: Path) -> Path:
    return tmp_path / "boveda.pvlt"


@pytest.fixture
def vault(vault_path: Path, clock: FakeClock) -> Vault:
    """An unlocked empty vault with the fast Argon2id configuration A."""
    return Vault.create(vault_path, MASTER, params=CONFIG_A, clock=clock, now=fixed_now)


def reopen(path: Path, password: str = MASTER, clock: FakeClock | None = None) -> Vault:
    return Vault.unlock(path, password, clock=clock or FakeClock(), now=fixed_now)


def snapshot(directory: Path) -> dict[str, bytes]:
    """Every file of the directory except the lock, which is empty and unreadable on Windows."""
    return {p.name: p.read_bytes() for p in sorted(directory.iterdir()) if p.suffix != ".lock"}
