"""Flip one bit of a file, to show the backup recovery in a live demonstration.

    docker compose run --rm app python -m scripts.damage /data/boveda.pvlt

The digest is not recomputed, as in a disk fault (adversary A3). The next start
reports the file as damaged and offers to restore the backup. Run it only with
pvlt stopped, because the running server holds the vault.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Inside the ciphertext for any valid file (the fixed part ends at byte 135).
DEFAULT_OFFSET = 200


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.damage",
        description="Invierte un bit de un archivo para demostrar la recuperación del respaldo.",
    )
    parser.add_argument("file", type=Path, metavar="ARCHIVO")
    parser.add_argument("--offset", type=int, default=DEFAULT_OFFSET, help="byte que se altera")
    args = parser.parse_args(argv)

    data = bytearray(args.file.read_bytes())
    if not 0 <= args.offset < len(data):
        print("Error: el desplazamiento está fuera del archivo.", file=sys.stderr)
        return 2
    data[args.offset] ^= 0x01
    args.file.write_bytes(bytes(data))
    print(f"Se invirtió un bit del byte {args.offset} de {args.file}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
