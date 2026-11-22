"""The demonstration script runs end to end and never prints a secret."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import damage, demo


@pytest.mark.slow
def test_demo_passes_every_check(capsys: pytest.CaptureFixture[str]) -> None:
    assert demo.main([]) == 0
    out = capsys.readouterr().out
    assert "[FALLO]" not in out
    assert "Todas las comprobaciones pasaron." in out
    for secret in (demo.MASTER, demo.NEW_MASTER, demo.WRONG, demo.EXPORT):
        assert secret not in out
    for i in range(3):
        assert demo.synthetic_strings(i)[2] not in out


def test_damage_flips_exactly_one_bit(tmp_path: Path) -> None:
    target = tmp_path / "boveda.pvlt"
    original = bytes(range(256))
    target.write_bytes(original)
    assert damage.main([str(target)]) == 0
    changed = [
        i for i, (a, b) in enumerate(zip(original, target.read_bytes(), strict=True)) if a != b
    ]
    assert changed == [damage.DEFAULT_OFFSET]
    assert damage.main([str(target), "--offset", "999"]) == 2
