"""Single-process access to a vault (docs/diseno.md, section 7, step 1).

The lock is an advisory lock held by the kernel on an open descriptor of
`<vault>.lock`. The kernel releases it when the process ends, however it ends,
so a crash can never leave the vault locked. The file itself is empty, stays on
disk between runs and holds no information.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import TracebackType

from pvlt.storage.errors import VaultLockedError


def lock_path(vault_path: Path) -> Path:
    return vault_path.with_name(vault_path.name + ".lock")


def _try_lock(fd: int) -> None:
    """Take an exclusive lock without waiting. Raises OSError if someone else holds it."""
    if sys.platform == "win32":
        import msvcrt

        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(fd: int) -> None:
    if sys.platform == "win32":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_UN)


class VaultLock:
    """Exclusive lock over one vault path. Usable as a context manager."""

    def __init__(self, vault_path: Path) -> None:
        self._path = lock_path(vault_path)
        self._fd: int | None = None

    @property
    def held(self) -> bool:
        return self._fd is not None

    def acquire(self) -> None:
        """Take the lock or raise `VaultLockedError` if a live process holds it."""
        if self._fd is not None:
            return
        fd = os.open(self._path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            _try_lock(fd)
        except OSError:
            os.close(fd)
            raise VaultLockedError from None
        self._fd = fd

    def release(self) -> None:
        if self._fd is None:
            return
        fd, self._fd = self._fd, None
        try:
            _unlock(fd)
        finally:
            os.close(fd)

    def __enter__(self) -> VaultLock:
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()
