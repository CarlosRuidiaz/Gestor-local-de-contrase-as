"""E2: open and save without Argon2id for vaults of 1, 100 and 500 entries.

docs/diseno.md section 10: median of 50. The KEK is drawn at random once, so
the times exclude the key derivation that E1 measures. Each phase is timed apart:

- save: canonical JSON and sealing (new DEK and nonces), then `atomic_save`
  (temporary file, fsync, verification, backup, `os.replace`, directory fsync).
- open: `load` (reading plus checks 1 and 2), then checks 3 and 4 and the
  strict parsing of the content.

Every save writes the next generation, exactly as `Vault` does.

Usage: python -m bench.e2_open_save [--repeats 50] [--dir DIRECTORIO]
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path

from bench.common import RAW_DIR, RESULTS_DIR, summary, synthetic_content, write_csv
from pvlt.crypto import random_bytes, zeroize
from pvlt.params import CONFIG_B, KEY_LEN, SALT_LEN
from pvlt.storage import Header, Purpose, atomic_save, load
from pvlt.storage.format import VAULT_ID_LEN
from pvlt.vault.envelope import open_file, seal_file
from pvlt.vault.model import parse_content, serialize_content

SIZES: tuple[int, ...] = (1, 100, 500)


def measure_size(n: int, repeats: int, workdir: Path) -> list[dict[str, object]]:
    """Save and open a vault of `n` entries `repeats` times. Returns one raw row per repetition."""
    if repeats < 1:
        raise ValueError("repeats must be at least 1")
    content = synthetic_content(n)
    header = Header(
        purpose=Purpose.VAULT,
        m_cost=CONFIG_B.m_cost,
        t_cost=CONFIG_B.t_cost,
        parallelism=CONFIG_B.parallelism,
        salt=random_bytes(SALT_LEN),
        vault_id=random_bytes(VAULT_ID_LEN),
        generation=1,
    )
    path = workdir / f"e2-{n}.pvlt"
    kek = bytearray(random_bytes(KEY_LEN))
    rows: list[dict[str, object]] = []
    try:
        atomic_save(path, seal_file(kek, header, serialize_content(content)))
        for i in range(repeats):
            header = dataclasses.replace(header, generation=header.generation + 1)
            t0 = time.perf_counter()
            data = seal_file(kek, header, serialize_content(content))
            t1 = time.perf_counter()
            atomic_save(path, data)
            t2 = time.perf_counter()
            file = load(path, Purpose.VAULT)
            t3 = time.perf_counter()
            opened = parse_content(open_file(kek, file))
            t4 = time.perf_counter()
            if opened != content:
                raise AssertionError("the opened content differs from the saved one")
            rows.append(
                {
                    "entradas": n,
                    "repeticion": i,
                    "bytes_archivo": len(data),
                    "sellar_s": t1 - t0,
                    "escribir_s": t2 - t1,
                    "leer_s": t3 - t2,
                    "descifrar_s": t4 - t3,
                }
            )
    finally:
        zeroize(kek)
    return rows


_PHASES = ("sellar_s", "escribir_s", "leer_s", "descifrar_s")


def summary_rows(raw: Sequence[dict[str, object]]) -> list[dict[str, object]]:
    """Median per phase in milliseconds, plus the save and open totals."""
    out: list[dict[str, object]] = []
    for n in sorted({int(str(r["entradas"])) for r in raw}):
        rows = [r for r in raw if r["entradas"] == n]
        med = {p: summary([float(str(r[p])) for r in rows])["median"] * 1000 for p in _PHASES}
        save = summary([float(str(r["sellar_s"])) + float(str(r["escribir_s"])) for r in rows])
        opened = summary([float(str(r["leer_s"])) + float(str(r["descifrar_s"])) for r in rows])
        out.append(
            {
                "entradas": n,
                "repeticiones": len(rows),
                "bytes_archivo": rows[0]["bytes_archivo"],
                "sellar_ms": med["sellar_s"],
                "escribir_ms": med["escribir_s"],
                "guardar_mediana_ms": save["median"] * 1000,
                "guardar_min_ms": save["min"] * 1000,
                "guardar_max_ms": save["max"] * 1000,
                "leer_ms": med["leer_s"],
                "descifrar_ms": med["descifrar_s"],
                "abrir_mediana_ms": opened["median"] * 1000,
                "abrir_min_ms": opened["min"] * 1000,
                "abrir_max_ms": opened["max"] * 1000,
            }
        )
    return out


def run(
    *,
    repeats: int,
    workdir: Path | None = None,
    sizes: Sequence[int] = SIZES,
    results_dir: Path = RESULTS_DIR,
    raw_dir: Path = RAW_DIR,
) -> list[dict[str, object]]:
    raw: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="pvlt-e2-", dir=workdir) as tmp:
        for n in sizes:
            print(f"E2 {n} entradas: {repeats} guardados y aperturas", flush=True)
            raw.extend(measure_size(n, repeats, Path(tmp)))
    rows = summary_rows(raw)
    write_csv(results_dir / "e2_abrir_guardar.csv", rows)
    write_csv(raw_dir / "e2_raw.csv", raw)
    for r in rows:
        print(
            f"  {r['entradas']:>4} entradas: guardar {r['guardar_mediana_ms']:.2f} ms, "
            f"abrir {r['abrir_mediana_ms']:.2f} ms"
        )
    return rows


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--repeats", type=int, default=50)
    parser.add_argument(
        "--dir", type=Path, default=None, help="carpeta de trabajo (por defecto la temporal)"
    )
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    run(repeats=args.repeats, workdir=args.dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
