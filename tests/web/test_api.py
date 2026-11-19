"""API over the vault: every operation of section 1, errors, recovery and the session lock."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from pvlt.params import CONFIG_A
from pvlt.storage import backup_path
from pvlt.vault import Vault, WrongPasswordError
from tests.storage.helpers import flip_bit
from tests.web.conftest import (
    ENTRY_PASSWORD,
    EXPORT,
    MASTER,
    NEW_MASTER,
    WRONG,
    FakeClock,
    Harness,
    build_harness,
)

OFFSET_IN_C = 300


def error_of(response) -> str:  # type: ignore[no-untyped-def]
    return response.json()["error"]


# --- Status, create, unlock and lock --------------------------------------------------


def test_status_without_vault(web: Harness) -> None:
    status = web.client.get("/api/status").json()
    assert status["vault"] == "missing"
    assert status["unlocked"] is False
    assert status["vault_name"] == "boveda.pvlt"
    assert status["can_restore_backup"] is False


def test_create_leaves_the_vault_unlocked(unlocked: Harness, vault_path: Path) -> None:
    assert vault_path.exists()
    status = unlocked.client.get("/api/status").json()
    assert status["unlocked"] is True
    assert status["vault"] == "ok"
    assert 0 < status["seconds_until_autolock"] <= 300
    header = vault_path.read_bytes()[9:18]
    assert int.from_bytes(header[:4], "big") == CONFIG_A.m_cost


def test_create_requires_matching_confirmation(web: Harness, vault_path: Path) -> None:
    response = web.client.post(
        "/api/create", json={"password": MASTER, "confirm": MASTER + "x", "config": "A"}
    )
    assert response.status_code == 422
    assert error_of(response) == "mismatch"
    assert not vault_path.exists()


@pytest.mark.parametrize("password", ["short", "x" * 1025])
def test_create_validates_length(web: Harness, vault_path: Path, password: str) -> None:
    response = web.client.post(
        "/api/create", json={"password": password, "confirm": password, "config": "A"}
    )
    assert response.status_code == 422
    assert response.json()["field"] == "password"
    assert not vault_path.exists()


def test_create_rejects_unknown_config(web: Harness) -> None:
    response = web.client.post(
        "/api/create", json={"password": MASTER, "confirm": MASTER, "config": "Z"}
    )
    assert response.status_code == 422
    assert response.json()["field"] == "config"


def test_create_refuses_to_overwrite(unlocked: Harness, vault_path: Path) -> None:
    before = vault_path.read_bytes()
    response = unlocked.client.post(
        "/api/create", json={"password": NEW_MASTER, "confirm": NEW_MASTER, "config": "A"}
    )
    assert response.status_code == 409
    assert error_of(response) == "exists"
    assert vault_path.read_bytes() == before


def test_lock_and_unlock(unlocked: Harness) -> None:
    unlocked.add()
    assert unlocked.client.post("/api/lock").json()["unlocked"] is False
    assert unlocked.state.vault is None
    locked = unlocked.client.get("/api/entries")
    assert locked.status_code == 423
    assert error_of(locked) == "locked"

    status = unlocked.client.post("/api/unlock", json={"password": MASTER}).json()
    assert status["unlocked"] is True
    assert len(unlocked.client.get("/api/entries").json()["entries"]) == 1


def test_wrong_password_is_400_and_leaves_the_file_intact(
    unlocked: Harness, vault_path: Path
) -> None:
    unlocked.client.post("/api/lock")
    before = vault_path.read_bytes()
    response = unlocked.client.post("/api/unlock", json={"password": WRONG})
    assert response.status_code == 400
    assert response.json() == {"error": "wrong_password", "message": "Contraseña incorrecta"}
    assert vault_path.read_bytes() == before
    assert unlocked.client.get("/api/status").json()["unlocked"] is False


def test_unlock_without_vault_is_404_and_creates_nothing(web: Harness, vault_path: Path) -> None:
    response = web.client.post("/api/unlock", json={"password": MASTER})
    assert response.status_code == 404
    assert error_of(response) == "no_vault"
    assert not vault_path.exists()


def test_unlock_unrecognized_file_is_422_format(web: Harness, vault_path: Path) -> None:
    vault_path.write_bytes(b"not a vault at all")
    response = web.client.post("/api/unlock", json={"password": MASTER})
    assert response.status_code == 422
    assert error_of(response) == "format"
    assert vault_path.read_bytes() == b"not a vault at all"


# --- Damaged vault and backup ----------------------------------------------------------


def damaged_with_backup(h: Harness, vault_path: Path) -> None:
    """Two saves so the backup exists, then one flipped bit in C of the vault."""
    h.add(1)
    h.add(2)
    h.client.post("/api/lock")
    vault_path.write_bytes(flip_bit(vault_path.read_bytes(), 135 + OFFSET_IN_C))


def test_corrupted_vault_offers_the_backup(unlocked: Harness, vault_path: Path) -> None:
    damaged_with_backup(unlocked, vault_path)
    response = unlocked.client.post("/api/unlock", json={"password": MASTER})
    assert response.status_code == 422
    assert error_of(response) == "corrupted"
    status = unlocked.client.get("/api/status").json()
    assert status["vault"] == "corrupted"
    assert status["can_restore_backup"] is True


def test_restore_requires_explicit_confirmation(unlocked: Harness, vault_path: Path) -> None:
    damaged_with_backup(unlocked, vault_path)
    unlocked.client.post("/api/unlock", json={"password": MASTER})
    damaged = vault_path.read_bytes()
    response = unlocked.client.post("/api/restore-backup", json={"confirm": False})
    assert response.status_code == 422
    assert vault_path.read_bytes() == damaged


def test_restore_backup(unlocked: Harness, vault_path: Path) -> None:
    damaged_with_backup(unlocked, vault_path)
    unlocked.client.post("/api/unlock", json={"password": MASTER})
    response = unlocked.client.post("/api/restore-backup", json={"confirm": True})
    assert response.status_code == 200
    kept = response.json()["kept"]
    assert kept.startswith("boveda.pvlt.damaged-")
    assert (vault_path.parent / kept).exists()
    assert response.json()["vault"] == "ok"
    unlocked.client.post("/api/unlock", json={"password": MASTER})
    assert len(unlocked.client.get("/api/entries").json()["entries"]) == 1


def test_restore_without_usable_backup_is_409(unlocked: Harness) -> None:
    response = unlocked.client.post("/api/restore-backup", json={"confirm": True})
    assert response.status_code == 409
    assert error_of(response) == "no_backup"


def test_rollback_warning_at_startup(vault_path: Path, clock: FakeClock) -> None:
    vault = Vault.create(vault_path, MASTER, params=CONFIG_A)
    vault.add(site="s", username="u", password="p")
    newer = vault_path.read_bytes()
    vault.add(site="s2", username="u", password="p")
    vault.lock()
    backup_path(vault_path).write_bytes(vault_path.read_bytes())
    vault_path.write_bytes(newer)  # the vault is now older than its backup
    h = build_harness(vault_path, clock)
    with h.client:
        h.login()
        status = h.client.get("/api/status").json()
    h.workspace.close()
    assert status["possible_rollback"] is True
    assert status["backup_generation"] > status["vault_generation"]


# --- Entries -----------------------------------------------------------------------------


def test_listing_has_no_passwords_or_notes(unlocked: Harness) -> None:
    unlocked.add(1)
    unlocked.add(2)
    response = unlocked.client.get("/api/entries")
    entries = response.json()["entries"]
    assert len(entries) == 2
    for entry in entries:
        assert set(entry) == {"id", "site", "username", "modified"}
    assert ENTRY_PASSWORD not in response.text


def test_detail_has_no_password_and_password_comes_alone(unlocked: Harness) -> None:
    entry_id = unlocked.add(7)
    detail = unlocked.client.get(f"/api/entries/{entry_id}")
    assert "password" not in detail.json()
    assert ENTRY_PASSWORD not in detail.text
    assert detail.json()["created"] == "2026-11-19T12:00:00Z"
    password = unlocked.client.get(f"/api/entries/{entry_id}/password").json()
    assert password == {"password": f"{ENTRY_PASSWORD}-7"}


def test_update_changes_only_the_given_fields(unlocked: Harness) -> None:
    entry_id = unlocked.add(1)
    response = unlocked.client.put(f"/api/entries/{entry_id}", json={"password": "nueva-sint"})
    assert response.status_code == 200
    assert response.json()["site"].endswith("-1")
    assert unlocked.client.get(f"/api/entries/{entry_id}/password").json()["password"] == (
        "nueva-sint"
    )


def test_delete(unlocked: Harness) -> None:
    entry_id = unlocked.add(1)
    assert unlocked.client.delete(f"/api/entries/{entry_id}").status_code == 200
    assert unlocked.client.get("/api/entries").json()["entries"] == []
    missing = unlocked.client.get(f"/api/entries/{entry_id}")
    assert missing.status_code == 404
    assert error_of(missing) == "not_found"


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"site": "", "password": "p"}, "site"),
        ({"site": "s", "password": ""}, "password"),
        ({"site": "s", "password": "p", "notes": "x" * 8193}, "notes"),
        ({"site": "s\x00", "password": "p"}, "site"),
        ({"site": "s"}, "password"),
    ],
)
def test_invalid_entries_are_422_with_the_field(
    unlocked: Harness, body: dict[str, str], field: str
) -> None:
    response = unlocked.client.post("/api/entries", json=body)
    assert response.status_code == 422
    assert response.json()["field"] == field
    assert unlocked.client.get("/api/entries").json()["entries"] == []


def test_changes_persist_after_reopening(unlocked: Harness, vault_path: Path) -> None:
    ids = [unlocked.add(i) for i in range(5)]
    unlocked.client.delete(f"/api/entries/{ids[0]}")
    unlocked.client.put(f"/api/entries/{ids[1]}", json={"notes": "cambiada"})
    unlocked.client.post("/api/lock")
    vault = Vault.unlock(vault_path, MASTER)
    try:
        assert len(vault) == 4
        assert vault.get(ids[1]).notes == "cambiada"
    finally:
        vault.lock()


# --- Generator and settings ---------------------------------------------------------------


def test_generate(web: Harness) -> None:
    body = {"length": 32, "lower": True, "upper": True, "digits": True, "symbols": False}
    data = web.client.post("/api/generate", json=body).json()
    assert len(data["password"]) == 32
    assert data["password"].isalnum()
    assert data["entropy_bits"] == pytest.approx(32 * 5.954196310386876)


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"length": 7}, "generator.length"),
        ({"length": 129}, "generator.length"),
        ({"lower": False, "upper": False, "digits": False, "symbols": False}, "generator.classes"),
        ({"length": "20"}, "length"),
    ],
)
def test_generate_rejects_bad_settings(web: Harness, body: dict[str, object], field: str) -> None:
    response = web.client.post("/api/generate", json=body)
    assert response.status_code == 422
    assert response.json()["field"] == field


def test_settings(unlocked: Harness) -> None:
    settings = unlocked.client.get("/api/settings").json()
    assert settings["autolock_seconds"] == 300
    generator = {**settings["generator"], "length": 40}
    updated = unlocked.client.put(
        "/api/settings", json={"autolock_seconds": 60, "generator": generator}
    ).json()
    assert updated == {"autolock_seconds": 60, "generator": generator}
    bad = unlocked.client.put("/api/settings", json={"autolock_seconds": 10})
    assert bad.status_code == 422
    assert bad.json()["field"] == "autolock_seconds"


# --- Inactivity --------------------------------------------------------------------------


def test_inactivity_locks_the_vault(unlocked: Harness, clock: FakeClock) -> None:
    unlocked.add()
    clock.advance(299)
    assert unlocked.client.get("/api/entries").status_code == 200  # counts as activity
    clock.advance(299)
    assert unlocked.client.get("/api/status").json()["seconds_until_autolock"] == pytest.approx(1)
    clock.advance(1)
    response = unlocked.client.get("/api/entries")
    assert response.status_code == 423
    assert unlocked.state.vault is None


def test_status_does_not_count_as_activity(unlocked: Harness, clock: FakeClock) -> None:
    for _ in range(4):
        clock.advance(80)
        unlocked.client.get("/api/status")
    assert unlocked.client.get("/api/status").json()["unlocked"] is False


def test_background_watcher_erases_the_key_without_requests(
    vault_path: Path, clock: FakeClock
) -> None:
    h = build_harness(vault_path, clock, autolock_poll=0.02)
    with h.client:
        h.login()
        h.create()
        vault = h.state.vault
        assert vault is not None
        clock.advance(301)
        deadline = time.monotonic() + 5
        while h.state.vault is not None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert h.state.vault is None
        assert vault._kek is None  # erased by lock()
    h.workspace.close()


def test_shutdown_locks_the_vault(vault_path: Path, clock: FakeClock) -> None:
    h = build_harness(vault_path, clock)
    with h.client:
        h.login()
        h.create()
        vault = h.state.vault
        assert vault is not None
    assert h.state.vault is None
    assert vault.is_locked
    h.workspace.close()


# --- Master password ----------------------------------------------------------------------


def test_change_password(unlocked: Harness, vault_path: Path) -> None:
    unlocked.add()
    unlocked.add(2)  # a second save so a backup exists
    response = unlocked.client.post(
        "/api/change-password",
        json={"current": MASTER, "new": NEW_MASTER, "confirm": NEW_MASTER},
    )
    assert response.status_code == 200
    unlocked.client.post("/api/lock")
    for path in (vault_path, backup_path(vault_path)):
        Vault.unlock(path, NEW_MASTER).lock()
        with pytest.raises(WrongPasswordError):
            Vault.unlock(path, MASTER)


def test_change_password_errors(unlocked: Harness, vault_path: Path) -> None:
    before = vault_path.read_bytes()
    mismatch = unlocked.client.post(
        "/api/change-password", json={"current": MASTER, "new": NEW_MASTER, "confirm": "otra"}
    )
    assert error_of(mismatch) == "mismatch"
    wrong = unlocked.client.post(
        "/api/change-password", json={"current": WRONG, "new": NEW_MASTER, "confirm": NEW_MASTER}
    )
    assert wrong.status_code == 400
    short = unlocked.client.post(
        "/api/change-password", json={"current": MASTER, "new": "corta", "confirm": "corta"}
    )
    assert short.status_code == 422
    assert vault_path.read_bytes() == before
    assert unlocked.client.get("/api/status").json()["unlocked"] is True


# --- Export and import ----------------------------------------------------------------------


def export(h: Harness, filename: str = "exportacion.pvlt", **extra: object):  # type: ignore[no-untyped-def]
    body = {"filename": filename, "password": EXPORT, "confirm": EXPORT, **extra}
    return h.client.post("/api/export", json=body)


@pytest.mark.parametrize(
    "filename",
    [
        "boveda.pvlt",
        "../fuera.pvlt",
        "sub/dir.pvlt",
        "exportacion.txt",
        "boveda.pvlt.bak",
        ".oculto.pvlt",
        "/tmp/abs.pvlt",  # noqa: S108 - a rejected name, never created
        "C:\\abs.pvlt",
        "",
        "x" * 120 + ".pvlt",
    ],
)
def test_export_rejects_paths_and_vault_files(
    unlocked: Harness, vault_path: Path, filename: str
) -> None:
    files_before = sorted(p.name for p in vault_path.parent.iterdir())
    response = export(unlocked, filename)
    assert response.status_code == 422
    assert response.json()["field"] == "filename"
    assert sorted(p.name for p in vault_path.parent.iterdir()) == files_before


def test_export_and_import_round_trip(unlocked: Harness, vault_path: Path) -> None:
    ids = [unlocked.add(i) for i in range(3)]
    response = export(unlocked)
    assert response.json() == {"filename": "exportacion.pvlt", "entries": 3}
    assert (vault_path.parent / "exportacion.pvlt").exists()
    assert not (vault_path.parent / "exportacion.pvlt.bak").exists()
    assert unlocked.client.get("/api/files").json() == {"files": ["exportacion.pvlt"]}

    again = export(unlocked)
    assert again.status_code == 409
    assert export(unlocked, overwrite=True).status_code == 200

    unlocked.client.delete(f"/api/entries/{ids[0]}")
    unlocked.client.put(f"/api/entries/{ids[1]}", json={"notes": "local"})

    preview = unlocked.client.post(
        "/api/import/preview", json={"filename": "exportacion.pvlt", "password": EXPORT}
    )
    assert preview.status_code == 200
    data = preview.json()
    assert len(data["items"]) == 3
    assert data["conflicts"] == 2
    assert ENTRY_PASSWORD not in preview.text
    for item in data["items"]:
        assert "password" not in item and "notes" not in item
    conflicts = {item["id"]: item["conflict"] for item in data["items"]}
    assert conflicts[ids[0]] is None
    assert conflicts[ids[1]] == "id"

    result = unlocked.client.post(
        "/api/import/apply",
        json={
            "preview_id": data["preview_id"],
            "decisions": {ids[1]: "replace", ids[2]: "keep_both"},
        },
    ).json()
    assert result == {"added": 1, "replaced": 1, "kept_both": 1, "skipped": 0}
    assert len(unlocked.client.get("/api/entries").json()["entries"]) == 4
    assert unlocked.client.get(f"/api/entries/{ids[1]}").json()["notes"] != "local"

    stale = unlocked.client.post("/api/import/apply", json={"preview_id": data["preview_id"]})
    assert stale.status_code == 409
    assert error_of(stale) == "no_preview"


def test_import_errors(unlocked: Harness) -> None:
    unlocked.add()
    missing = unlocked.client.post(
        "/api/import/preview", json={"filename": "no-existe.pvlt", "password": EXPORT}
    )
    assert missing.status_code == 404
    assert error_of(missing) == "no_file"

    export(unlocked)
    wrong = unlocked.client.post(
        "/api/import/preview", json={"filename": "exportacion.pvlt", "password": WRONG}
    )
    assert wrong.status_code == 400

    vault_as_import = unlocked.client.post(
        "/api/import/preview", json={"filename": "boveda.pvlt", "password": MASTER}
    )
    assert vault_as_import.status_code == 422


def test_unknown_decision_is_rejected(unlocked: Harness) -> None:
    response = unlocked.client.post(
        "/api/import/apply", json={"preview_id": "x", "decisions": {"a": "merge"}}
    )
    assert response.status_code == 422


def test_lock_discards_the_preview(unlocked: Harness) -> None:
    unlocked.add()
    export(unlocked)
    preview = unlocked.client.post(
        "/api/import/preview", json={"filename": "exportacion.pvlt", "password": EXPORT}
    ).json()
    unlocked.client.post("/api/lock")
    unlocked.client.post("/api/unlock", json={"password": MASTER})
    response = unlocked.client.post("/api/import/apply", json={"preview_id": preview["preview_id"]})
    assert response.status_code == 409
