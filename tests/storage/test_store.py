"""Atomic save, backup and recovery (T7), plus the no-write guarantee of failed opens (T4)."""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

from pvlt.storage import (
    CorruptedFileError,
    FileStatus,
    FormatError,
    Purpose,
    SaveStep,
    atomic_save,
    backup_path,
    load,
    recover,
    restore_backup,
    store,
    write_backup,
)
from tests.storage.helpers import flip_bit, make_file

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")


class SimulatedCrash(Exception):
    """Raised from the fault hook: the process dies at that step, nothing is cleaned up."""


def crash_at(step: SaveStep) -> store.FaultHook:
    def hook(reached: SaveStep) -> None:
        if reached is step:
            raise SimulatedCrash(step.value)

    return hook


def snapshot(directory: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(directory.iterdir())}


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    return tmp_path / "boveda.pvlt"


# --- Normal saves -----------------------------------------------------------


def test_first_save_creates_only_the_vault(vault: Path) -> None:
    v1 = make_file(generation=1)
    atomic_save(vault, v1.pack())
    assert load(vault) == v1
    assert sorted(p.name for p in vault.parent.iterdir()) == ["boveda.pvlt"]


def test_second_save_keeps_the_previous_version_as_backup(vault: Path) -> None:
    v1, v2, v3 = (make_file(generation=g) for g in (1, 2, 3))
    atomic_save(vault, v1.pack())
    atomic_save(vault, v2.pack())
    assert load(vault) == v2
    assert load(backup_path(vault)) == v1
    atomic_save(vault, v3.pack())
    assert load(vault) == v3
    assert load(backup_path(vault)) == v2
    assert sorted(p.name for p in vault.parent.iterdir()) == ["boveda.pvlt", "boveda.pvlt.bak"]


def test_all_steps_are_reported_in_order(vault: Path) -> None:
    atomic_save(vault, make_file(generation=1).pack())
    seen: list[SaveStep] = []
    atomic_save(vault, make_file(generation=2).pack(), fault_hook=seen.append)
    assert seen == list(SaveStep)


@posix_only
def test_files_are_created_with_mode_0600(vault: Path) -> None:
    old_umask = os.umask(0)  # prove the mode does not depend on a friendly umask
    try:
        atomic_save(vault, make_file(generation=1).pack())
        atomic_save(vault, make_file(generation=2).pack())
    finally:
        os.umask(old_umask)
    for path in (vault, backup_path(vault)):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


@posix_only
def test_temporary_is_created_with_mode_0600(vault: Path) -> None:
    modes: list[int] = []

    def hook(step: SaveStep) -> None:
        if step is SaveStep.TMP_WRITTEN:
            modes.append(stat.S_IMODE(store.tmp_path(vault).stat().st_mode))

    old_umask = os.umask(0)
    try:
        atomic_save(vault, make_file().pack(), fault_hook=hook)
    finally:
        os.umask(old_umask)
    assert modes == [0o600]


def test_save_refuses_data_that_is_not_a_valid_file(vault: Path) -> None:
    v1 = make_file(generation=1)
    atomic_save(vault, v1.pack())
    before = snapshot(vault.parent)
    with pytest.raises(FormatError):
        atomic_save(vault, b"not a vault")
    with pytest.raises(CorruptedFileError):
        atomic_save(vault, flip_bit(make_file(generation=2).pack(), 200))
    with pytest.raises(FormatError):
        atomic_save(vault, make_file(purpose=Purpose.EXPORT).pack())
    assert snapshot(vault.parent) == before


def test_stale_temporary_does_not_block_a_save(vault: Path) -> None:
    store.tmp_path(vault).write_bytes(b"leftover of a crashed run")
    v1 = make_file()
    atomic_save(vault, v1.pack())
    assert load(vault) == v1
    assert not store.tmp_path(vault).exists()


def test_export_is_saved_without_backup(tmp_path: Path) -> None:
    target = tmp_path / "export.pvlt"
    e1 = make_file(purpose=Purpose.EXPORT)
    e2 = make_file(purpose=Purpose.EXPORT)
    atomic_save(target, e1.pack(), purpose=Purpose.EXPORT, make_backup=False)
    atomic_save(target, e2.pack(), purpose=Purpose.EXPORT, make_backup=False)
    assert load(target, Purpose.EXPORT) == e2
    assert sorted(p.name for p in tmp_path.iterdir()) == ["export.pvlt"]


def test_write_backup_replaces_the_backup(vault: Path) -> None:
    v1, v2 = make_file(generation=1), make_file(generation=2)
    atomic_save(vault, v1.pack())
    atomic_save(vault, v2.pack())
    write_backup(vault, v2.pack())
    assert load(backup_path(vault)) == v2
    assert load(vault) == v2


