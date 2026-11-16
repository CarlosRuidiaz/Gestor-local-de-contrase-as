"""Protocol constants shared by every layer (docs/diseno.md, sections 4 to 6).

This module holds only public constants. It imports nothing from the package,
so `crypto/` and `storage/` can both use it without depending on each other.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

# Sizes in bytes.
KEY_LEN: Final = 32
NONCE_LEN: Final = 12
TAG_LEN: Final = 16
SALT_LEN: Final = 16

# Domain separation labels, exact ASCII bytes with no terminator (section 4.1).
WRAP_LABEL: Final = b"PVLT/v1/wrap"
DATA_LABEL: Final = b"PVLT/v1/data"

# Argon2id limits accepted when opening a file (section 5). Memory is in KiB.
ARGON2_VERSION: Final = 0x13
M_COST_MAX_KIB: Final = 4 * 1024 * 1024  # 4 GiB
T_COST_MIN: Final = 1
T_COST_MAX: Final = 16
PARALLELISM_MIN: Final = 1
PARALLELISM_MAX: Final = 16
M_COST_PER_LANE_MIN_KIB: Final = 8  # Argon2 requires m >= 8 * p

# Stricter floor applied only when creating a vault.
M_COST_CREATE_MIN_KIB: Final = 64 * 1024  # 64 MiB


@dataclass(frozen=True, slots=True)
class Argon2Params:
    """Cost parameters of Argon2id. They are public and stored in the file header."""

    m_cost: int  # memory in KiB
    t_cost: int  # passes
    parallelism: int  # lanes


# Section 6. A is used by the functional tests, B is the proposed default,
# C is the first recommendation of RFC 9106. E1 decides the final one.
CONFIG_A: Final = Argon2Params(m_cost=64 * 1024, t_cost=3, parallelism=4)
CONFIG_B: Final = Argon2Params(m_cost=256 * 1024, t_cost=3, parallelism=4)
CONFIG_C: Final = Argon2Params(m_cost=2 * 1024 * 1024, t_cost=1, parallelism=4)
