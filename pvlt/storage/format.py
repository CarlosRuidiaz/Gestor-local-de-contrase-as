"""Binary format v1 (docs/diseno.md, section 5): layout, serialization and checks 1 and 2.

This module only sees public metadata and ciphertext. It never receives a key
or plaintext, and it never decides whether a file is authentic: that depends
on the AEAD tags, which only the vault layer can verify.
"""

from __future__ import annotations

import hmac
import struct
from dataclasses import dataclass
from enum import IntEnum
from typing import Final

from cryptography.hazmat.primitives import hashes

from pvlt.params import (
    ARGON2_VERSION,
    C_LEN_MAX,
    C_LEN_MIN,
    KEY_LEN,
    NONCE_LEN,
    PAD_BLOCK,
    SALT_LEN,
    TAG_LEN,
    argon2_limit_violation,
)
from pvlt.storage.errors import CorruptedFileError, FormatError

MAGIC: Final = b"PVLT"
FORMAT_VERSION: Final = 1
KDF_ID_ARGON2ID: Final = 0x01
AEAD_ID_CHACHA20_POLY1305: Final = 0x01
VAULT_ID_LEN: Final = 16
WRAPPED_KEY_LEN: Final = KEY_LEN + TAG_LEN  # 48
DIGEST_LEN: Final = 32
GENERATION_MAX: Final = 2**64 - 1


class Purpose(IntEnum):
    VAULT = 0x01
    EXPORT = 0x02


@dataclass(frozen=True, slots=True)
class Field:
    """Half-open byte range [start, end) of a field inside the file."""

    name: str
    start: int
    end: int

    @property
    def size(self) -> int:
        return self.end - self.start


def _layout(specs: tuple[tuple[str, int], ...], origin: int = 0) -> tuple[Field, ...]:
    fields: list[Field] = []
    offset = origin
    for name, size in specs:
        fields.append(Field(name, offset, offset + size))
        offset += size
    return tuple(fields)


# Single source of truth for the offsets. Serialization, parsing and the
# tampering tests (T5) are all driven by these two tables.
HEADER_FIELDS: Final = _layout(
    (
        ("magic", 4),
        ("format_version", 2),
        ("purpose", 1),
        ("kdf_id", 1),
        ("kdf_version", 1),
        ("m_cost", 4),
        ("t_cost", 4),
        ("parallelism", 1),
        ("salt", SALT_LEN),
        ("aead_id", 1),
        ("vault_id", VAULT_ID_LEN),
        ("generation", 8),
    )
)
HEADER_LEN: Final = HEADER_FIELDS[-1].end  # 59

ENVELOPE_FIELDS: Final = _layout(
    (
        ("nonce_w", NONCE_LEN),
        ("wrapped_key", WRAPPED_KEY_LEN),
        ("nonce_d", NONCE_LEN),
        ("len_c", 4),
    ),
    origin=HEADER_LEN,
)
FIXED_LEN: Final = ENVELOPE_FIELDS[-1].end  # 135

FIXED_FIELDS: Final = HEADER_FIELDS + ENVELOPE_FIELDS
FIELD: Final = {f.name: f for f in FIXED_FIELDS}

MIN_FILE_LEN: Final = FIXED_LEN + C_LEN_MIN + DIGEST_LEN
MAX_FILE_LEN: Final = FIXED_LEN + C_LEN_MAX + DIGEST_LEN

_HEADER_STRUCT: Final = struct.Struct(f">4sHBBBIIB{SALT_LEN}sB{VAULT_ID_LEN}sQ")
_ENVELOPE_STRUCT: Final = struct.Struct(f">{NONCE_LEN}s{WRAPPED_KEY_LEN}s{NONCE_LEN}sI")


def file_fields(len_c: int) -> tuple[Field, ...]:
    """Every field of a file whose ciphertext is `len_c` bytes long, in order."""
    return FIXED_FIELDS + _layout((("ciphertext", len_c), ("digest", DIGEST_LEN)), FIXED_LEN)


def sha256(data: bytes) -> bytes:
    digest = hashes.Hash(hashes.SHA256())
    digest.update(data)
    return digest.finalize()


def _len_c_violation(len_c: int) -> bool:
    return not C_LEN_MIN <= len_c <= C_LEN_MAX or (len_c - TAG_LEN) % PAD_BLOCK != 0


