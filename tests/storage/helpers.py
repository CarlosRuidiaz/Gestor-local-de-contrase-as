"""Synthetic files for the storage tests.

Storage never decrypts, so the "ciphertext" here is just random bytes of a valid
length. The digest is recomputed with `hashlib`, an implementation independent
from the one under test.
"""

from __future__ import annotations

import hashlib
import os

from pvlt.params import CONFIG_A, PAD_BLOCK, TAG_LEN
from pvlt.storage.format import DIGEST_LEN, Header, Purpose, VaultFile


def make_file(
    *,
    generation: int = 1,
    purpose: Purpose = Purpose.VAULT,
    blocks: int = 1,
    vault_id: bytes | None = None,
) -> VaultFile:
    return VaultFile(
        header=Header(
            purpose=purpose,
            m_cost=CONFIG_A.m_cost,
            t_cost=CONFIG_A.t_cost,
            parallelism=CONFIG_A.parallelism,
            salt=os.urandom(16),
            vault_id=vault_id if vault_id is not None else os.urandom(16),
            generation=generation,
        ),
        nonce_w=os.urandom(12),
        wrapped_key=os.urandom(48),
        nonce_d=os.urandom(12),
        ciphertext=os.urandom(blocks * PAD_BLOCK + TAG_LEN),
    )


def redigest(data: bytes) -> bytes:
    """Recompute the trailing digest, as an attacker (not an accident) would."""
    body = data[:-DIGEST_LEN]
    return body + hashlib.sha256(body).digest()


def patch(data: bytes, start: int, replacement: bytes, *, fix_digest: bool = True) -> bytes:
    out = data[:start] + replacement + data[start + len(replacement) :]
    assert len(out) == len(data)
    return redigest(out) if fix_digest else out


def flip_bit(data: bytes, byte_index: int, bit: int = 0) -> bytes:
    out = bytearray(data)
    out[byte_index] ^= 1 << bit
    return bytes(out)
