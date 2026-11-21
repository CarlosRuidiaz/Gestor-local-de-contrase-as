"""Helpers shared by the experiments: synthetic data, statistics, CSV and system info.

Every password, site and user produced here is synthetic. No result file ever
contains an entry field or the master password, only sizes, times and parameters.
"""

from __future__ import annotations

import csv
import os
import platform
import statistics
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

import cryptography
from cryptography.hazmat.backends.openssl import backend

from pvlt.vault.generator import generate
from pvlt.vault.model import Content, Entry, GeneratorSettings, new_entry_id

RESULTS_DIR = Path(__file__).resolve().parent / "results"
RAW_DIR = RESULTS_DIR / "raw"

# Synthetic master password of every vault the experiments create. It is never
# written to argv, the environment, a file or the output.
BENCH_PASSWORD = "contraseña-sintética-de-experimentos-001"

_TIMESTAMP = "2026-11-21T12:00:00Z"
_SYNTHETIC_PASSWORD_SETTINGS = GeneratorSettings(length=20)


def synthetic_entry(i: int) -> Entry:
    """A plausible entry: short site and user, a 20 character generated password and a note."""
    return Entry(
        id=new_entry_id(),
        site=f"sitio-sintetico-{i:04d}.example",
        username=f"usuario.sintetico.{i:04d}@example.com",
        password=generate(_SYNTHETIC_PASSWORD_SETTINGS),
        notes=f"nota sintética de la entrada {i:04d}",
        created=_TIMESTAMP,
        modified=_TIMESTAMP,
    )


def synthetic_content(n: int) -> Content:
    return Content(entries=tuple(synthetic_entry(i) for i in range(n)))


def summary(values: Sequence[float]) -> dict[str, float]:
    """Median, minimum and maximum of a non-empty series."""
    if not values:
        raise ValueError("empty series")
    return {
        "median": statistics.median(values),
        "min": min(values),
        "max": max(values),
    }


def write_csv(path: Path, rows: Iterable[Mapping[str, object]]) -> Path:
    """Write `rows` with the keys of the first row as the header. Floats get 6 decimals."""
    rows = list(rows)
    if not rows:
        raise ValueError("no rows to write")
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0])
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: f"{v:.6f}" if isinstance(v, float) else v for k, v in row.items()})
    return path


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _first_line_with(path: Path, prefix: str) -> str | None:
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                if line.startswith(prefix):
                    return line.split(":", 1)[1].strip()
    except OSError:
        return None
    return None


def _cgroup_memory_limit() -> str:
    try:
        raw = Path("/sys/fs/cgroup/memory.max").read_text(encoding="ascii").strip()
    except OSError:
        return "desconocido"
    if raw == "max":
        return "sin límite"
    return f"{int(raw) / 2**30:.2f} GiB"


def _mem_total() -> str:
    value = _first_line_with(Path("/proc/meminfo"), "MemTotal")
    if value is None:
        return "desconocida"
    kib = int(value.split()[0])
    return f"{kib / 2**20:.2f} GiB"


def system_info() -> dict[str, str]:
    """CPU, RAM, OS and library versions of the machine running the experiments."""
    cpu = _first_line_with(Path("/proc/cpuinfo"), "model name") or platform.processor()
    affinity = os.sched_getaffinity(0) if hasattr(os, "sched_getaffinity") else None
    return {
        "fecha_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "cpu": cpu or "desconocida",
        "nucleos_logicos": str(os.cpu_count()),
        "nucleos_disponibles": str(len(affinity)) if affinity is not None else "desconocido",
        "ram_total": _mem_total(),
        "limite_memoria_cgroup": _cgroup_memory_limit(),
        "so": platform.platform(),
        "en_docker": "sí" if os.environ.get("PVLT_IN_DOCKER") == "1" else "no",
        "anfitrion": os.environ.get("PVLT_BENCH_HOST", "no indicado"),
        "python": platform.python_version(),
        "cryptography": cryptography.__version__,
        "openssl": backend.openssl_version_text(),
    }


def write_system_info(path: Path) -> Path:
    return write_csv(path, [{"clave": k, "valor": v} for k, v in system_info().items()])
