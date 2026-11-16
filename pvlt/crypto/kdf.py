"""Key derivation: Argon2id v1.3 through `cryptography` (OpenSSL)."""

from __future__ import annotations

from cryptography.hazmat.primitives.kdf.argon2 import Argon2id

from pvlt.params import (
    KEY_LEN,
    M_COST_MAX_KIB,
    M_COST_PER_LANE_MIN_KIB,
    PARALLELISM_MAX,
    PARALLELISM_MIN,
    SALT_LEN,
    T_COST_MAX,
    T_COST_MIN,
)


class KdfParameterError(ValueError):
    """Argon2id parameters outside the accepted limits. Carries no secret data."""


def validate_kdf_params(salt_len: int, m_cost: int, t_cost: int, parallelism: int) -> None:
    """Reject out-of-range parameters. Must run before any Argon2id work (property P7).

    The parameters come from a file an attacker may have written, so a huge
    `m_cost` or `t_cost` would otherwise turn opening a file into a denial of service.
    """
    if salt_len != SALT_LEN:
        raise KdfParameterError("salt length out of range")
    if not PARALLELISM_MIN <= parallelism <= PARALLELISM_MAX:
        raise KdfParameterError("parallelism out of range")
    if not T_COST_MIN <= t_cost <= T_COST_MAX:
        raise KdfParameterError("t_cost out of range")
    if not M_COST_PER_LANE_MIN_KIB * parallelism <= m_cost <= M_COST_MAX_KIB:
        raise KdfParameterError("m_cost out of range")


def derive_kek(
    password: bytes, salt: bytes, m_cost: int, t_cost: int, parallelism: int
) -> bytearray:
    """Derive the 32-byte KEK from the UTF-8 master password.

    The key is written straight into a `bytearray` owned by the caller, so no
    immutable copy of it is created here and the caller can `zeroize` it on lock.
    No secret, associated data or normalization is applied (docs/diseno.md 4.1).
    """
    validate_kdf_params(len(salt), m_cost, t_cost, parallelism)
    kdf = Argon2id(
        salt=salt,
        length=KEY_LEN,
        iterations=t_cost,
        lanes=parallelism,
        memory_cost=m_cost,
    )
    kek = bytearray(KEY_LEN)
    written = kdf.derive_into(password, kek)
    if written != KEY_LEN:  # pragma: no cover - defensive, the library guarantees it
        kek[:] = bytes(KEY_LEN)
        raise RuntimeError("unexpected KDF output length")
    return kek
