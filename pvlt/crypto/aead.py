"""Authenticated encryption: ChaCha20-Poly1305 (RFC 8439) through `cryptography`."""

from __future__ import annotations

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

from pvlt.params import KEY_LEN, NONCE_LEN, TAG_LEN

Key = bytes | bytearray


class AuthenticationError(Exception):
    """The tag did not verify: wrong key, or nonce, ciphertext, tag or associated data altered.

    The layer above decides what it means (wrong password when opening W,
    tampered content when opening C). The message never includes key or data.
    """

    def __init__(self) -> None:
        super().__init__("authentication failed")


def _check_lengths(key: Key, nonce: bytes) -> None:
    # Only lengths are reported. Values never reach an exception message.
    if len(key) != KEY_LEN:
        raise ValueError("key must be 32 bytes")
    if len(nonce) != NONCE_LEN:
        raise ValueError("nonce must be 12 bytes")


def seal(key: Key, nonce: bytes, plaintext: bytes | bytearray, aad: bytes) -> bytes:
    """Encrypt and authenticate. Returns ciphertext followed by the 16-byte tag.

    The caller is responsible for never reusing a nonce under the same key.
    """
    _check_lengths(key, nonce)
    return ChaCha20Poly1305(key).encrypt(nonce, plaintext, aad)


def open_(key: Key, nonce: bytes, ciphertext: bytes, aad: bytes) -> bytes:
    """Verify and decrypt. Raises `AuthenticationError` and releases nothing on failure."""
    _check_lengths(key, nonce)
    if len(ciphertext) < TAG_LEN:
        raise AuthenticationError
    try:
        return ChaCha20Poly1305(key).decrypt(nonce, ciphertext, aad)
    except InvalidTag:
        # `from None` drops the chained traceback, whose frames hold the key.
        raise AuthenticationError from None