# --- T7: interrupt the save after every step --------------------------------

BEFORE_REPLACE = [
    SaveStep.TMP_WRITTEN,
    SaveStep.TMP_VERIFIED,
    SaveStep.BACKUP_TMP_WRITTEN,
    SaveStep.BACKUP_REPLACED,
]
AFTER_REPLACE = [SaveStep.VAULT_REPLACED, SaveStep.DIR_SYNCED]


@pytest.mark.parametrize("step", list(SaveStep), ids=lambda s: s.value)
def test_crash_at_any_step_leaves_an_intact_version(vault: Path, step: SaveStep) -> None:
    v0, v1, v2 = (make_file(generation=g) for g in (1, 2, 3))
    atomic_save(vault, v0.pack())
    atomic_save(vault, v1.pack())  # disk: vault = v1, backup = v0

    with pytest.raises(SimulatedCrash):
        atomic_save(vault, v2.pack(), fault_hook=crash_at(step))

    # Even before recovery the vault is a complete version, never a mix.
    assert load(vault) in (v1, v2)

    report = recover(vault)
    assert report.vault is FileStatus.OK
    assert report.backup is FileStatus.OK
    assert not report.can_restore_backup
    assert not report.possible_rollback

    expected = v1 if step in BEFORE_REPLACE else v2
    assert load(vault) == expected
    # The backup is always one of the two previous good versions.
    assert load(backup_path(vault)) in (v0, v1)
    if step in AFTER_REPLACE:
        assert load(backup_path(vault)) == v1
    # No temporaries survive recovery.
    assert sorted(p.name for p in vault.parent.iterdir()) == ["boveda.pvlt", "boveda.pvlt.bak"]


@pytest.mark.parametrize("step", list(SaveStep), ids=lambda s: s.value)
def test_save_can_be_retried_after_a_crash(vault: Path, step: SaveStep) -> None:
    v1, v2 = make_file(generation=1), make_file(generation=2)
    atomic_save(vault, v1.pack())
    with pytest.raises(SimulatedCrash):
        atomic_save(vault, v2.pack(), fault_hook=crash_at(step))
    recover(vault)
    atomic_save(vault, v2.pack())
    assert load(vault) == v2


def test_crash_on_the_very_first_save_leaves_no_vault(vault: Path) -> None:
    with pytest.raises(SimulatedCrash):
        atomic_save(vault, make_file().pack(), fault_hook=crash_at(SaveStep.TMP_VERIFIED))
    report = recover(vault)
    assert report.removed_temporaries == (store.tmp_path(vault),)
    assert report.vault is FileStatus.MISSING
    assert report.backup is FileStatus.MISSING
    assert not report.can_restore_backup
    assert list(vault.parent.iterdir()) == []


def test_recover_reports_what_it_removed(vault: Path) -> None:
    atomic_save(vault, make_file(generation=1).pack())
    with pytest.raises(SimulatedCrash):
        atomic_save(
            vault,
            make_file(generation=2).pack(),
            fault_hook=crash_at(SaveStep.BACKUP_TMP_WRITTEN),
        )
    report = recover(vault)
    assert set(report.removed_temporaries) == {
        store.tmp_path(vault),
        store.tmp_path(backup_path(vault)),
    }
    assert recover(vault).removed_temporaries == ()


