"""Vault lock: one process at a time, released by the kernel when the holder dies."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from pvlt.storage import VaultLock, VaultLockedError
from pvlt.storage.lock import lock_path

HOLDER = """
import sys
from pathlib import Path
from pvlt.storage import VaultLock
lock = VaultLock(Path(sys.argv[1]))
lock.acquire()
print("ready", flush=True)
sys.stdin.readline()
"""


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    return tmp_path / "boveda.pvlt"


def test_second_acquire_is_refused(vault: Path) -> None:
    first, second = VaultLock(vault), VaultLock(vault)
    first.acquire()
    try:
        assert first.held
        with pytest.raises(VaultLockedError) as info:
            second.acquire()
        assert not second.held
        assert str(info.value) == "La bóveda ya está abierta en otro proceso"
    finally:
        first.release()


def test_release_allows_a_new_holder(vault: Path) -> None:
    first, second = VaultLock(vault), VaultLock(vault)
    first.acquire()
    first.release()
    assert not first.held
    second.acquire()
    second.release()


def test_context_manager_and_idempotence(vault: Path) -> None:
    with VaultLock(vault) as lock:
        lock.acquire()  # already ours, no error
        with pytest.raises(VaultLockedError):
            VaultLock(vault).acquire()
    lock.release()  # already released, no error
    with VaultLock(vault):
        pass


def test_lock_is_released_when_the_block_raises(vault: Path) -> None:
    with pytest.raises(RuntimeError), VaultLock(vault):
        raise RuntimeError("synthetic failure")
    with VaultLock(vault):
        pass


def test_locks_of_different_vaults_are_independent(tmp_path: Path) -> None:
    with VaultLock(tmp_path / "a.pvlt"), VaultLock(tmp_path / "b.pvlt"):
        pass


def test_lock_file_is_empty_and_does_not_touch_the_vault(vault: Path) -> None:
    with VaultLock(vault):
        assert lock_path(vault).read_bytes() == b""
        assert not vault.exists()
    assert sorted(p.name for p in vault.parent.iterdir()) == ["boveda.pvlt.lock"]


def test_another_process_holds_the_lock_until_it_dies(vault: Path) -> None:
    holder = subprocess.Popen(  # noqa: S603 - fixed command, synthetic path
        [sys.executable, "-c", HOLDER, str(vault)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "ready"
        with pytest.raises(VaultLockedError):
            VaultLock(vault).acquire()

        holder.kill()  # abrupt death: no cleanup code runs in the holder
        holder.wait(timeout=10)
        with VaultLock(vault):
            pass
    finally:
        if holder.poll() is None:
            holder.kill()
            holder.wait(timeout=10)
        for stream in (holder.stdin, holder.stdout):
            if stream is not None:
                stream.close()
