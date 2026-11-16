"""Reading, atomic saving, backup and recovery of vault files (docs/diseno.md, section 7).

Every byte that reaches the disk through this module is already encrypted.
Reading never writes: only `atomic_save`, `write_backup`, `recover` and
`restore_backup` modify the directory, and each one is an explicit operation.
"""

from __future__ import annotations

import contextlib
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from pvlt.storage.errors import CorruptedFileError, FormatError
from pvlt.storage.format import MAX_FILE_LEN, Purpose, VaultFile, unpack

FILE_MODE = 0o600


class SaveStep(Enum):
    """Points where a save can be interrupted. The hook runs right after each one."""

    TMP_WRITTEN = "tmp_written"  # new version written and fsynced to .tmp
    TMP_VERIFIED = "tmp_verified"  # .tmp read back, structure and digest checked
    BACKUP_TMP_WRITTEN = "backup_tmp_written"  # current version copied to .bak.tmp
    BACKUP_REPLACED = "backup_replaced"  # .bak.tmp renamed over .bak
    VAULT_REPLACED = "vault_replaced"  # .tmp renamed over the vault
    DIR_SYNCED = "dir_synced"  # directory entry flushed


FaultHook = Callable[[SaveStep], None]


def tmp_path(path: Path) -> Path:
    return path.with_name(path.name + ".tmp")


def backup_path(path: Path) -> Path:
    return path.with_name(path.name + ".bak")


def _reached(hook: FaultHook | None, step: SaveStep) -> None:
    if hook is not None:
        hook(step)


def read_bytes(path: Path) -> bytes:
    """Read a whole file, refusing anything larger than the format allows."""
    with open(path, "rb") as fh:
        data = fh.read(MAX_FILE_LEN + 1)
    if len(data) > MAX_FILE_LEN:
        raise FormatError("too_long")
    return data


def load(path: Path, expected_purpose: Purpose = Purpose.VAULT) -> VaultFile:
    """Read and parse a file (checks 1 and 2). Never writes to disk.

    Raises `FileNotFoundError` if it does not exist.
    """
    return unpack(read_bytes(path), expected_purpose)


def _write_new(path: Path, data: bytes) -> None:
    """Create `path` exclusively with mode 0600, write everything and fsync."""
    path.unlink(missing_ok=True)  # leftover of an interrupted save, we hold the lock
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    flags |= getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, FILE_MODE)
    try:
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            view = view[written:]
        os.fsync(fd)
    except OSError:
        os.close(fd)
        path.unlink(missing_ok=True)
        raise
    os.close(fd)


def _fsync_dir(directory: Path) -> None:
    if sys.platform == "win32":
        return  # directories cannot be fsynced on Windows
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _backup_current(path: Path, purpose: Purpose, hook: FaultHook | None) -> None:
    """Copy the version currently on disk to `.bak`, only if it is intact.

    A damaged current file is never copied: it would destroy the last good backup.
    """
    try:
        current = read_bytes(path)
        unpack(current, purpose)
    except (FileNotFoundError, FormatError, CorruptedFileError):
        return
    bak = backup_path(path)
    bak_tmp = tmp_path(bak)
    _write_new(bak_tmp, current)
    _reached(hook, SaveStep.BACKUP_TMP_WRITTEN)
    os.replace(bak_tmp, bak)
    _reached(hook, SaveStep.BACKUP_REPLACED)