def test_write_failure_removes_the_partial_temporary(
    vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real I/O error (disk full) is not a crash: the partial temporary is cleaned up."""
    v1 = make_file(generation=1)
    atomic_save(vault, v1.pack())
    before = snapshot(vault.parent)

    def failing_fsync(fd: int) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "fsync", failing_fsync)
    with pytest.raises(OSError, match="No space left"):
        atomic_save(vault, make_file(generation=2).pack())
    monkeypatch.undo()
    assert snapshot(vault.parent) == before


def test_readback_mismatch_aborts_before_touching_the_vault(
    vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Step 4: what reached the disk is verified before it replaces anything."""
    v1 = make_file(generation=1)
    atomic_save(vault, v1.pack())
    before = snapshot(vault.parent)
    real_read = store.read_bytes

    def lying_read(path: Path) -> bytes:
        data = real_read(path)
        return flip_bit(data, 300) if path == store.tmp_path(vault) else data

    monkeypatch.setattr(store, "read_bytes", lying_read)
    with pytest.raises(CorruptedFileError) as info:
        atomic_save(vault, make_file(generation=2).pack())
    assert info.value.reason == "readback"
    monkeypatch.undo()
    assert snapshot(vault.parent) == before


# --- T7: damaged bytes without recomputing the digest ------------------------


def damage(path: Path, index: int = 500) -> bytes:
    data = flip_bit(path.read_bytes(), index)
    path.write_bytes(data)
    return data


def test_damaged_vault_is_detected_and_restored_from_backup(vault: Path) -> None:
    v1, v2 = make_file(generation=1), make_file(generation=2)
    atomic_save(vault, v1.pack())
    atomic_save(vault, v2.pack())
    damaged_bytes = damage(vault)

    with pytest.raises(CorruptedFileError):
        load(vault)
    report = recover(vault)
    assert report.vault is FileStatus.CORRUPTED
    assert report.backup is FileStatus.OK
    assert report.can_restore_backup
    assert report.backup_generation == 1

    kept = restore_backup(vault)
    assert load(vault) == v1
    assert load(backup_path(vault)) == v1  # the backup is not consumed
    assert kept is not None
    assert kept.name.startswith("boveda.pvlt.damaged-")
    assert kept.read_bytes() == damaged_bytes  # kept for analysis, not overwritten
    assert not store.tmp_path(vault).exists()


def test_unrecognized_vault_is_also_restorable(vault: Path) -> None:
    v1, v2 = make_file(generation=1), make_file(generation=2)
    atomic_save(vault, v1.pack())
    atomic_save(vault, v2.pack())
    vault.write_bytes(vault.read_bytes()[:1000])  # truncated by a disk fault
    report = recover(vault)
    assert report.vault is FileStatus.UNRECOGNIZED
    assert report.can_restore_backup
    restore_backup(vault)
    assert load(vault) == v1


def test_two_restores_keep_both_damaged_files(vault: Path) -> None:
    atomic_save(vault, make_file(generation=1).pack())
    atomic_save(vault, make_file(generation=2).pack())
    damage(vault)
    first = restore_backup(vault)
    damage(vault)
    second = restore_backup(vault)
    assert first is not None
    assert second is not None
    assert first != second
    assert first.exists()
    assert second.exists()


def test_restore_refuses_a_damaged_backup(vault: Path) -> None:
    atomic_save(vault, make_file(generation=1).pack())
    atomic_save(vault, make_file(generation=2).pack())
    damage(vault)
    damage(backup_path(vault))
    report = recover(vault)
    assert report.vault is FileStatus.CORRUPTED
    assert report.backup is FileStatus.CORRUPTED
    assert not report.can_restore_backup
    before = snapshot(vault.parent)
    with pytest.raises(CorruptedFileError):
        restore_backup(vault)
    assert snapshot(vault.parent) == before


def test_missing_vault_with_good_backup_can_be_restored(vault: Path) -> None:
    v1 = make_file(generation=1)
    atomic_save(vault, v1.pack())
    atomic_save(vault, make_file(generation=2).pack())
    vault.unlink()
    assert recover(vault).can_restore_backup
    assert restore_backup(vault) is None
    assert load(vault) == v1


def test_a_damaged_vault_is_never_copied_over_a_good_backup(vault: Path) -> None:
    v1, v2, v3 = (make_file(generation=g) for g in (1, 2, 3))
    atomic_save(vault, v1.pack())
    atomic_save(vault, v2.pack())  # backup = v1
    damage(vault)
    atomic_save(vault, v3.pack())
    assert load(vault) == v3
    assert load(backup_path(vault)) == v1


def test_rollback_warning_when_backup_is_newer(vault: Path) -> None:
    old, new = make_file(generation=3), make_file(generation=9)
    atomic_save(vault, new.pack())
    write_backup(vault, new.pack())
    vault.write_bytes(old.pack())  # someone put back an older, valid copy
    report = recover(vault)
    assert report.vault is FileStatus.OK
    assert (report.vault_generation, report.backup_generation) == (3, 9)
    assert report.possible_rollback
    assert not report.can_restore_backup


# --- T4: a failed open never writes ------------------------------------------


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"not a vault",
        make_file().pack()[:2000],
        make_file().pack() + b"\x00",
        flip_bit(make_file().pack(), 500),
        make_file(purpose=Purpose.EXPORT).pack(),
    ],
    ids=["empty", "garbage", "truncated", "trailing", "bitflip", "export"],
)
def test_failed_load_leaves_the_directory_untouched(vault: Path, content: bytes) -> None:
    vault.write_bytes(content)
    before = snapshot(vault.parent)
    with pytest.raises((FormatError, CorruptedFileError)):
        load(vault)
    assert snapshot(vault.parent) == before
    assert not store.tmp_path(vault).exists()


def test_loading_a_missing_vault_creates_nothing(vault: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load(vault)
    assert list(vault.parent.iterdir()) == []


def test_oversized_file_is_rejected_without_reading_it_whole(vault: Path) -> None:
    with open(vault, "wb") as fh:
        fh.truncate(store.MAX_FILE_LEN + 10)
    with pytest.raises(FormatError) as info:
        load(vault)
    assert info.value.reason == "too_long"
