"""Figures for the report, generated from the CSV files in bench/results/.

Usage: python -m bench.plots
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.figure import Figure

from bench.common import RESULTS_DIR, read_csv
from bench.e1_argon2 import UNLOCK_BUDGET_S

_DPI = 150


def _floats(rows: Sequence[dict[str, str]], key: str) -> list[float]:
    return [float(r[key]) for r in rows]


def _save(fig: Figure, path: Path) -> Path:
    fig.tight_layout()
    fig.savefig(path, dpi=_DPI)
    plt.close(fig)
    return path


def plot_e1_unlock(results_dir: Path) -> Path:
    rows = read_csv(results_dir / "e1_argon2.csv")
    labels = [f"{r['config']}\n{r['m_cost_mib']} MiB, t={r['t_cost']}" for r in rows]
    med = _floats(rows, "desbloqueo_mediana_s")
    low = [m - x for m, x in zip(med, _floats(rows, "desbloqueo_min_s"), strict=True)]
    high = [x - m for m, x in zip(med, _floats(rows, "desbloqueo_max_s"), strict=True)]
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.bar(labels, med, yerr=[low, high], capsize=4, color="#4c72b0")
    ax.axhline(UNLOCK_BUDGET_S, color="#c44e52", linestyle="--", label="Límite de 1 s")
    ax.set_ylabel("Tiempo de desbloqueo (s), mediana con mín. y máx.")
    ax.set_title("E1: desbloqueo por configuración de Argon2id")
    ax.legend()
    return _save(fig, results_dir / "e1_desbloqueo.png")


def plot_e1_memory(results_dir: Path) -> Path:
    rows = read_csv(results_dir / "e1_argon2.csv")
    m_cost = _floats(rows, "m_cost_mib")
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.plot(m_cost, _floats(rows, "rss_pico_mib"), "o-", label="Pico de memoria residente")
    ax.plot(m_cost, m_cost, ":", color="gray", label="Memoria de Argon2id (m)")
    for r, x in zip(rows, m_cost, strict=True):
        ax.annotate(
            r["config"], (x, float(r["rss_pico_mib"])), xytext=(5, -12), textcoords="offset points"
        )
    ax.set_xscale("log", base=2)
    ax.set_yscale("log", base=2)
    ax.set_xlabel("Memoria de Argon2id (MiB)")
    ax.set_ylabel("Memoria (MiB)")
    ax.set_title("E1: pico de memoria residente del proceso")
    ax.legend()
    return _save(fig, results_dir / "e1_memoria.png")


def plot_e1_lanes(results_dir: Path) -> Path:
    rows = read_csv(results_dir / "e1_carriles.csv")
    labels = [f"p={r['parallelism']}" for r in rows]
    x = range(len(rows))
    width = 0.38
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.bar(
        [i - width / 2 for i in x],
        _floats(rows, "desbloqueo_mediana_s"),
        width,
        label="Tiempo de pared",
        color="#4c72b0",
    )
    ax.bar(
        [i + width / 2 for i in x],
        _floats(rows, "cpu_mediana_s"),
        width,
        label="Tiempo de CPU",
        color="#dd8452",
    )
    ax.set_xticks(list(x), labels)
    ax.set_ylabel("Segundos (mediana)")
    ax.set_title("E1: carriles con 256 MiB y 3 pasadas")
    ax.legend()
    return _save(fig, results_dir / "e1_carriles.png")


def plot_e2(results_dir: Path) -> Path:
    rows = read_csv(results_dir / "e2_abrir_guardar.csv")
    labels = [r["entradas"] for r in rows]
    x = range(len(rows))
    width = 0.38
    fig, ax = plt.subplots(figsize=(6, 4))
    save_bottom = _floats(rows, "sellar_ms")
    open_bottom = _floats(rows, "leer_ms")
    xs = [i - width / 2 for i in x]
    xo = [i + width / 2 for i in x]
    ax.bar(xs, save_bottom, width, label="Guardar: sellar", color="#4c72b0")
    ax.bar(
        xs,
        _floats(rows, "escribir_ms"),
        width,
        bottom=save_bottom,
        label="Guardar: escritura atómica",
        color="#8fa8d6",
    )
    ax.bar(xo, open_bottom, width, label="Abrir: leer y comprobaciones 1 y 2", color="#dd8452")
    ax.bar(
        xo,
        _floats(rows, "descifrar_ms"),
        width,
        bottom=open_bottom,
        label="Abrir: comprobaciones 3 y 4 y JSON",
        color="#f0b88a",
    )
    ax.set_xticks(list(x), labels)
    ax.set_xlabel("Entradas")
    ax.set_ylabel("Milisegundos (mediana)")
    ax.set_title("E2: abrir y guardar sin Argon2id")
    ax.legend(fontsize="small")
    return _save(fig, results_dir / "e2_abrir_guardar.png")


def plot_e3(results_dir: Path) -> Path:
    # Only the measured points are joined, with straight segments: between two
    # measurements the file always stays above the JSON (padding only adds bytes).
    rows = read_csv(results_dir / "e3_tamano.csv")
    n = _floats(rows, "entradas")
    json_kib = [b / 1024 for b in _floats(rows, "json_bytes")]
    file_kib = [b / 1024 for b in _floats(rows, "archivo_bytes")]
    fig, (left, right) = plt.subplots(1, 2, figsize=(9, 3.8))
    left.plot(n, file_kib, "s-", color="#dd8452", label="Archivo .pvlt")
    left.plot(n, json_kib, "o--", color="#4c72b0", label="JSON sin cifrar")
    left.set_xlabel("Entradas")
    left.set_ylabel("Tamaño (KiB)")
    left.set_title("Tamaño medido")
    left.legend()

    measured = [(x, f, j) for x, f, j in zip(n, file_kib, json_kib, strict=True) if x > 0]
    overhead = [100 * (f / j - 1) for _, f, j in measured]
    right.plot([x for x, _, _ in measured], overhead, "s-", color="#dd8452")
    right.set_yscale("log")
    right.set_xlabel("Entradas")
    right.set_ylabel("Exceso sobre el JSON (%)")
    right.set_title("Costo del relleno y la parte fija")
    for x, pct in zip([x for x, _, _ in measured], overhead, strict=True):
        right.annotate(
            f"{pct:.1f} %".replace(".", ","),
            (x, pct),
            xytext=(4, 4),
            textcoords="offset points",
            fontsize="small",
        )
    fig.suptitle("E3: tamaño del archivo frente al JSON")
    return _save(fig, results_dir / "e3_tamano.png")


def run(results_dir: Path = RESULTS_DIR) -> list[Path]:
    makers = {
        "e1_argon2.csv": (plot_e1_unlock, plot_e1_memory),
        "e1_carriles.csv": (plot_e1_lanes,),
        "e2_abrir_guardar.csv": (plot_e2,),
        "e3_tamano.csv": (plot_e3,),
    }
    out: list[Path] = []
    for csv_name, funcs in makers.items():
        if not (results_dir / csv_name).exists():
            print(f"Falta {csv_name}, se omiten sus gráficas")
            continue
        out.extend(f(results_dir) for f in funcs)
    for p in out:
        print(f"  {p.name}")
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.parse_args(sys.argv[1:] if argv is None else argv)
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
