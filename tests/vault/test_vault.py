"""Vault operations: T1 (life cycle), T2 (password change), T3 (no plaintext) and the session."""

from __future__ import annotations

import shutil
import unicodedata
from pathlib import Path

import pytest

from pvlt.params import CONFIG_A, Argon2Params
from pvlt.storage import Purpose, backup_path, load
from pvlt.vault import (
    EntryNotFoundError,
    GeneratorSettings,
    SessionLockedError,
    ValidationError,
    Vault,
    VaultExistsError,
    WrongPasswordError,
)
from pvlt.vault import vault as vault_module
from tests.vault.conftest import (
    MASTER,
    OTHER,
    FakeClock,
    fixed_now,
    reopen,
    snapshot,
    synthetic_entry,
)

# --- Create -----------------------------------------------------------------


def test_create_writes_an_empty_vault_that_reopens(vault: Vault, vault_path: Path) -> None:
    assert len(vault) == 0
    assert vault.generation == 1
    assert not vault.is_locked
    header = load(vault_path, Purpose.VAULT).header
    assert (header.m_cost, header.t_cost, header.parallelism) == (65536, 3, 4)
    assert header.generation == 1
    assert sorted(p.name for p in vault_path.parent.iterdir()) == ["boveda.pvlt"]
    assert len(reopen(vault_path)) == 0


def test_create_refuses_to_overwrite(vault: Vault, vault_path: Path) -> None:
    before = snapshot(vault_path.parent)
    with pytest.raises(VaultExistsError):
        Vault.create(vault_path, OTHER, params=CONFIG_A)
    assert snapshot(vault_path.parent) == before


def test_create_refuses_to_overwrite_a_file_that_is_not_a_vault(tmp_path: Path) -> None:
    target = tmp_path / "boveda.pvlt"
    target.write_bytes(b"something else")
    with pytest.raises(VaultExistsError):
        Vault.create(target, MASTER, params=CONFIG_A)
    assert target.read_bytes() == b"something else"


@pytest.mark.parametrize("password", ["", "short", "1234567"])
def test_create_rejects_weak_master_password(tmp_path: Path, password: str) -> None:
    with pytest.raises(ValidationError) as info:
        Vault.create(tmp_path / "boveda.pvlt", password, params=CONFIG_A)
    assert info.value.field == "password"
    assert list(tmp_path.iterdir()) == []


def test_create_requires_at_least_64_mib(tmp_path: Path) -> None:
    with pytest.raises(ValidationError) as info:
        Vault.create(tmp_path / "boveda.pvlt", MASTER, params=Argon2Params(65535, 3, 4))
    assert info.value.field == "m_cost"
    assert list(tmp_path.iterdir()) == []


def test_two_vaults_with_the_same_password_share_nothing(tmp_path: Path) -> None:
    Vault.create(tmp_path / "a.pvlt", MASTER, params=CONFIG_A)
    Vault.create(tmp_path / "b.pvlt", MASTER, params=CONFIG_A)
    a, b = load(tmp_path / "a.pvlt"), load(tmp_path / "b.pvlt")
    assert a.header.salt != b.header.salt
    assert a.header.vault_id != b.header.vault_id
    assert a.wrapped_key != b.wrapped_key
    assert a.ciphertext != b.ciphertext


# --- T1: create, close and reopen with 1, 100 and 500 entries ----------------


@pytest.mark.parametrize("count", [1, 100, pytest.param(500, marks=pytest.mark.slow)])
def test_t1_content_survives_close_and_reopen(vault: Vault, vault_path: Path, count: int) -> None:
    added = [vault.add(**synthetic_entry(i)) for i in range(count)]
    assert len(vault) == count
    assert vault.generation == 1 + count
    vault.lock()

    reopened = reopen(vault_path)
    assert len(reopened) == count
    assert [reopened.get(e.id) for e in added] == added
    assert [s.id for s in reopened.list_entries()] == [e.id for e in added]
    assert load(vault_path).header.generation == 1 + count


