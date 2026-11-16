"""Storage failures, one class per category. Messages are fixed and carry no file content."""

from __future__ import annotations


class StorageError(Exception):
    """Base class of every failure raised by the storage layer."""


class FormatError(StorageError):
    """Check 1 failed: the bytes are not a supported pvlt file.

    `reason` names the rule that failed (for tests and diagnosis). It is a fixed
    identifier, never a value read from the file.
    """

    def __init__(self, reason: str) -> None:
        super().__init__("Formato no reconocido")
        self.reason = reason


class CorruptedFileError(StorageError):
    """Check 2 failed: the structure is valid but the SHA-256 digest does not match."""

    def __init__(self, reason: str = "digest") -> None:
        super().__init__("Archivo dañado")
        self.reason = reason


class VaultLockedError(StorageError):
    """Another live process holds the lock of this vault."""

    def __init__(self) -> None:
        super().__init__("La bóveda ya está abierta en otro proceso")
