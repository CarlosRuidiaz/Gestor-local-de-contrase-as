"""Run every experiment and draw the figures. Results go to bench/results/.

Usage, from the root of the repository:

    docker compose build
    docker compose run --rm -v "${PWD}/bench/results:/app/bench/results" app python -m bench.run_all

`--quick` uses few repetitions and skips configuration C, to check that
everything works. Its numbers are not valid for the report, so it writes to
bench/results/quick/ and never touches the reference results.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from bench import e1_argon2, e2_open_save, e3_size, plots
from bench.common import RESULTS_DIR, write_system_info

QUICK_DIR = RESULTS_DIR / "quick"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--quick", action="store_true", help="prueba rápida, sin validez")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    out = QUICK_DIR if args.quick else RESULTS_DIR
    raw = out / "raw"
    write_system_info(out / "sistema.csv")
    if args.quick:
        e1_argon2.run(repeats=2, lane_repeats=2, skip_c=True, results_dir=out, raw_dir=raw)
        e2_open_save.run(repeats=3, results_dir=out, raw_dir=raw)
    else:
        e1_argon2.run(repeats=20, lane_repeats=10, skip_c=False, results_dir=out, raw_dir=raw)
        e2_open_save.run(repeats=50, results_dir=out, raw_dir=raw)
    print("E3 tamaño del archivo", flush=True)
    e3_size.run(results_dir=out)
    print("Gráficas", flush=True)
    plots.run(out)
    print(f"Resultados en {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