@dataclass(frozen=True, slots=True)
class Header:
    """The 59 authenticated header bytes. Everything in it is public."""

    purpose: Purpose
    m_cost: int
    t_cost: int
    parallelism: int
    salt: bytes
    vault_id: bytes
    generation: int

    def __post_init__(self) -> None:
        # Refuse to build (and therefore to write) a header that check 1 would reject.
        if len(self.salt) != SALT_LEN:
            raise ValueError("salt must be 16 bytes")
        if len(self.vault_id) != VAULT_ID_LEN:
            raise ValueError("vault_id must be 16 bytes")
        if not 1 <= self.generation <= GENERATION_MAX:
            raise ValueError("generation out of range")
        violation = argon2_limit_violation(self.m_cost, self.t_cost, self.parallelism)
        if violation is not None:
            raise ValueError(f"{violation} out of range")

    def pack(self) -> bytes:
        """Exact bytes written to disk and used as associated data (`Hdr`)."""
        return _HEADER_STRUCT.pack(
            MAGIC,
            FORMAT_VERSION,
            int(self.purpose),
            KDF_ID_ARGON2ID,
            ARGON2_VERSION,
            self.m_cost,
            self.t_cost,
            self.parallelism,
            self.salt,
            AEAD_ID_CHACHA20_POLY1305,
            self.vault_id,
            self.generation,
        )


@dataclass(frozen=True, slots=True)
class VaultFile:
    """A complete file: header, wrapped DEK and encrypted content."""

    header: Header
    nonce_w: bytes
    wrapped_key: bytes
    nonce_d: bytes
    ciphertext: bytes

    def __post_init__(self) -> None:
        if len(self.nonce_w) != NONCE_LEN or len(self.nonce_d) != NONCE_LEN:
            raise ValueError("nonces must be 12 bytes")
        if len(self.wrapped_key) != WRAPPED_KEY_LEN:
            raise ValueError("wrapped key must be 48 bytes")
        if _len_c_violation(len(self.ciphertext)):
            raise ValueError("ciphertext length out of range")

    def pack(self) -> bytes:
        body = b"".join(
            (
                self.header.pack(),
                _ENVELOPE_STRUCT.pack(
                    self.nonce_w, self.wrapped_key, self.nonce_d, len(self.ciphertext)
                ),
                self.ciphertext,
            )
        )
        return body + sha256(body)


def unpack(data: bytes, expected_purpose: Purpose) -> VaultFile:
    """Parse a file applying check 1 (`FormatError`) and then check 2 (`CorruptedFileError`).

    Passing both checks only means the file is well formed and not accidentally
    damaged. Acceptance still depends on checks 3 and 4 in the vault layer.
    """
    # --- Check 1: structure, identifiers and limits -------------------------
    if len(data) < MIN_FILE_LEN:
        raise FormatError("too_short")
    if len(data) > MAX_FILE_LEN:
        raise FormatError("too_long")

    (
        magic,
        format_version,
        purpose,
        kdf_id,
        kdf_version,
        m_cost,
        t_cost,
        parallelism,
        salt,
        aead_id,
        vault_id,
        generation,
    ) = _HEADER_STRUCT.unpack_from(data, 0)
    if magic != MAGIC:
        raise FormatError("magic")
    if format_version != FORMAT_VERSION:
        raise FormatError("format_version")
    if purpose != expected_purpose:
        raise FormatError("purpose")
    if kdf_id != KDF_ID_ARGON2ID:
        raise FormatError("kdf_id")
    if kdf_version != ARGON2_VERSION:
        raise FormatError("kdf_version")
    if aead_id != AEAD_ID_CHACHA20_POLY1305:
        raise FormatError("aead_id")
    violation = argon2_limit_violation(m_cost, t_cost, parallelism)
    if violation is not None:
        raise FormatError(violation)
    if generation < 1:
        raise FormatError("generation")

    nonce_w, wrapped_key, nonce_d, len_c = _ENVELOPE_STRUCT.unpack_from(data, HEADER_LEN)
    if _len_c_violation(len_c):
        raise FormatError("len_c")
    if len(data) != FIXED_LEN + len_c + DIGEST_LEN:
        raise FormatError("total_length")

    # --- Check 2: accidental damage -----------------------------------------
    body_end = FIXED_LEN + len_c
    if not hmac.compare_digest(sha256(data[:body_end]), data[body_end:]):
        raise CorruptedFileError

    return VaultFile(
        header=Header(
            purpose=Purpose(purpose),
            m_cost=m_cost,
            t_cost=t_cost,
            parallelism=parallelism,
            salt=salt,
            vault_id=vault_id,
            generation=generation,
        ),
        nonce_w=nonce_w,
        wrapped_key=wrapped_key,
        nonce_d=nonce_d,
        ciphertext=data[FIXED_LEN:body_end],
    )
