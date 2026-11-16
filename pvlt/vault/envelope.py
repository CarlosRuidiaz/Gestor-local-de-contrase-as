"""Sealing and opening of a whole file (docs/diseno.md, sections 4.1, 4.3 and 4.4).

    W = AEAD(KEK).encrypt(N_w, DEK,    "PVLT/v1/wrap" || Hdr)
    C = AEAD(DEK).encrypt(N_d, pad(P), "PVLT/v1/data" || Hdr || W)

Every call to `seal_file` draws a fresh DEK and fresh nonces, so each DEK
encrypts exactly one message and no counter has to be persisted.
"""

from __future__ import annotations

from pvlt.crypto import AuthenticationError, open_, random_bytes, seal, zeroize
from pvlt.params import DATA_LABEL, KEY_LEN, NONCE_LEN, WRAP_LABEL
from pvlt.storage import Header, VaultFile
from pvlt.vault.errors import TamperedContentError, WrongPasswordError
from pvlt.vault.model import pad, unpad

Key = bytes | bytearray


def wrap_aad(header: Header) -> bytes:
    return WRAP_LABEL + header.pack()


def data_aad(header: Header, wrapped_key: bytes) -> bytes:
    return DATA_LABEL + header.pack() + wrapped_key


def seal_file(kek: Key, header: Header, content: bytes) -> bytes:
    """Encrypt `content` under a new DEK and return the complete serialized file."""
    dek = bytearray(random_bytes(KEY_LEN))
    try:
        nonce_w = random_bytes(NONCE_LEN)
        nonce_d = random_bytes(NONCE_LEN)
        wrapped_key = seal(kek, nonce_w, dek, wrap_aad(header))
        ciphertext = seal(dek, nonce_d, pad(content), data_aad(header, wrapped_key))
    finally:
        zeroize(dek)
    return VaultFile(header, nonce_w, wrapped_key, nonce_d, ciphertext).pack()


def unwrap_dek(kek: Key, file: VaultFile) -> bytes:
    """Check 3: open W with the KEK. Failure means wrong password (or altered header, salt or W)."""
    try:
        return open_(kek, file.nonce_w, file.wrapped_key, wrap_aad(file.header))
    except AuthenticationError:
        raise WrongPasswordError from None


def open_file(kek: Key, file: VaultFile) -> bytes:
    """Checks 3 and 4 up to the padding: returns the content bytes P."""
    dek = unwrap_dek(kek, file)
    try:
        padded = open_(dek, file.nonce_d, file.ciphertext, data_aad(file.header, file.wrapped_key))
    except AuthenticationError:
        raise TamperedContentError("tag") from None
    return unpad(padded)