def test_t1_add_search_get_update_delete(vault: Vault, vault_path: Path) -> None:
    entries = [vault.add(**synthetic_entry(i)) for i in range(20)]
    target = entries[7]

    # Search: case-insensitive substring over site and username, no secrets in the listing.
    hits = vault.list_entries("SINTETICO-007")
    assert [h.id for h in hits] == [target.id]
    assert [h.id for h in vault.list_entries("usuario.sintetico.01")] == [
        e.id for e in entries[10:20]
    ]
    assert vault.list_entries("no-existe") == []
    assert len(vault.list_entries()) == 20
    assert not hasattr(hits[0], "password")
    assert not hasattr(hits[0], "notes")
    assert vault.list_entries("CLAVE-SINTETICA") == []  # passwords are not searchable

    # Get.
    assert vault.get(target.id).password == "CLAVE-SINTETICA-007-zxqj"

    # Update only what is given.
    updated = vault.update(target.id, password="CLAVE-SINTETICA-NUEVA-wvk", notes="")
    assert (updated.site, updated.username) == (target.site, target.username)
    assert updated.password == "CLAVE-SINTETICA-NUEVA-wvk"
    assert updated.notes == ""
    assert updated.created == target.created

    # Delete.
    vault.delete(entries[0].id)
    with pytest.raises(EntryNotFoundError):
        vault.get(entries[0].id)
    assert len(vault) == 19

    reopened = reopen(vault_path)
    assert reopened.get(target.id) == updated
    assert len(reopened) == 19
    with pytest.raises(EntryNotFoundError):
        reopened.get(entries[0].id)


def test_operations_on_unknown_ids(vault: Vault) -> None:
    missing = "99999999-9999-4999-8999-999999999999"
    generation = vault.generation
    for call in (
        lambda: vault.get(missing),
        lambda: vault.update(missing, site="x"),
        lambda: vault.delete(missing),
    ):
        with pytest.raises(EntryNotFoundError):
            call()
    assert vault.generation == generation


def test_invalid_input_is_rejected_without_saving(vault: Vault, vault_path: Path) -> None:
    kept = vault.add(**synthetic_entry(1))
    before = snapshot(vault_path.parent)
    with pytest.raises(ValidationError) as info:
        vault.add(site="", username="u", password="CLAVE-SINTETICA-x")
    assert info.value.field == "site"
    for blank in (" ", "   ", "\t\n"):
        with pytest.raises(ValidationError) as info:
            vault.add(site=blank, username="u", password="CLAVE-SINTETICA-x")
        assert info.value.field == "site"
        with pytest.raises(ValidationError):
            vault.update(kept.id, site=blank)
    with pytest.raises(ValidationError):
        vault.update(kept.id, password="")
    with pytest.raises(ValidationError):
        vault.update_settings(autolock_seconds=5)
    assert snapshot(vault_path.parent) == before
    assert vault.get(kept.id) == kept