def atomic_save(
    path: Path,
    data: bytes,
    *,
    purpose: Purpose = Purpose.VAULT,
    make_backup: bool = True,
    fault_hook: FaultHook | None = None,
) -> None:
    """Replace `path` with `data` so that a crash leaves the old or the new version, never a mix.

    `data` must be a complete serialized file. `fault_hook` exists for T7: an
    exception raised from it simulates a crash at that step, so nothing is cleaned up.
    """
    unpack(data, purpose)  # never start writing something we could not read back

    tmp = tmp_path(path)
    _write_new(tmp, data)
    _reached(fault_hook, SaveStep.TMP_WRITTEN)

    if read_bytes(tmp) != data:
        tmp.unlink(missing_ok=True)
        raise CorruptedFileError("readback")
    _reached(fault_hook, SaveStep.TMP_VERIFIED)

    if make_backup:
        _backup_current(path, purpose, fault_hook)

    os.replace(tmp, path)
    _reached(fault_hook, SaveStep.VAULT_REPLACED)

    _fsync_dir(path.parent)
    _reached(fault_hook, SaveStep.DIR_SYNCED)


def write_backup(path: Path, data: bytes, *, purpose: Purpose = Purpose.VAULT) -> None:
    """Write `data` as the backup of `path`.

    Used after a master password change, so that no backup remains that the old
    password could open (docs/diseno.md 4.5).
    """
    unpack(data, purpose)
    bak = backup_path(path)
    bak_tmp = tmp_path(bak)
    _write_new(bak_tmp, data)
    os.replace(bak_tmp, bak)
    _fsync_dir(path.parent)


# --- Recovery at startup ----------------------------------------------------


class FileStatus(Enum):
    MISSING = "missing"
    OK = "ok"  # passes checks 1 and 2
    UNRECOGNIZED = "unrecognized"  # fails check 1
    CORRUPTED = "corrupted"  # fails check 2


@dataclass(frozen=True, slots=True)
class RecoveryReport:
    removed_temporaries: tuple[Path, ...]
    vault: FileStatus
    backup: FileStatus
    vault_generation: int | None
    backup_generation: int | None

    @property
    def can_restore_backup(self) -> bool:
        """The vault cannot be read but the backup can: offer to restore it."""
        return self.vault is not FileStatus.OK and self.backup is FileStatus.OK

    @property
    def possible_rollback(self) -> bool:
        """The backup is newer than the vault: the vault may be an old copy."""
        return (
            self.vault_generation is not None
            and self.backup_generation is not None
            and self.backup_generation > self.vault_generation
        )


def _inspect(path: Path, purpose: Purpose) -> tuple[FileStatus, int | None]:
    try:
        return FileStatus.OK, load(path, purpose).header.generation
    except FileNotFoundError:
        return FileStatus.MISSING, None
    except FormatError:
        return FileStatus.UNRECOGNIZED, None
    except CorruptedFileError:
        return FileStatus.CORRUPTED, None


def recover(path: Path, *, purpose: Purpose = Purpose.VAULT) -> RecoveryReport:
    """Startup pass: delete leftover temporaries and report the state of vault and backup.

    Call it while holding the lock. It never touches the vault or the backup.
    """
    removed: list[Path] = []
    for leftover in (tmp_path(path), tmp_path(backup_path(path))):
        with contextlib.suppress(FileNotFoundError):
            leftover.unlink()
            removed.append(leftover)
    vault, vault_generation = _inspect(path, purpose)
    backup, backup_generation = _inspect(backup_path(path), purpose)
    return RecoveryReport(tuple(removed), vault, backup, vault_generation, backup_generation)


def restore_backup(path: Path, *, purpose: Purpose = Purpose.VAULT) -> Path | None:
    """Put the backup in place of the vault. The damaged file is renamed, not overwritten.

    Returns the path where the damaged file was kept, or None if there was none.
    The backup itself stays untouched.
    """
    data = read_bytes(backup_path(path))
    unpack(data, purpose)

    kept: Path | None = None
    if path.exists():
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        kept = path.with_name(f"{path.name}.damaged-{stamp}")
        counter = 1
        while kept.exists():
            kept = path.with_name(f"{path.name}.damaged-{stamp}-{counter}")
            counter += 1
        os.replace(path, kept)

    tmp = tmp_path(path)
    _write_new(tmp, data)
    os.replace(tmp, path)
    _fsync_dir(path.parent)
    return kept
