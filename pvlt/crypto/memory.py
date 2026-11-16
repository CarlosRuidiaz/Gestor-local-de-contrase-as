"""Best-effort erasure of key material held in mutable buffers."""

from __future__ import annotations


def zeroize(buf: bytearray) -> None:
    """Overwrite `buf` with zeros in place.

    This is reasonable effort, not a guarantee (docs/diseno.md 4.9): Python and
    OpenSSL may have made internal copies that this function cannot reach.
    """
    for i in range(len(buf)):
        buf[i] = 0
