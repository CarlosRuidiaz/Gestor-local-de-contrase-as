"""E1: unlock time and peak resident memory for the Argon2id configurations.

docs/diseno.md section 10: median of 20 unlocks for A, B and C, peak resident
memory of the process (not `tracemalloc`), whether the lanes use several cores,
and the dictionary cost t x |D|.

Each configuration runs in its own child process, so the peak resident set
(`ru_maxrss`) belongs to that configuration alone. The child creates a vault in
a temporary directory and unlocks it with `Vault.unlock`, which is what a user
waits for: checks 1 and 2, Argon2id, and checks 3 and 4. The synthetic master
password lives only inside the child, never in its arguments.

Usage: python -m bench.e1_argon2 [--repeats 20] [--lane-repeats 10] [--skip-c]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from bench.common import BENCH_PASSWORD, RAW_DIR, RESULTS_DIR, summary, write_csv
from pvlt.params import CONFIG_A, CONFIG_B, CONFIG_C, Argon2Params
from pvlt.vault import Vault

# Fallback of configuration C written in the design: 1 GiB and 2 passes if 2 GiB does not fit.
CONFIG_C_FALLBACK = Argon2Params(m_cost=1024 * 1024, t_cost=2, parallelism=4)

# Final configuration rule (section 6): the most memory with an unlock of at most 1 s.
UNLOCK_BUDGET_S = 1.0

# Dictionary sizes for the cost estimate t x |D|.
DICTIONARIES: tuple[tuple[str, int], ...] = (
    ("10^4 contraseñas más comunes", 10**4),
    ("RockYou, 1,43·10^7", 14_344_391),
    ("10^9 candidatos", 10**9),
    ("2^40, contraseña de 40 bits", 2**40),
)

KIB_PER_MIB = 1024


@dataclass(frozen=True, slots=True)
class Measurement:
    """What one child process reports. Times in seconds, memory in KiB."""

    label: str
    params: Argon2Params
    wall: tuple[float, ...]
    cpu: tuple[float, ...]
    rss_baseline_kib: int
    rss_peak_kib: int


# --- Child process ------------------------------------------------------------


def _rss_kib() -> int:
    """Current resident set (VmRSS) of this process, in KiB. 0 where /proc is missing."""
    try:
        with open("/proc/self/status", encoding="ascii") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])
    except OSError:
        return 0
    return 0


def _peak_rss_kib() -> int:
    """Peak resident set of this process since it started (`ru_maxrss`, KiB on Linux)."""
    if sys.platform == "win32":
        return 0
    import resource

    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss


def measure_in_process(params: Argon2Params, repeats: int, workdir: Path) -> dict[str, object]:
    """Create one vault and unlock it `repeats` times. Runs inside the child process.

    `time.process_time` counts the CPU time of every thread of the process, so
    cpu / wall above 1 means the lanes ran on several cores at once.
    """
    if repeats < 1:
        raise ValueError("repeats must be at least 1")
    baseline = _rss_kib()
    path = workdir / "e1.pvlt"
    Vault.create(path, BENCH_PASSWORD, params=params).lock()
    wall: list[float] = []
    cpu: list[float] = []
    for _ in range(repeats):
        c0 = time.process_time()
        t0 = time.perf_counter()
        vault = Vault.unlock(path, BENCH_PASSWORD)
        t1 = time.perf_counter()
        c1 = time.process_time()
        vault.lock()
        wall.append(t1 - t0)
        cpu.append(c1 - c0)
    return {
        "wall": wall,
        "cpu": cpu,
        "rss_baseline_kib": baseline,
        "rss_peak_kib": _peak_rss_kib(),
    }


def _worker(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--m", type=int, required=True)
    parser.add_argument("--t", type=int, required=True)
    parser.add_argument("--p", type=int, required=True)
    parser.add_argument("--repeats", type=int, required=True)
    args = parser.parse_args(argv)
    params = Argon2Params(m_cost=args.m, t_cost=args.t, parallelism=args.p)
    with tempfile.TemporaryDirectory(prefix="pvlt-e1-") as tmp:
        result = measure_in_process(params, args.repeats, Path(tmp))
    print(json.dumps(result))
    return 0


# --- Parent process -----------------------------------------------------------


class ChildFailedError(RuntimeError):
    """The child process died, usually killed for lack of memory."""


def measure(label: str, params: Argon2Params, repeats: int) -> Measurement:
    """Run one configuration in a fresh interpreter and collect its report."""
    cmd = [
        sys.executable,
        "-m",
        "bench.e1_argon2",
        "--worker",
        "--m",
        str(params.m_cost),
        "--t",
        str(params.t_cost),
        "--p",
        str(params.parallelism),
        "--repeats",
        str(repeats),
    ]
    # Only public cost parameters go in the arguments. The password never leaves the child.
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603
    if proc.returncode != 0:
        raise ChildFailedError(f"{label}: exit status {proc.returncode}")
    data = json.loads(proc.stdout.strip().splitlines()[-1])
    return Measurement(
        label=label,
        params=params,
        wall=tuple(float(x) for x in data["wall"]),
        cpu=tuple(float(x) for x in data["cpu"]),
        rss_baseline_kib=int(data["rss_baseline_kib"]),
        rss_peak_kib=int(data["rss_peak_kib"]),
    )


def summary_row(m: Measurement) -> dict[str, object]:
    wall = summary(m.wall)
    cpu = summary(m.cpu)
    return {
        "config": m.label,
        "m_cost_mib": m.params.m_cost // KIB_PER_MIB,
        "t_cost": m.params.t_cost,
        "parallelism": m.params.parallelism,
        "repeticiones": len(m.wall),
        "desbloqueo_mediana_s": wall["median"],
        "desbloqueo_min_s": wall["min"],
        "desbloqueo_max_s": wall["max"],
        "cpu_mediana_s": cpu["median"],
        "cpu_sobre_pared": cpu["median"] / wall["median"],
        "rss_base_mib": m.rss_baseline_kib / KIB_PER_MIB,
        "rss_pico_mib": m.rss_peak_kib / KIB_PER_MIB,
        "rss_incremento_mib": (m.rss_peak_kib - m.rss_baseline_kib) / KIB_PER_MIB,
    }


def raw_rows(m: Measurement) -> list[dict[str, object]]:
    return [
        {"config": m.label, "repeticion": i, "pared_s": w, "cpu_s": c}
        for i, (w, c) in enumerate(zip(m.wall, m.cpu, strict=True))
    ]


def dictionary_rows(measurements: Sequence[Measurement]) -> list[dict[str, object]]:
    """Cost of trying every candidate of a dictionary against one vault.

    `pared` is t x |D| with t the median unlock on this machine, as the design
    asks. `cpu` uses CPU time per guess, the figure that matters to an attacker
    who keeps every core busy. Neither counts hardware faster than this machine.
    """
    rows: list[dict[str, object]] = []
    for m in measurements:
        t_wall = summary(m.wall)["median"]
        t_cpu = summary(m.cpu)["median"]
        for name, size in DICTIONARIES:
            rows.append(
                {
                    "config": m.label,
                    "diccionario": name,
                    "tamano": size,
                    "segundos_por_intento": t_wall,
                    "pared_horas": t_wall * size / 3600,
                    "pared_anios": t_wall * size / (3600 * 24 * 365),
                    "cpu_nucleo_horas": t_cpu * size / 3600,
                    "memoria_por_intento_mib": m.params.m_cost // KIB_PER_MIB,
                }
            )
    return rows


def choose_final(measurements: Sequence[Measurement]) -> Measurement | None:
    """The configuration with the most memory whose median unlock fits the budget."""
    fitting = [m for m in measurements if summary(m.wall)["median"] <= UNLOCK_BUDGET_S]
    if not fitting:
        return None
    return max(fitting, key=lambda m: (m.params.m_cost, m.params.t_cost))


def run(
    *,
    repeats: int,
    lane_repeats: int,
    skip_c: bool,
    results_dir: Path = RESULTS_DIR,
    raw_dir: Path = RAW_DIR,
) -> list[Measurement]:
    configs: list[tuple[str, Argon2Params]] = [("A", CONFIG_A), ("B", CONFIG_B)]
    main: list[Measurement] = []
    for label, params in configs:
        print(f"E1 {label}: {repeats} desbloqueos", flush=True)
        main.append(measure(label, params, repeats))
    if not skip_c:
        print(f"E1 C: {repeats} desbloqueos", flush=True)
        try:
            main.append(measure("C", CONFIG_C, repeats))
        except ChildFailedError as exc:
            print(f"E1 C no cabe en memoria ({exc}), se mide C' con 1 GiB y 2 pasadas", flush=True)
            main.append(measure("C'", CONFIG_C_FALLBACK, repeats))

    # Lanes: same memory and passes as B, only the parallelism changes.
    lanes: list[Measurement] = []
    for p in (1, 2, 4):
        params = Argon2Params(m_cost=CONFIG_B.m_cost, t_cost=CONFIG_B.t_cost, parallelism=p)
        print(f"E1 carriles p={p}: {lane_repeats} desbloqueos", flush=True)
        lanes.append(measure(f"B p={p}", params, lane_repeats))

    write_csv(results_dir / "e1_argon2.csv", [summary_row(m) for m in main])
    write_csv(results_dir / "e1_carriles.csv", [summary_row(m) for m in lanes])
    write_csv(results_dir / "e1_diccionario.csv", dictionary_rows(main))
    write_csv(raw_dir / "e1_raw.csv", [r for m in main + lanes for r in raw_rows(m)])

    for m in main + lanes:
        row = summary_row(m)
        print(
            f"  {row['config']:>7}: {row['desbloqueo_mediana_s']:.3f} s, "
            f"cpu/pared {row['cpu_sobre_pared']:.2f}, pico {row['rss_pico_mib']:.0f} MiB"
        )
    final = choose_final(main)
    print(f"Configuración final según la regla de 1 s: {final.label if final else 'ninguna'}")
    return main + lanes


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "--worker":
        return _worker(argv[1:])
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--repeats", type=int, default=20)
    parser.add_argument("--lane-repeats", type=int, default=10)
    parser.add_argument("--skip-c", action="store_true", help="omitir la configuración C")
    args = parser.parse_args(argv)
    run(repeats=args.repeats, lane_repeats=args.lane_repeats, skip_c=args.skip_c)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
