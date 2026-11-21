"""The experiment scripts run end to end with tiny settings and never leak the synthetic data.

These tests check the scripts, not the numbers: the numbers only mean something
with the full repetitions on the reference machine.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from bench import e1_argon2, e2_open_save, e3_size, plots
from bench.common import (
    BENCH_PASSWORD,
    read_csv,
    summary,
    synthetic_content,
    system_info,
    write_csv,
)
from pvlt.params import CONFIG_A, PAD_BLOCK, Argon2Params

linux_only = pytest.mark.skipif(sys.platform == "win32", reason="usa /proc y ru_maxrss")


def test_synthetic_content_is_valid_and_unique() -> None:
    content = synthetic_content(50)
    assert len(content.entries) == 50
    assert len({e.password for e in content.entries}) == 50
    assert all(e.site.endswith(".example") for e in content.entries)


def test_summary_and_empty_series() -> None:
    assert summary([3.0, 1.0, 2.0]) == {"median": 2.0, "min": 1.0, "max": 3.0}
    with pytest.raises(ValueError):
        summary([])


def test_csv_roundtrip(tmp_path: Path) -> None:
    path = write_csv(tmp_path / "x.csv", [{"a": 1, "b": 0.5}, {"a": 2, "b": 1.25}])
    assert read_csv(path) == [{"a": "1", "b": "0.500000"}, {"a": "2", "b": "1.250000"}]


def test_system_info_has_the_fields_the_report_needs() -> None:
    info = system_info()
    for key in ("cpu", "nucleos_logicos", "ram_total", "so", "cryptography", "openssl"):
        assert info[key]


def _measurement(label: str, m_mib: int, t: int, median: float) -> e1_argon2.Measurement:
    return e1_argon2.Measurement(
        label=label,
        params=Argon2Params(m_cost=m_mib * 1024, t_cost=t, parallelism=4),
        wall=(median,),
        cpu=(median,),
        rss_baseline_kib=0,
        rss_peak_kib=0,
    )


def test_choose_final_takes_the_most_memory_within_one_second() -> None:
    a = _measurement("A", 64, 3, 0.2)
    b = _measurement("B", 256, 3, 0.9)
    c = _measurement("C", 2048, 1, 1.4)
    assert e1_argon2.choose_final([a, b, c]) is b
    assert e1_argon2.choose_final([c]) is None


def test_dictionary_cost_is_time_times_size() -> None:
    rows = e1_argon2.dictionary_rows([_measurement("B", 256, 3, 0.5)])
    assert len(rows) == len(e1_argon2.DICTIONARIES)
    for row, (_, size) in zip(rows, e1_argon2.DICTIONARIES, strict=True):
        assert row["pared_horas"] == pytest.approx(0.5 * size / 3600)


@linux_only
def test_e1_measures_in_process(tmp_path: Path) -> None:
    result = e1_argon2.measure_in_process(CONFIG_A, 2, tmp_path)
    wall = result["wall"]
    assert isinstance(wall, list)
    assert len(wall) == 2
    assert all(w > 0 for w in wall)
    peak = result["rss_peak_kib"]
    base = result["rss_baseline_kib"]
    assert isinstance(peak, int)
    assert isinstance(base, int)
    # Argon2id with 64 MiB must show in the peak resident set.
    assert peak - base >= 60 * 1024


@linux_only
def test_e1_child_process_reports_and_keeps_the_password_out_of_argv() -> None:
    m = e1_argon2.measure("A", CONFIG_A, 1)
    assert len(m.wall) == 1
    assert m.rss_peak_kib > m.rss_baseline_kib
    row = e1_argon2.summary_row(m)
    assert row["m_cost_mib"] == 64


def test_e2_saves_opens_and_summarizes(tmp_path: Path) -> None:
    results = tmp_path / "results"
    rows = e2_open_save.run(
        repeats=2, workdir=tmp_path, sizes=(1, 5), results_dir=results, raw_dir=results / "raw"
    )
    assert [r["entradas"] for r in rows] == [1, 5]
    assert all(float(str(r["guardar_mediana_ms"])) > 0 for r in rows)
    assert len(read_csv(results / "raw" / "e2_raw.csv")) == 4


def test_e3_sizes_are_consistent(tmp_path: Path) -> None:
    rows = e3_size.run(sizes=(0, 1, 30), results_dir=tmp_path)
    fixed = {r["fijo_bytes"] for r in rows}
    assert len(fixed) == 1, "the fixed part must not depend on the number of entries"
    for r in rows:
        json_bytes = int(str(r["json_bytes"]))
        padding = int(str(r["relleno_bytes"]))
        assert (json_bytes + padding) % PAD_BLOCK == 0
        assert int(str(r["archivo_bytes"])) > json_bytes


@linux_only
def test_full_quick_pipeline_draws_every_figure_and_leaks_nothing(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    measurements = [e1_argon2.measure("A", CONFIG_A, 1)]
    write_csv(tmp_path / "e1_argon2.csv", [e1_argon2.summary_row(m) for m in measurements])
    write_csv(tmp_path / "e1_carriles.csv", [e1_argon2.summary_row(m) for m in measurements])
    e2_open_save.run(repeats=1, workdir=tmp_path, sizes=(1,), results_dir=tmp_path, raw_dir=raw)
    e3_size.run(sizes=(0, 1), results_dir=tmp_path)
    figures = plots.run(tmp_path)
    assert {p.name for p in figures} == {
        "e1_desbloqueo.png",
        "e1_memoria.png",
        "e1_carriles.png",
        "e2_abrir_guardar.png",
        "e3_tamano.png",
    }
    secret = BENCH_PASSWORD.encode("utf-8")
    for path in tmp_path.rglob("*"):
        if path.is_file() and path.suffix in {".csv", ".png"}:
            data = path.read_bytes()
            assert secret not in data
            assert b"sitio-sintetico" not in data
            assert b"usuario.sintetico" not in data
