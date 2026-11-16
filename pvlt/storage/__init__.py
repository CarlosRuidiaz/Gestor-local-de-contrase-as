"""Binary format v1, limit validation, atomic save, backup and lock.

Never receives keys or plaintext.
"""

from pvlt.storage.errors import CorruptedFileError, FormatError, StorageError, VaultLockedError
from pvlt.storage.format import Header, Purpose, VaultFile, unpack
from pvlt.storage.lock import VaultLock
from pvlt.storage.store import (
    FileStatus,
    RecoveryReport,
    SaveStep,
    atomic_save,
    backup_path,
    load,
    recover,
    restore_backup,
    write_backup,
)

__all__ = [
    "CorruptedFileError",
    "FileStatus",
    "FormatError",
    "Header",
    "Purpose",
    "RecoveryReport",
    "SaveStep",
    "StorageError",
    "VaultFile",
    "VaultLock",
    "VaultLockedError",
    "atomic_save",
    "backup_path",
    "load",
    "recover",
    "restore_backup",
    "unpack",
    "write_backup",
]
