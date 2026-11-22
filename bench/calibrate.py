"""Choose the Argon2id configuration for the machine that will run pvlt.

The final configuration (B) was chosen on the reference machine with the rule of
section 6: the most memory whose unlock takes at most 1 s. This script applies
the same rule on any other machine, with fewer repetitions than E1, and prints
which configuration to pick when creating a vault. It writes nothing, so the
reference results in bench/results/ are never overwritten.

Usage: python -m bench.calibrate [--repeats 5] [--skip-c]
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from bench.common import summary
from bench.e1_argon2 import (
    CONFIG_C_FALLBACK,
    KIB_PER_MIB,
    UNLOCK_BUDGET_S,
    ChildFailedError,
    Measurement,
    choose_final,
    measure,
)
from pvlt.params import CONFIG_A, CONFIG_B, CONFIG_C


def calibrate(*, repeats: int, skip_c: bool) -> list[Measurement]:
    results: list[Measurement] = []
    configs = [("A", CONFIG_A), ("B", CONFIG_B)] + ([] if skip_c else [("C", CONFIG_C)])
    for label, params in configs:
        print(f"Midiendo {label} ({repeats} desbloqueos)...", flush=True)
        try:
            results.append(measure(label, params, repeats))
        except ChildFailedError:
            if label != "C":
                raise
            print("  C no cabe en la memoria disponible, se mide 1 GiB y 2 pasadas.", flush=True)
            results.append(measure("C'", CONFIG_C_FALLBACK, repeats))
    return results


def report(results: Sequence[Measurement]) -> str:
    lines = ["", "Configuración  Memoria   Pasadas  Desbloqueo (mediana)  Pico de memoria"]
    for m in results:
        median = f"{summary(m.wall)['median']:.3f}".replace(".", ",")
        lines.append(
            f"{m.label:<14} {m.params.m_cost // KIB_PER_MIB:>5} MiB  {m.params.t_cost:>7}"
            f"  {median:>17} s  {m.rss_peak_kib // KIB_PER_MIB:>11} MiB"
        )
    final = choose_final(results)
    lines.append("")
    if final is None:
        lines.append(
            f"Ninguna configuración desbloquea en {UNLOCK_BUDGET_S:.0f} s o menos en este equipo. "
            "Usa A, que es la más ligera."
        )
    else:
        lines.append(
            f"Recomendada para este equipo: {final.label}, la de mayor memoria que desbloquea "
            f"en {UNLOCK_BUDGET_S:.0f} s o menos."
        )
        lines.append(
            "Se elige al crear la bóveda: en la interfaz web, en el campo «Configuración de "
            f"Argon2id», o con: python -m pvlt.cli create --config {final.label[0]}"
        )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m bench.calibrate",
        description="Mide A, B y C en este equipo y recomienda una configuración de Argon2id.",
    )
    parser.add_argument("--repeats", type=int, default=5, help="desbloqueos por configuración")
    parser.add_argument("--skip-c", action="store_true", help="omitir la configuración C (2 GiB)")
    args = parser.parse_args(argv)
    if args.repeats < 1:
        parser.error("--repeats debe ser al menos 1")
    print(report(calibrate(repeats=args.repeats, skip_c=args.skip_c)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