def test_the_501st_entry_is_rejected(vault: Vault, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(vault_module, "MAX_ENTRIES", 3)
    for i in range(3):
        vault.add(**synthetic_entry(i))
    with pytest.raises(ValidationError) as info:
        vault.add(**synthetic_entry(3))
    assert info.value.field == "entries"
    assert len(vault) == 3


def test_settings_are_stored_in_the_vault(vault: Vault, vault_path: Path) -> None:
    generator = GeneratorSettings(length=40, lower=True, upper=True, digits=False, symbols=False)
    vault.update_settings(autolock_seconds=120, generator=generator)
    reopened = reopen(vault_path)
    assert reopened.settings.autolock_seconds == 120
    assert reopened.settings.generator == generator
    password = reopened.generate_password()
    assert len(password) == 40
    assert password.isalpha()


def test_every_save_keeps_the_previous_version_as_backup(vault: Vault, vault_path: Path) -> None:
    vault.add(**synthetic_entry(1))
    vault.add(**synthetic_entry(2))
    assert load(vault_path).header.generation == 3
    assert load(backup_path(vault_path)).header.generation == 2
    assert not vault_path.with_name("boveda.pvlt.tmp").exists()


def test_failed_save_leaves_session_and_disk_unchanged(
    vault: Vault, vault_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kept = vault.add(**synthetic_entry(1))
    before = snapshot(vault_path.parent)

    def failing_save(*args: object, **kwargs: object) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(vault_module, "atomic_save", failing_save)
    for call in (
        lambda: vault.add(**synthetic_entry(2)),
        lambda: vault.update(kept.id, notes="otra nota sintética"),
        lambda: vault.delete(kept.id),
        lambda: vault.update_settings(autolock_seconds=60),
        lambda: vault.change_password(MASTER, OTHER),
    ):
        with pytest.raises(OSError, match="No space left"):
            call()
    monkeypatch.undo()

    assert snapshot(vault_path.parent) == before
    assert vault.generation == 2
    assert vault.get(kept.id) == kept
    assert vault.settings.autolock_seconds == 300
    vault.add(**synthetic_entry(3))  # the session still works, with the old password
    assert len(reopen(vault_path)) == 2


# --- Lock and inactivity ----------------------------------------------------


def test_lock_erases_the_kek_and_blocks_everything(vault: Vault, vault_path: Path) -> None:
    entry = vault.add(**synthetic_entry(1))
    kek = vault._kek
    assert kek is not None
    assert any(kek)

    vault.lock()
    assert vault.is_locked
    assert kek == bytearray(32)  # overwritten in place, not just dereferenced
    assert vault._kek is None
    assert vault._content is None
    for call in (
        lambda: len(vault),
        lambda: vault.list_entries(),
        lambda: vault.get(entry.id),
        lambda: vault.add(**synthetic_entry(2)),
        lambda: vault.update(entry.id, notes="x"),
        lambda: vault.delete(entry.id),
        lambda: vault.settings,
        lambda: vault.generate_password(),
        lambda: vault.change_password(MASTER, OTHER),
        lambda: vault.export(vault_path.with_name("export.pvlt"), OTHER),
    ):
        with pytest.raises(SessionLockedError) as info:
            call()
        assert str(info.value) == "La bóveda está bloqueada"
    vault.lock()  # idempotent
    assert reopen(vault_path).get(entry.id) == entry


def test_t1_inactivity_locks_the_vault(vault: Vault, clock: FakeClock) -> None:
    entry = vault.add(**synthetic_entry(1))
    kek = vault._kek

    clock.advance(299)
    assert vault.seconds_until_autolock() == pytest.approx(1)
    assert not vault.is_locked  # looking at the state is not activity
    assert vault.get(entry.id) == entry  # activity: the timer restarts

    clock.advance(299)
    assert not vault.is_locked
    clock.advance(1)  # 300 s idle since the last operation
    with pytest.raises(SessionLockedError):
        vault.get(entry.id)
    assert vault.is_locked
    assert kek == bytearray(32)
    assert vault.seconds_until_autolock() == 0


def test_inactivity_is_detected_even_without_an_operation(vault: Vault, clock: FakeClock) -> None:
    kek = vault._kek
    clock.advance(301)
    assert vault.is_locked
    assert kek == bytearray(32)


def test_autolock_time_is_configurable(vault: Vault, clock: FakeClock) -> None:
    vault.update_settings(autolock_seconds=30)
    clock.advance(29)
    len(vault)
    clock.advance(30)
    with pytest.raises(SessionLockedError):
        len(vault)


def test_vault_repr_shows_no_secret(vault: Vault) -> None:
    vault.add(**synthetic_entry(1))
    assert repr(vault) == "Vault(locked=False)"


# --- T2: master password change ---------------------------------------------


def test_t2_change_password(vault: Vault, vault_path: Path, tmp_path: Path) -> None:
    entries = [vault.add(**synthetic_entry(i)) for i in range(5)]
    old = load(vault_path)
    old_kek = vault._kek

    vault.change_password(MASTER, OTHER)

    # Same content, new salt, next generation, old KEK erased.
    new = load(vault_path)
    assert new.header.salt != old.header.salt
    assert new.header.vault_id == old.header.vault_id
    assert new.header.generation == old.header.generation + 1
    assert old_kek == bytearray(32)
    assert [vault.get(e.id) for e in entries] == entries

    # The new password opens the vault, the old one does not.
    assert [reopen(vault_path, OTHER).get(e.id) for e in entries] == entries
    with pytest.raises(WrongPasswordError):
        reopen(vault_path, MASTER)

    # The same holds for the backup.
    restored = tmp_path / "restaurada" / "boveda.pvlt"
    restored.parent.mkdir()
    shutil.copyfile(backup_path(vault_path), restored)
    assert [reopen(restored, OTHER).get(e.id) for e in entries] == entries
    with pytest.raises(WrongPasswordError):
        reopen(restored, MASTER)

    # The session keeps working under the new key.
    vault.add(**synthetic_entry(99))
    assert len(reopen(vault_path, OTHER)) == 6


def test_change_password_requires_the_current_one(vault: Vault, vault_path: Path) -> None:
    vault.add(**synthetic_entry(1))
    before = snapshot(vault_path.parent)
    with pytest.raises(WrongPasswordError):
        vault.change_password("synthetic-wrong-password", OTHER)
    assert snapshot(vault_path.parent) == before
    assert len(reopen(vault_path, MASTER)) == 1
    vault.add(**synthetic_entry(2))  # session unaffected


def test_change_password_rejects_a_weak_new_one(vault: Vault, vault_path: Path) -> None:
    before = snapshot(vault_path.parent)
    with pytest.raises(ValidationError):
        vault.change_password(MASTER, "short")
    assert snapshot(vault_path.parent) == before


def test_password_is_not_normalized(tmp_path: Path) -> None:
    """Design 4.1: UTF-8 without normalization, so NFC and NFD are different passwords."""
    nfc = unicodedata.normalize("NFC", "contraseña-sintética-ñ")
    nfd = unicodedata.normalize("NFD", nfc)
    assert nfc != nfd
    path = tmp_path / "boveda.pvlt"
    Vault.create(path, nfc, params=CONFIG_A)
    reopen(path, nfc)
    with pytest.raises(WrongPasswordError):
        reopen(path, nfd)


# --- T3: nothing in the clear on disk ---------------------------------------


def test_t3_no_synthetic_data_appears_in_any_file(vault: Vault, vault_path: Path) -> None:
    markers = [MASTER, OTHER]
    for i in range(30):
        data = synthetic_entry(i)
        vault.add(**data)
        markers.extend(data.values())
    vault.change_password(MASTER, OTHER)
    vault.export(vault_path.with_name("export.pvlt"), "synthetic-export-password-003")
    markers.append("synthetic-export-password-003")
    # Fragments too, in case something was stored re-encoded or split.
    markers += ["sitio-sintetico", "usuario.sintetico", "CLAVE-SINTETICA", "nota sint", "schema"]

    files = snapshot(vault_path.parent)
    assert set(files) == {"boveda.pvlt", "boveda.pvlt.bak", "export.pvlt"}
    for name, blob in files.items():
        for marker in markers:
            for encoding in ("utf-8", "utf-16-le", "utf-16-be"):
                assert marker.encode(encoding) not in blob, (name, encoding)


def test_file_size_does_not_reveal_small_changes(vault: Vault, vault_path: Path) -> None:
    empty = vault_path.stat().st_size
    vault.add(**synthetic_entry(1))
    assert vault_path.stat().st_size == empty == 135 + 4096 + 16 + 32
    for i in range(2, 40):
        vault.add(**synthetic_entry(i))
    assert (vault_path.stat().st_size - 135 - 16 - 32) % 4096 == 0


def test_unlock_uses_the_injected_clock(vault_path: Path, vault: Vault) -> None:
    clock = FakeClock()
    reopened = Vault.unlock(vault_path, MASTER, clock=clock, now=fixed_now)
    clock.advance(10_000)
    assert reopened.is_locked
