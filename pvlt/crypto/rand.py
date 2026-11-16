"""Randomness. The only source in the whole project is the OS CSPRNG via `secrets`."""

from __future__ import annotations

import secrets


def random_bytes(n: int) -> bytes:
    """Return `n` bytes from the operating system CSPRNG."""
    if n <= 0:
        raise ValueError("n must be positive")
    return secrets.token_bytes(n)
