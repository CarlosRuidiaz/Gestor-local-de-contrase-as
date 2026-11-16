"""Startup: lock for the whole process, recovery report and restore of the backup."""

from __future__ import annotations

from pathlib import Path

import pytest

from pvlt.storage import CorruptedFileError, FileStatus, VaultLockedError
from pvlt.vault import Vault, Workspace
from tests.storage.helpers import flip_bit
from tests.vault.conftest import reopen, snapshot, synthetic_entry


def test_only_one_workspace_per_vault(vault_path: Path) -> None:
    with Workspace(vault_path) as first:
        assert first.report.vault is FileStatus.MISSING
        with pytest.raises(VaultLockedError):
            Workspace(vault_path)
    with Workspace(vault_path):
        pass  # released on exit


def test_workspace_does_not_create_a_vault(vault_path: Path) -> None:
    with Workspace(vault_path):
        pass
    assert sorted(p.name for p in vault_path.parent.iterdir()) == ["boveda.pvlt.lock"]


def test_startup_removes_leftover_temporaries(vault: Vault, vault_path: Path) -> None:
    vault.add(**synthetic_entry(1))
    vault.lock()
    leftover = vault_path.with_name("boveda.pvlt.tmp")
    leftover.write_bytes(b"leftover of an interrupted save")
    with Workspace(vault_path) as ws:
        assert ws.report.removed_temporaries == (leftover,)
        assert ws.report.vault is FileStatus.OK
        assert not ws.report.can_restore_backup
    assert not leftover.exists()
    assert len(reopen(vault_path)) == 1


def test_damaged_vault_is_restored_from_backup_on_request(vault: Vault, vault_path: Path) -> None:
    first = vault.add(**synthetic_entry(1))
    vault.add(**synthetic_entry(2))
    vault.lock()
    vault_path.write_bytes(flip_bit(vault_path.read_bytes(), 700))

    with Workspace(vault_path) as ws:
        assert ws.report.vault is FileStatus.CORRUPTED
        assert ws.report.can_restore_backup

        # Opening fails and, by itself, restores nothing.
        before = snapshot(vault_path.parent)
        with pytest.raises(CorruptedFileError):
            reopen(vault_path)
        assert snapshot(vault_path.parent) == before

        kept = ws.restore_backup()
        assert kept is not None
        assert kept.exists()
        assert ws.report.vault is FileStatus.OK
        assert not ws.report.can_restore_backup

    restored = reopen(vault_path)
    assert len(restored) == 1  # the last intact version, one save behind
    assert restored.get(first.id) == first


def test_rollback_is_warned_about(vault: Vault, vault_path: Path) -> None:
    vault.add(**synthetic_entry(1))
    old_copy = vault_path.read_bytes()  # generation 2
    vault.add(**synthetic_entry(2))
    vault.add(**synthetic_entry(3))  # vault generation 4, backup generation 3
    vault.lock()
    vault_path.write_bytes(old_copy)  # an older but valid copy is put back

    with Workspace(vault_path) as ws:
        assert ws.report.vault is FileStatus.OK
        assert (ws.report.vault_generation, ws.report.backup_generation) == (2, 3)
        assert ws.report.possible_rollback
    assert len(reopen(vault_path)) == 1  # it opens: rollback is only warned about
