"""T8: encrypted export and import with preview and conflict resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from pvlt.params import CONFIG_A
from pvlt.storage import FormatError, Purpose, load
from pvlt.vault import (
    ConflictReason,
    ImportDecision,
    ImportResult,
    TamperedContentError,
    ValidationError,
    Vault,
    VaultExistsError,
    WrongPasswordError,
)
from pvlt.vault import vault as vault_module
from tests.storage.helpers import flip_bit, redigest
from tests.vault.conftest import EXPORT, MASTER, OTHER, reopen, snapshot, synthetic_entry


@pytest.fixture
def export_path(tmp_path: Path) -> Path:
    return tmp_path / "salida" / "export.pvlt"


@pytest.fixture
def source(tmp_path: Path, export_path: Path) -> Vault:
    """A vault with five entries, already exported to `export_path`."""
    export_path.parent.mkdir()
    origin = tmp_path / "origen"
    origin.mkdir()
    v = Vault.create(origin / "boveda.pvlt", MASTER, params=CONFIG_A)
    for i in range(5):
        v.add(**synthetic_entry(i))
    v.export(export_path, EXPORT)
    return v


def new_vault(tmp_path: Path, name: str = "destino") -> Vault:
    (tmp_path / name).mkdir()
    return Vault.create(tmp_path / name / "boveda.pvlt", OTHER, params=CONFIG_A)


# --- Export -----------------------------------------------------------------


def test_export_is_an_independent_encrypted_file(source: Vault, export_path: Path) -> None:
    exported = load(export_path, Purpose.EXPORT)
    original = load(source.path, Purpose.VAULT)
    assert exported.header.purpose is Purpose.EXPORT
    assert exported.header.generation == 1
    assert exported.header.salt != original.header.salt
    assert exported.header.vault_id != original.header.vault_id
    assert exported.wrapped_key != original.wrapped_key
    assert sorted(p.name for p in export_path.parent.iterdir()) == ["export.pvlt"]  # no backup

    blob = export_path.read_bytes()
    for i in range(5):
        for value in synthetic_entry(i).values():
            assert value.encode() not in blob
    assert EXPORT.encode() not in blob
    assert MASTER.encode() not in blob


def test_export_does_not_change_the_vault(source: Vault, tmp_path: Path) -> None:
    before = snapshot(source.path.parent)
    generation = source.generation
    source.export(tmp_path / "otro.pvlt", EXPORT)
    assert snapshot(source.path.parent) == before
    assert source.generation == generation


def test_export_refuses_to_overwrite(source: Vault, export_path: Path) -> None:
    before = export_path.read_bytes()
    with pytest.raises(VaultExistsError):
        source.export(export_path, EXPORT)
    with pytest.raises(VaultExistsError):
        source.export(source.path, EXPORT, overwrite=True)  # never over the vault itself
    assert export_path.read_bytes() == before
    source.export(export_path, EXPORT, overwrite=True)
    assert export_path.read_bytes() != before


def test_export_needs_its_own_valid_password(source: Vault, tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        source.export(tmp_path / "otro.pvlt", "short")
    assert not (tmp_path / "otro.pvlt").exists()


# --- T8: import only with the export password -------------------------------


def test_t8_import_with_the_export_password(
    source: Vault, export_path: Path, tmp_path: Path
) -> None:
    target = new_vault(tmp_path)
    preview = target.import_preview(export_path, EXPORT)
    assert len(preview.items) == 5
    assert preview.conflicts == ()
    assert len(target) == 0  # the preview writes nothing
    assert target.generation == 1

    result = target.import_apply(preview)
    assert result == ImportResult(added=5)
    assert target.generation == 2  # one save for the whole import
    originals = [source.get(s.id) for s in source.list_entries()]
    assert [target.get(e.id) for e in originals] == originals
    assert [reopen(target.path, OTHER).get(e.id) for e in originals] == originals


@pytest.mark.parametrize("password", [MASTER, OTHER, EXPORT + "x", ""])
def test_t8_import_without_the_export_password(
    source: Vault, export_path: Path, tmp_path: Path, password: str
) -> None:
    target = new_vault(tmp_path)
    before = snapshot(target.path.parent)
    with pytest.raises(WrongPasswordError):
        target.import_preview(export_path, password)
    assert snapshot(target.path.parent) == before
    assert len(target) == 0


def test_t8_a_vault_file_cannot_be_imported(source: Vault, tmp_path: Path) -> None:
    target = new_vault(tmp_path)
    with pytest.raises(FormatError) as info:
        target.import_preview(source.path, MASTER)
    assert info.value.reason == "purpose"


def test_t8_tampered_export_is_rejected(source: Vault, export_path: Path, tmp_path: Path) -> None:
    target = new_vault(tmp_path)
    data = export_path.read_bytes()
    export_path.write_bytes(redigest(flip_bit(data, len(data) - 40)))
    with pytest.raises(TamperedContentError):
        target.import_preview(export_path, EXPORT)
    export_path.write_bytes(redigest(flip_bit(data, 20)))  # salt
    with pytest.raises(WrongPasswordError):
        target.import_preview(export_path, EXPORT)
    assert len(target) == 0


def test_import_requires_an_unlocked_vault(
    source: Vault, export_path: Path, tmp_path: Path
) -> None:
    target = new_vault(tmp_path)
    preview = target.import_preview(export_path, EXPORT)
    target.lock()
    with pytest.raises(vault_module.SessionLockedError):
        target.import_apply(preview)
    with pytest.raises(vault_module.SessionLockedError):
        target.import_preview(export_path, EXPORT)


# --- Conflicts --------------------------------------------------------------


def test_reimport_into_the_same_vault_conflicts_by_id(source: Vault, export_path: Path) -> None:
    preview = source.import_preview(export_path, EXPORT)
    assert len(preview.conflicts) == 5
    assert {item.conflict_reason for item in preview.items} == {ConflictReason.SAME_ID}
    assert all(item.conflict_id == item.entry.id for item in preview.items)

    generation = source.generation
    assert source.import_apply(preview) == ImportResult(skipped=5)  # default: skip
    assert source.generation == generation  # nothing changed, nothing saved
    assert len(source) == 5


def test_conflict_by_site_and_username(source: Vault, export_path: Path, tmp_path: Path) -> None:
    target = new_vault(tmp_path)
    mine = target.add(**(synthetic_entry(2) | {"password": "CLAVE-SINTETICA-LOCAL-qpw"}))
    preview = target.import_preview(export_path, EXPORT)
    assert len(preview.conflicts) == 1
    conflict = preview.conflicts[0]
    assert conflict.conflict_reason is ConflictReason.SAME_SITE_AND_USERNAME
    assert conflict.conflict_id == mine.id
    assert conflict.entry.id != mine.id


def test_decisions_skip_replace_and_keep_both(
    source: Vault, export_path: Path, tmp_path: Path
) -> None:
    target = new_vault(tmp_path)
    local = [
        target.add(**(synthetic_entry(i) | {"password": f"CLAVE-SINTETICA-LOCAL-{i}"}))
        for i in (0, 1, 2)
    ]
    preview = target.import_preview(export_path, EXPORT)
    incoming = {item.entry.site: item.entry for item in preview.items}
    assert len(preview.conflicts) == 3

    result = target.import_apply(
        preview,
        {
            incoming[local[0].site].id: ImportDecision.SKIP,
            incoming[local[1].site].id: ImportDecision.REPLACE,
            incoming[local[2].site].id: ImportDecision.KEEP_BOTH,
        },
    )
    assert result == ImportResult(added=2, replaced=1, kept_both=1, skipped=1)
    assert len(target) == 6

    # Skip: the local entry is untouched.
    assert target.get(local[0].id) == local[0]
    # Replace: same local id and creation date, incoming data.
    replaced = target.get(local[1].id)
    assert replaced.password == synthetic_entry(1)["password"]
    assert replaced.created == local[1].created
    # Keep both: the local one stays and the incoming one gets a brand new id.
    assert target.get(local[2].id) == local[2]
    twins = target.list_entries(local[2].site)
    assert len(twins) == 2
    new_id = next(t.id for t in twins if t.id != local[2].id)
    assert new_id != incoming[local[2].site].id
    assert target.get(new_id).password == synthetic_entry(2)["password"]

    assert len(reopen(target.path, OTHER)) == 6


def test_keep_both_on_id_conflict_assigns_a_new_id(source: Vault, export_path: Path) -> None:
    preview = source.import_preview(export_path, EXPORT)
    decisions = {item.entry.id: ImportDecision.KEEP_BOTH for item in preview.items}
    assert source.import_apply(preview, decisions) == ImportResult(kept_both=5)
    ids = [s.id for s in source.list_entries()]
    assert len(ids) == len(set(ids)) == 10


def test_conflicts_are_recomputed_when_applying(
    source: Vault, export_path: Path, tmp_path: Path
) -> None:
    """The vault changed after the preview: the stale preview cannot create duplicates."""
    target = new_vault(tmp_path)
    preview = target.import_preview(export_path, EXPORT)
    assert preview.conflicts == ()
    target.add(**synthetic_entry(4))  # now one incoming entry collides
    assert target.import_apply(preview) == ImportResult(added=4, skipped=1)
    assert len(target) == 5


def test_import_cannot_exceed_the_entry_limit(
    source: Vault, export_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = new_vault(tmp_path)
    target.add(site="otro-sintetico.example", username="u", password="CLAVE-SINTETICA-otra")
    preview = target.import_preview(export_path, EXPORT)
    monkeypatch.setattr(vault_module, "MAX_ENTRIES", 5)
    before = snapshot(target.path.parent)
    with pytest.raises(ValidationError) as info:
        target.import_apply(preview)
    assert info.value.field == "entries"
    assert snapshot(target.path.parent) == before
    assert len(target) == 1


def test_preview_repr_shows_no_secret(source: Vault, export_path: Path) -> None:
    preview = source.import_preview(export_path, EXPORT)
    text = repr(preview) + repr(preview.items) + repr(preview.items[0])
    assert "CLAVE-SINTETICA" not in text
    assert "usuario.sintetico" not in text
    assert "sitio-sintetico" not in text
