"""Scaffolding checks: the package imports and the layers respect the dependency direction."""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

import pvlt

PKG = Path(pvlt.__file__).parent

# web -> vault -> (crypto, storage). Each layer lists the pvlt subpackages it must not import.
FORBIDDEN: dict[str, set[str]] = {
    "crypto": {"storage", "vault", "web"},
    "storage": {"crypto", "vault", "web"},
    "vault": {"web"},
}


@pytest.mark.parametrize("name", ["crypto", "storage", "vault", "web"])
def test_layer_imports(name: str) -> None:
    importlib.import_module(f"pvlt.{name}")


def _pvlt_imports(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names = [node.module]
        else:
            continue
        for n in names:
            parts = n.split(".")
            if parts[0] == "pvlt" and len(parts) > 1:
                found.add(parts[1])
    return found


@pytest.mark.parametrize("layer", sorted(FORBIDDEN))
def test_dependency_direction(layer: str) -> None:
    for path in (PKG / layer).rglob("*.py"):
        bad = _pvlt_imports(path) & FORBIDDEN[layer]
        assert not bad, f"{path.relative_to(PKG)} importa {sorted(bad)}"


def test_no_random_module_in_package() -> None:
    """Rule 1: randomness only through `secrets` or `os.urandom`."""
    for path in PKG.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                assert all(a.name != "random" for a in node.names), path
            elif isinstance(node, ast.ImportFrom):
                assert node.module != "random", path
