"""The vault session: the only object in the program that holds the KEK.

A `Vault` exists only in the unlocked state right after `create` or `unlock`.
`lock()` (button, shutdown or inactivity) erases the KEK and drops the content.
Every change is written to disk before it becomes visible in memory, so a
failed save leaves both the file and the session as they were.
"""

from __future__ import annotations

import dataclasses
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Final

from pvlt.crypto import derive_kek, random_bytes, zeroize
from pvlt.params import CONFIG_B, M_COST_CREATE_MIN_KIB, SALT_LEN, Argon2Params
from pvlt.storage import Header, Purpose, VaultFile, atomic_save, load, write_backup
from pvlt.storage.format import VAULT_ID_LEN
from pvlt.vault import generator
from pvlt.vault.envelope import open_file, seal_file, unwrap_dek
from pvlt.vault.errors import (
    EntryNotFoundError,
    SessionLockedError,
    ValidationError,
    VaultExistsError,
)
from pvlt.vault.model import (
    MAX_ENTRIES,
    Clock,
    Content,
    Entry,
    EntrySummary,
    GeneratorSettings,
    Now,
    Settings,
    new_entry_id,
    parse_content,
    serialize_content,
    utc_now,
)

MASTER_PASSWORD_MIN_LEN: Final = 8
MASTER_PASSWORD_MAX_LEN: Final = 1024


def _encode_password(password: str, *, new: bool) -> bytes:
    """UTF-8 without normalization. Length rules apply only when a password is being set."""
    if not isinstance(password, str) or len(password) > MASTER_PASSWORD_MAX_LEN:
        raise ValidationError("password")
    if new and len(password) < MASTER_PASSWORD_MIN_LEN:
        raise ValidationError("password")
    try:
        return password.encode("utf-8")
    except UnicodeEncodeError:
        raise ValidationError("password") from None


def _derive(password: bytes, header: Header) -> bytearray:
    return derive_kek(password, header.salt, header.m_cost, header.t_cost, header.parallelism)


def _open_content(password: bytes, file: VaultFile) -> tuple[bytearray, Content]:
    """Checks 3 and 4. Returns the KEK and the content, or erases the KEK and raises."""
    kek = _derive(password, file.header)
    try:
        content = parse_content(open_file(kek, file))
    except BaseException:
        zeroize(kek)
        raise
    return kek, content


class ImportDecision(Enum):
    SKIP = "skip"
    REPLACE = "replace"
    KEEP_BOTH = "keep_both"


class ConflictReason(Enum):
    SAME_ID = "id"
    SAME_SITE_AND_USERNAME = "site_username"


@dataclass(frozen=True, slots=True, repr=False)
class ImportItem:
    entry: Entry
    conflict_id: str | None  # id of the entry already in the vault, if any
    conflict_reason: ConflictReason | None

    def __repr__(self) -> str:
        return f"ImportItem(id={self.entry.id!r}, conflict={self.conflict_reason})"


@dataclass(frozen=True, slots=True, repr=False)
class ImportPreview:
    items: tuple[ImportItem, ...]

    @property
    def conflicts(self) -> tuple[ImportItem, ...]:
        return tuple(item for item in self.items if item.conflict_id is not None)

    def __repr__(self) -> str:
        return f"ImportPreview(items={len(self.items)}, conflicts={len(self.conflicts)})"


@dataclass(frozen=True, slots=True)
class ImportResult:
    added: int = 0
    replaced: int = 0
    kept_both: int = 0
    skipped: int = 0


def _find_conflict(incoming: Entry, entries: list[Entry]) -> tuple[Entry, ConflictReason] | None:
    for existing in entries:
        if existing.id == incoming.id:
            return existing, ConflictReason.SAME_ID
    for existing in entries:
        if (existing.site, existing.username) == (incoming.site, incoming.username):
            return existing, ConflictReason.SAME_SITE_AND_USERNAME
    return None


