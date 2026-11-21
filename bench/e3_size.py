"""E3: size of the vault file compared with the unencrypted canonical JSON.

The file is header + envelope (nonces, wrapped DEK, length) + C + SHA-256,
and C is the content padded to a multiple of 4096 bytes plus the Poly1305 tag
(docs/diseno.md sections 5 and 5.1). The table separates the padding from the
fixed part, so the report can say where each extra byte comes from.

Usage: python -m bench.e3_size
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from bench.common import RESULTS_DIR, synthetic_content, write_csv
from pvlt.crypto import random_bytes, zeroize
from pvlt.params import CONFIG_B, KEY_LEN, SALT_LEN, TAG_LEN
from pvlt.storage import Header, Purpose
from pvlt.storage.format import VAULT_ID_LEN
from pvlt.vault.envelope import seal_file
from pvlt.vault.model import MAX_ENTRIES, pad, serialize_content

SIZES: tuple[int, ...] = (0, 1, 10, 50, 100, 200, 300, 400, MAX_ENTRIES)


def size_row(n: int) -> dict[str, object]:
    content = serialize_content(synthetic_content(n))
    padded = len(pad(content))
    header = Header(
        purpose=Purpose.VAULT,
        m_cost=CONFIG_B.m_cost,
        t_cost=CONFIG_B.t_cost,
        parallelism=CONFIG_B.parallelism,
        salt=random_bytes(SALT_LEN),
        vault_id=random_bytes(VAULT_ID_LEN),
        generation=1,
    )
    kek = bytearray(random_bytes(KEY_LEN))
    try:
        file_len = len(seal_file(kek, header, content))
    finally:
        zeroize(kek)
    return {
        "entradas": n,
        "json_bytes": len(content),
        "relleno_bytes": padded - len(content),
        "fijo_bytes": file_len - padded,
        "etiqueta_c_bytes": TAG_LEN,
        "archivo_bytes": file_len,
        "archivo_sobre_json": file_len / len(content),
        "bytes_por_entrada_json": (len(content) / n) if n else 0.0,
    }


def run(
    *, sizes: Sequence[int] = SIZES, results_dir: Path = RESULTS_DIR
) -> list[dict[str, object]]:
    rows = [size_row(n) for n in sizes]
    write_csv(results_dir / "e3_tamano.csv", rows)
    for r in rows:
        print(
            f"  {r['entradas']:>4} entradas: JSON {r['json_bytes']} B, "
            f"archivo {r['archivo_bytes']} B ({r['archivo_sobre_json']:.2f}x)"
        )
    return rows


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.parse_args(sys.argv[1:] if argv is None else argv)
    print("E3 tamaño del archivo", flush=True)
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
