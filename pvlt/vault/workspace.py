"""Process-level handle of a vault path (docs/diseno.md, section 7).

The program opens one `Workspace` at startup, before any vault operation. It
holds the lock for the whole life of the process and runs the recovery pass,
whose report tells the interface whether to offer the backup or warn about a
possible rollback. It never sees a password or a key.
"""

from __future__ import annotations

from pathlib import Path
from types import TracebackType

from pvlt.storage import RecoveryReport, VaultLock, recover, restore_backup


class Workspace:
    def __init__(self, path: Path) -> None:
        """Take the lock (`VaultLockedError` if another process has it) and recover."""
        self.path = path
        self._lock = VaultLock(path)
        self._lock.acquire()
        try:
            self.report: RecoveryReport = recover(path)
        except BaseException:
            self._lock.release()
            raise

    def restore_backup(self) -> Path | None:
        """Put the backup in place of an unreadable vault. Only on explicit user request.

        Returns where the damaged file was kept. The report is refreshed.
        """
        kept = restore_backup(self.path)
        self.report = recover(self.path)
        return kept

    def refresh(self) -> RecoveryReport:
        self.report = recover(self.path)
        return self.report

    def close(self) -> None:
        self._lock.release()

    def __enter__(self) -> Workspace:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