class Vault:
    """An unlocked vault. Build it with `Vault.create` or `Vault.unlock`."""

    def __init__(
        self,
        *,
        path: Path,
        kek: bytearray,
        header: Header,
        content: Content,
        clock: Clock,
        now: Now,
    ) -> None:
        self._path = path
        self._kek: bytearray | None = kek
        self._header = header
        self._content: Content | None = content
        self._clock = clock
        self._now = now
        self._last_activity = clock()

    def __repr__(self) -> str:
        return f"Vault(locked={self._kek is None})"

    # --- Opening ------------------------------------------------------------

    @classmethod
    def create(
        cls,
        path: Path,
        password: str,
        *,
        params: Argon2Params = CONFIG_B,
        clock: Clock = time.monotonic,
        now: Now = utc_now,
    ) -> Vault:
        """Create a new empty vault at `path`. Refuses to overwrite anything."""
        secret = _encode_password(password, new=True)
        if params.m_cost < M_COST_CREATE_MIN_KIB:
            raise ValidationError("m_cost")
        if os.path.lexists(path):
            raise VaultExistsError
        header = Header(
            purpose=Purpose.VAULT,
            m_cost=params.m_cost,
            t_cost=params.t_cost,
            parallelism=params.parallelism,
            salt=random_bytes(SALT_LEN),
            vault_id=random_bytes(VAULT_ID_LEN),
            generation=1,
        )
        content = Content()
        kek = _derive(secret, header)
        try:
            atomic_save(path, seal_file(kek, header, serialize_content(content)))
        except BaseException:
            zeroize(kek)
            raise
        return cls(path=path, kek=kek, header=header, content=content, clock=clock, now=now)

    @classmethod
    def unlock(
        cls,
        path: Path,
        password: str,
        *,
        clock: Clock = time.monotonic,
        now: Now = utc_now,
    ) -> Vault:
        """Run the four checks in order. No failure writes to disk or creates a vault.

        Raises `FileNotFoundError`, `FormatError`, `CorruptedFileError`,
        `WrongPasswordError` or `TamperedContentError`.
        """
        secret = _encode_password(password, new=False)
        file = load(path, Purpose.VAULT)  # checks 1 and 2, limits validated before Argon2id
        kek, content = _open_content(secret, file)  # checks 3 and 4
        return cls(path=path, kek=kek, header=file.header, content=content, clock=clock, now=now)

    # --- Session ------------------------------------------------------------

    def lock(self) -> None:
        """Erase the KEK and forget the content. Safe to call more than once."""
        if self._kek is not None:
            zeroize(self._kek)
        self._kek = None
        self._content = None

    def _expired(self) -> bool:
        if self._kek is None or self._content is None:
            return False
        idle = self._clock() - self._last_activity
        return idle >= self._content.settings.autolock_seconds

    @property
    def is_locked(self) -> bool:
        if self._expired():
            self.lock()
        return self._kek is None

    def seconds_until_autolock(self) -> float:
        """Remaining idle time. Does not count as activity."""
        if self.is_locked or self._content is None:
            return 0.0
        idle = self._clock() - self._last_activity
        return max(0.0, self._content.settings.autolock_seconds - idle)

    def _active(self) -> tuple[bytearray, Content]:
        """Gate of every operation: enforce the inactivity lock, then count as activity."""
        if self._expired():
            self.lock()
        if self._kek is None or self._content is None:
            raise SessionLockedError
        self._last_activity = self._clock()
        return self._kek, self._content

    def _save(self, content: Content) -> None:
        """Write `content` as the next generation, then make it the session state."""
        kek, _ = self._active()
        header = dataclasses.replace(self._header, generation=self._header.generation + 1)
        atomic_save(self._path, seal_file(kek, header, serialize_content(content)))
        self._header = header
        self._content = content

    # --- Reading ------------------------------------------------------------

    @property
    def path(self) -> Path:
        return self._path

    @property
    def generation(self) -> int:
        return self._header.generation

    @property
    def settings(self) -> Settings:
        return self._active()[1].settings

    def __len__(self) -> int:
        return len(self._active()[1].entries)

    def list_entries(self, query: str = "") -> list[EntrySummary]:
        """Entries without passwords or notes, filtered by a case-insensitive substring."""
        _, content = self._active()
        needle = query.casefold()
        return [
            EntrySummary(e.id, e.site, e.username, e.modified)
            for e in content.entries
            if needle in e.site.casefold() or needle in e.username.casefold()
        ]

    def get(self, entry_id: str) -> Entry:
        _, content = self._active()
        for entry in content.entries:
            if entry.id == entry_id:
                return entry
        raise EntryNotFoundError

    # --- Changes ------------------------------------------------------------

    def add(self, *, site: str, username: str, password: str, notes: str = "") -> Entry:
        _, content = self._active()
        if len(content.entries) >= MAX_ENTRIES:
            raise ValidationError("entries")
        stamp = self._now()
        entry = Entry(
            id=new_entry_id(),
            site=site,
            username=username,
            password=password,
            notes=notes,
            created=stamp,
            modified=stamp,
        )
        self._save(dataclasses.replace(content, entries=(*content.entries, entry)))
        return entry

    def update(
        self,
        entry_id: str,
        *,
        site: str | None = None,
        username: str | None = None,
        password: str | None = None,
        notes: str | None = None,
    ) -> Entry:
        current = self.get(entry_id)
        _, content = self._active()
        updated = dataclasses.replace(
            current,
            site=current.site if site is None else site,
            username=current.username if username is None else username,
            password=current.password if password is None else password,
            notes=current.notes if notes is None else notes,
            modified=self._now(),
        )
        entries = tuple(updated if e.id == entry_id else e for e in content.entries)
        self._save(dataclasses.replace(content, entries=entries))
        return updated

    def delete(self, entry_id: str) -> None:
        self.get(entry_id)
        _, content = self._active()
        entries = tuple(e for e in content.entries if e.id != entry_id)
        self._save(dataclasses.replace(content, entries=entries))

    def update_settings(
        self,
        *,
        autolock_seconds: int | None = None,
        generator: GeneratorSettings | None = None,
    ) -> Settings:
        _, content = self._active()
        settings = Settings(
            autolock_seconds=(
                content.settings.autolock_seconds if autolock_seconds is None else autolock_seconds
            ),
            generator=content.settings.generator if generator is None else generator,
        )
        self._save(dataclasses.replace(content, settings=settings))
        return settings

    def generate_password(self, settings: GeneratorSettings | None = None) -> str:
        """Generate with the given settings, or with the ones stored in the vault."""
        _, content = self._active()
        return generator.generate(content.settings.generator if settings is None else settings)

    # --- Master password ----------------------------------------------------

    def change_password(self, current: str, new: str) -> None:
        """Re-encrypt under a new salt and KEK. Entries are untouched (section 4.5).

        The backup is rewritten too, so no file remains that the old password opens.
        """
        _, content = self._active()
        current_secret = _encode_password(current, new=False)
        new_secret = _encode_password(new, new=True)

        # Verify the current password as the design states: derive with the
        # current salt and open W of the file on disk.
        on_disk = load(self._path, Purpose.VAULT)
        candidate = _derive(current_secret, on_disk.header)
        try:
            unwrap_dek(candidate, on_disk)
        finally:
            zeroize(candidate)

        header = dataclasses.replace(
            self._header,
            salt=random_bytes(SALT_LEN),
            generation=self._header.generation + 1,
        )
        new_kek = _derive(new_secret, header)
        try:
            data = seal_file(new_kek, header, serialize_content(content))
            atomic_save(self._path, data)
        except BaseException:
            zeroize(new_kek)
            raise
        old_kek, self._kek, self._header = self._kek, new_kek, header
        if old_kek is not None:
            zeroize(old_kek)
        write_backup(self._path, data)

    # --- Export and import --------------------------------------------------

    def export(self, destination: Path, password: str, *, overwrite: bool = False) -> None:
        """Write an encrypted export with its own password, salt, KEK and vault id."""
        _, content = self._active()
        secret = _encode_password(password, new=True)
        if destination.resolve() == self._path.resolve():
            raise VaultExistsError
        if not overwrite and os.path.lexists(destination):
            raise VaultExistsError
        header = Header(
            purpose=Purpose.EXPORT,
            m_cost=self._header.m_cost,
            t_cost=self._header.t_cost,
            parallelism=self._header.parallelism,
            salt=random_bytes(SALT_LEN),
            vault_id=random_bytes(VAULT_ID_LEN),
            generation=1,
        )
        kek = _derive(secret, header)
        try:
            data = seal_file(kek, header, serialize_content(content))
        finally:
            zeroize(kek)
        atomic_save(destination, data, purpose=Purpose.EXPORT, make_backup=False)

    def import_preview(self, source: Path, password: str) -> ImportPreview:
        """Open an export (same four checks, purpose 0x02) and classify its entries.

        Nothing is written. Conflicts are entries whose id or whose
        (site, username) pair already exists in the vault.
        """
        _, content = self._active()
        secret = _encode_password(password, new=False)
        file = load(source, Purpose.EXPORT)
        kek, incoming = _open_content(secret, file)
        zeroize(kek)

        existing = list(content.entries)
        items: list[ImportItem] = []
        for entry in incoming.entries:
            conflict = _find_conflict(entry, existing)
            if conflict is None:
                items.append(ImportItem(entry, None, None))
            else:
                items.append(ImportItem(entry, conflict[0].id, conflict[1]))
        return ImportPreview(tuple(items))

    def import_apply(
        self,
        preview: ImportPreview,
        decisions: Mapping[str, ImportDecision] | None = None,
    ) -> ImportResult:
        """Merge a preview into the vault with one save.

        `decisions` maps the id of an incoming entry to what to do if it conflicts.
        A conflict without a decision is skipped. Entries without conflict are added.
        """
        _, content = self._active()
        chosen = decisions or {}
        entries = list(content.entries)
        added = replaced = kept_both = skipped = 0

        for item in preview.items:
            incoming = item.entry
            # Conflicts are recomputed against the current state: the vault may have
            # changed since the preview, and two incoming entries may collide.
            conflict = _find_conflict(incoming, entries)
            if conflict is None:
                entries.append(incoming)
                added += 1
                continue
            decision = chosen.get(incoming.id, ImportDecision.SKIP)
            if decision is ImportDecision.REPLACE:
                target = conflict[0]
                merged = dataclasses.replace(
                    incoming, id=target.id, created=target.created, modified=self._now()
                )
                entries[entries.index(target)] = merged
                replaced += 1
            elif decision is ImportDecision.KEEP_BOTH:
                entries.append(dataclasses.replace(incoming, id=new_entry_id()))
                kept_both += 1
            else:
                skipped += 1

        if len(entries) > MAX_ENTRIES:
            raise ValidationError("entries")
        if added or replaced or kept_both:
            self._save(dataclasses.replace(content, entries=tuple(entries)))
        return ImportResult(added, replaced, kept_both, skipped)
