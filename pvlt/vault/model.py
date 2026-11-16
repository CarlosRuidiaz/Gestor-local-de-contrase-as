"""Vault content P (docs/diseno.md, section 5.1): entries, settings, canonical JSON and padding.

Objects of this module hold plaintext secrets. Their `repr` is overridden so a
secret can never reach a log, a traceback or an error message by accident.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from pvlt.params import PAD_BLOCK
from pvlt.vault.errors import TamperedContentError, ValidationError

SCHEMA_VERSION: Final = 1
MAX_ENTRIES: Final = 500

# Field limits in characters.
SITE_MAX: Final = 256
USERNAME_MAX: Final = 256
PASSWORD_MAX: Final = 1024
NOTES_MAX: Final = 8192

AUTOLOCK_MIN_SECONDS: Final = 30
AUTOLOCK_MAX_SECONDS: Final = 3600
AUTOLOCK_DEFAULT_SECONDS: Final = 300
GENERATOR_LENGTH_MIN: Final = 8
GENERATOR_LENGTH_MAX: Final = 128
GENERATOR_LENGTH_DEFAULT: Final = 20

_UUID4_RE: Final = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
)
_TIMESTAMP_FORMAT: Final = "%Y-%m-%dT%H:%M:%SZ"
_TIMESTAMP_RE: Final = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")

_PAD_MARK: Final = 0x80


def utc_now() -> str:
    return datetime.now(UTC).strftime(_TIMESTAMP_FORMAT)


def new_entry_id() -> str:
    return str(uuid.uuid4())  # uuid4 draws from os.urandom


# --- Field validation -------------------------------------------------------


def _check_text(field: str, value: object, *, min_len: int, max_len: int) -> str:
    if not isinstance(value, str) or not min_len <= len(value) <= max_len or "\x00" in value:
        raise ValidationError(field)
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise ValidationError(field) from None  # lone surrogates cannot be stored
    return value


def _check_bool(field: str, value: object) -> bool:
    if type(value) is not bool:
        raise ValidationError(field)
    return value


def _check_int(field: str, value: object, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValidationError(field)
    return value


def _check_timestamp(field: str, value: object) -> str:
    if not isinstance(value, str) or _TIMESTAMP_RE.fullmatch(value) is None:
        raise ValidationError(field)
    try:
        datetime.strptime(value, _TIMESTAMP_FORMAT)
    except ValueError:
        raise ValidationError(field) from None
    return value


# --- Data model -------------------------------------------------------------


@dataclass(frozen=True, slots=True, repr=False)
class Entry:
    id: str
    site: str
    username: str
    password: str
    notes: str
    created: str
    modified: str

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or _UUID4_RE.fullmatch(self.id) is None:
            raise ValidationError("id")
        _check_text("site", self.site, min_len=1, max_len=SITE_MAX)
        _check_text("username", self.username, min_len=0, max_len=USERNAME_MAX)
        _check_text("password", self.password, min_len=1, max_len=PASSWORD_MAX)
        _check_text("notes", self.notes, min_len=0, max_len=NOTES_MAX)
        _check_timestamp("created", self.created)
        _check_timestamp("modified", self.modified)

    def __repr__(self) -> str:
        return f"Entry(id={self.id!r})"


@dataclass(frozen=True, slots=True)
class EntrySummary:
    """What a listing shows. It deliberately has no password and no notes."""

    id: str
    site: str
    username: str
    modified: str

    def __repr__(self) -> str:
        return f"EntrySummary(id={self.id!r})"


@dataclass(frozen=True, slots=True)
class GeneratorSettings:
    length: int = GENERATOR_LENGTH_DEFAULT
    lower: bool = True
    upper: bool = True
    digits: bool = True
    symbols: bool = True

    def __post_init__(self) -> None:
        _check_int("generator.length", self.length, GENERATOR_LENGTH_MIN, GENERATOR_LENGTH_MAX)
        flags = [
            _check_bool(f"generator.{name}", getattr(self, name))
            for name in ("lower", "upper", "digits", "symbols")
        ]
        if not any(flags):
            raise ValidationError("generator.classes")


@dataclass(frozen=True, slots=True)
class Settings:
    autolock_seconds: int = AUTOLOCK_DEFAULT_SECONDS
    generator: GeneratorSettings = GeneratorSettings()

    def __post_init__(self) -> None:
        _check_int(
            "autolock_seconds", self.autolock_seconds, AUTOLOCK_MIN_SECONDS, AUTOLOCK_MAX_SECONDS
        )
        if not isinstance(self.generator, GeneratorSettings):
            raise ValidationError("generator")


@dataclass(frozen=True, slots=True, repr=False)
class Content:
    entries: tuple[Entry, ...] = ()
    settings: Settings = Settings()

    def __post_init__(self) -> None:
        if len(self.entries) > MAX_ENTRIES:
            raise ValidationError("entries")
        if len({e.id for e in self.entries}) != len(self.entries):
            raise ValidationError("entries")

    def __repr__(self) -> str:
        return f"Content(entries={len(self.entries)})"


# --- Canonical JSON ---------------------------------------------------------

_ENTRY_KEYS: Final = frozenset(
    {"id", "site", "username", "password", "notes", "created", "modified"}
)
_GENERATOR_KEYS: Final = frozenset({"length", "lower", "upper", "digits", "symbols"})


def serialize_content(content: Content) -> bytes:
    """Canonical UTF-8 JSON: sorted keys, no whitespace, non-ASCII kept as is."""
    obj = {
        "schema": SCHEMA_VERSION,
        "entries": [
            {
                "id": e.id,
                "site": e.site,
                "username": e.username,
                "password": e.password,
                "notes": e.notes,
                "created": e.created,
                "modified": e.modified,
            }
            for e in content.entries
        ],
        "settings": {
            "autolock_seconds": content.settings.autolock_seconds,
            "generator": {
                "length": content.settings.generator.length,
                "lower": content.settings.generator.lower,
                "upper": content.settings.generator.upper,
                "digits": content.settings.generator.digits,
                "symbols": content.settings.generator.symbols,
            },
        },
    }
    text = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return text.encode("utf-8")


class _Invalid(Exception):
    """Internal: the decrypted bytes are not a valid content. Never leaves this module."""


def _no_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    out: dict[str, object] = {}
    for key, value in pairs:
        if key in out:
            raise _Invalid
        out[key] = value
    return out


def _reject_constant(_name: str) -> object:
    raise _Invalid  # NaN and Infinity are not JSON


def _as_object(value: object, keys: frozenset[str]) -> dict[str, object]:
    if not isinstance(value, dict) or frozenset(value) != keys:
        raise _Invalid
    return value


def _parse(data: bytes) -> Content:
    try:
        text = data.decode("utf-8")
        root = json.loads(
            text, object_pairs_hook=_no_duplicate_keys, parse_constant=_reject_constant
        )
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise _Invalid from None

    top = _as_object(root, frozenset({"schema", "entries", "settings"}))
    if type(top["schema"]) is not int or top["schema"] != SCHEMA_VERSION:
        raise _Invalid
    raw_entries = top["entries"]
    if not isinstance(raw_entries, list) or len(raw_entries) > MAX_ENTRIES:
        raise _Invalid

    try:
        entries = tuple(
            Entry(**_as_object(raw, _ENTRY_KEYS))  # type: ignore[arg-type]
            for raw in raw_entries
        )
        raw_settings = _as_object(top["settings"], frozenset({"autolock_seconds", "generator"}))
        raw_generator = _as_object(raw_settings["generator"], _GENERATOR_KEYS)
        settings = Settings(
            autolock_seconds=raw_settings["autolock_seconds"],  # type: ignore[arg-type]
            generator=GeneratorSettings(**raw_generator),  # type: ignore[arg-type]
        )
        content = Content(entries=entries, settings=settings)
    except ValidationError:
        raise _Invalid from None

    # Unambiguous serialization: only the canonical encoding of a content is accepted.
    if serialize_content(content) != data:
        raise _Invalid
    return content


def parse_content(data: bytes) -> Content:
    """Strict inverse of `serialize_content`. Anything else is `TamperedContentError`."""
    try:
        return _parse(data)
    except _Invalid:
        raise TamperedContentError("schema") from None


# --- Padding ----------------------------------------------------------------


def pad(data: bytes) -> bytes:
    """`data || 0x80 || 0x00 * k`, with the smallest k that reaches a multiple of 4096."""
    k = -(len(data) + 1) % PAD_BLOCK
    return data + bytes([_PAD_MARK]) + bytes(k)


def unpad(padded: bytes) -> bytes:
    """Strict removal: the last 0x80 must be followed only by zeros, inside the last block."""
    if len(padded) == 0 or len(padded) % PAD_BLOCK != 0:
        raise TamperedContentError("padding")
    stripped = padded.rstrip(b"\x00")
    if not stripped or stripped[-1] != _PAD_MARK or len(padded) - len(stripped) >= PAD_BLOCK:
        raise TamperedContentError("padding")
    return stripped[:-1]


Clock = Callable[[], float]
Now = Callable[[], str]
