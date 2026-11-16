"""T4, T5 and T6 with real keys: failed opens, tampering with a recomputed digest, nonce uniqueness.

Storage already rejects accidental damage (digest left stale). Here every altered
file gets a fresh, valid SHA-256, so the only thing that can reject it is the
structural check or an AEAD tag. That is the property the project claims (P3).
"""

from __future__ import annotations

import os
import struct
from pathlib import Path

import pytest

from pvlt import params
from pvlt.crypto import AuthenticationError, derive_kek, open_
from pvlt.storage import (
    CorruptedFileError,
    FormatError,
    Header,
    Purpose,
    StorageError,
    load,
    unpack,
)
from pvlt.storage import format as fmt
from pvlt.vault import TamperedContentError, Vault, VaultError, WrongPasswordError
from pvlt.vault import vault as vault_module
from pvlt.vault.envelope import open_file, seal_file
from pvlt.vault.model import Content, serialize_content
from tests.storage.helpers import flip_bit, patch, redigest
from tests.vault.conftest import MASTER, OTHER, reopen, snapshot, synthetic_entry

F = fmt.FIELD
REJECTIONS = (StorageError, VaultError)


@pytest.fixture
def populated(vault: Vault, vault_path: Path) -> Path:
    """A locked vault with a few entries and a backup. Returns its path."""
    for i in range(3):
        vault.add(**synthetic_entry(i))
    vault.lock()
    return vault_path


def assert_rejected(path: Path, tampered: bytes, expected: type[Exception]) -> None:
    """Opening `tampered` fails with `expected` and leaves the directory byte-identical."""
    path.write_bytes(tampered)
    before = snapshot(path.parent)
    with pytest.raises(expected):
        reopen(path)
    assert snapshot(path.parent) == before
    assert not path.with_name(path.name + ".tmp").exists()


# --- T4 ---------------------------------------------------------------------


def test_t4_wrong_password(populated: Path) -> None:
    before = snapshot(populated.parent)
    for wrong in (OTHER, MASTER + " ", MASTER[:-1], MASTER.upper(), ""):
        with pytest.raises(WrongPasswordError) as info:
            reopen(populated, wrong)
        assert str(info.value) == "Contraseña incorrecta"
    assert snapshot(populated.parent) == before
    assert len(reopen(populated)) == 3  # still opens with the right one


def test_t4_missing_vault_is_not_created(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        reopen(tmp_path / "boveda.pvlt")
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("keep", [0, 10, 59, 135, 2000, -33, -1])
def test_t4_truncated_file(populated: Path, keep: int) -> None:
    data = populated.read_bytes()
    assert_rejected(populated, data[:keep], FormatError)


def test_t4_unknown_version(populated: Path) -> None:
    data = patch(populated.read_bytes(), F["format_version"].start, b"\x00\x02")
    assert_rejected(populated, data, FormatError)


@pytest.mark.parametrize(
    ("m_cost", "t_cost", "parallelism"),
    [
        (params.M_COST_MAX_KIB + 1, 3, 4),
        (2**32 - 1, 3, 4),
        (65536, 17, 4),
        (65536, 2**32 - 1, 4),
        (65536, 3, 17),
        (65536, 3, 0),
        (16, 3, 4),
    ],
)
def test_t4_parameters_out_of_limits_never_reach_argon2(
    populated: Path, monkeypatch: pytest.MonkeyPatch, m_cost: int, t_cost: int, parallelism: int
) -> None:
    """P7 end to end: a hostile header is rejected before any derivation starts."""

    def must_not_run(*args: object, **kwargs: object) -> bytearray:
        raise AssertionError("Argon2id ran with out-of-range parameters")

    monkeypatch.setattr(vault_module, "derive_kek", must_not_run)
    packed = struct.pack(">IIB", m_cost, t_cost, parallelism)
    data = patch(populated.read_bytes(), F["m_cost"].start, packed)
    assert_rejected(populated, data, FormatError)


def test_t4_an_export_is_not_a_vault(vault: Vault, vault_path: Path, tmp_path: Path) -> None:
    export = tmp_path / "export.pvlt"
    vault.export(export, OTHER)
    with pytest.raises(FormatError):
        reopen(export, OTHER)


def test_t4_stale_digest_is_reported_as_damage(populated: Path) -> None:
    data = flip_bit(populated.read_bytes(), 1000)
    assert_rejected(populated, data, CorruptedFileError)


# --- T5: one bit in each field, digest recomputed ---------------------------

EXPECTED_BY_FIELD = {
    # Structural fields: check 1.
    "magic": FormatError,
    "format_version": FormatError,
    "purpose": FormatError,
    "kdf_id": FormatError,
    "kdf_version": FormatError,
    "aead_id": FormatError,
    "len_c": FormatError,
    # Authenticated through W: indistinguishable from a wrong password (declared limit).
    "m_cost": WrongPasswordError,
    "t_cost": WrongPasswordError,
    "parallelism": WrongPasswordError,
    "salt": WrongPasswordError,
    "vault_id": WrongPasswordError,
    "generation": WrongPasswordError,
    "nonce_w": WrongPasswordError,
    "wrapped_key": WrongPasswordError,
    # Authenticated through C.
    "nonce_d": TamperedContentError,
    "ciphertext": TamperedContentError,
}


@pytest.mark.parametrize("field", list(EXPECTED_BY_FIELD))
def test_t5_flipped_bit_in_each_field(populated: Path, field: str) -> None:
    """Lowest bit of the last byte of each field, then a valid digest on top."""
    data = populated.read_bytes()
    layout = {f.name: f for f in fmt.file_fields(len(data) - fmt.FIXED_LEN - fmt.DIGEST_LEN)}
    tampered = redigest(flip_bit(data, layout[field].end - 1))
    unpack_ok = field not in ("magic", "format_version", "purpose", "kdf_id", "kdf_version")
    if unpack_ok and EXPECTED_BY_FIELD[field] is not FormatError:
        unpack(tampered, Purpose.VAULT)  # storage alone accepts it: only the AEAD can object
    assert_rejected(populated, tampered, EXPECTED_BY_FIELD[field])


def test_t5_every_field_first_and_last_byte(populated: Path) -> None:
    data = populated.read_bytes()
    for field in fmt.file_fields(len(data) - fmt.FIXED_LEN - fmt.DIGEST_LEN):
        if field.name == "digest":
            continue  # recomputed below, covered by the stale-digest test
        for index, bit in ((field.start, 7), (field.end - 1, 0)):
            assert_rejected(populated, redigest(flip_bit(data, index, bit)), REJECTIONS)


def test_t5_both_tags(populated: Path) -> None:
    """The tags are the last 16 bytes of W and of C."""
    data = populated.read_bytes()
    tag_w = range(F["wrapped_key"].end - 16, F["wrapped_key"].end)
    tag_c = range(len(data) - 32 - 16, len(data) - 32)
    for index in tag_w:
        assert_rejected(populated, redigest(flip_bit(data, index)), WrongPasswordError)
    for index in tag_c:
        assert_rejected(populated, redigest(flip_bit(data, index)), TamperedContentError)


def test_t5_ciphertext_sampled_across_all_blocks(populated: Path) -> None:
    data = populated.read_bytes()
    for index in range(fmt.FIXED_LEN, len(data) - 32, 257):
        assert_rejected(populated, redigest(flip_bit(data, index, index % 8)), TamperedContentError)


def test_t5_swapping_c_between_vaults(tmp_path: Path) -> None:
    """Two vaults with the same password: C of one cannot be planted in the other."""
    paths = [tmp_path / name / "boveda.pvlt" for name in ("a", "b")]
    for i, path in enumerate(paths):
        path.parent.mkdir()
        v = Vault.create(path, MASTER, params=params.CONFIG_A)
        v.add(**synthetic_entry(i))
        v.lock()
    a, b = (p.read_bytes() for p in paths)
    assert len(a) == len(b)
    body = slice(fmt.FIXED_LEN, len(a) - 32)

    # Only C.
    assert_rejected(
        paths[0], redigest(a[: fmt.FIXED_LEN] + b[body] + a[-32:]), TamperedContentError
    )
    # C together with its nonce.
    start = F["nonce_d"].start
    assert_rejected(paths[0], redigest(a[:start] + b[start:]), TamperedContentError)
    # C, its nonce and its wrapped key: now W is bound to another header.
    start = F["nonce_w"].start
    assert_rejected(paths[0], redigest(a[:start] + b[start:]), WrongPasswordError)
    # The other vault whole is a valid file, which is why rollback is only warned about.
    paths[0].write_bytes(b)
    assert reopen(paths[0]).list_entries()[0].site == "sitio-sintetico-001.example"


def test_t5_c_of_an_older_generation_of_the_same_vault(vault: Vault, vault_path: Path) -> None:
    """The generation is in the associated data, so parts of two saves cannot be mixed."""
    vault.add(**synthetic_entry(1))
    old = vault_path.read_bytes()
    vault.add(**synthetic_entry(2))
    new = vault_path.read_bytes()
    vault.lock()
    assert len(old) == len(new)
    start = F["nonce_w"].start
    assert_rejected(vault_path, redigest(new[:start] + old[start:]), WrongPasswordError)
    assert_rejected(vault_path, redigest(old[:start] + new[start:]), WrongPasswordError)


def test_t5_domain_labels_are_not_interchangeable() -> None:
    """A file sealed with the two labels swapped does not open."""
    header = Header(Purpose.VAULT, 65536, 3, 4, os.urandom(16), os.urandom(16), 1)
    kek = os.urandom(32)
    good = unpack(seal_file(kek, header, serialize_content(Content())), Purpose.VAULT)
    assert open_file(kek, good) == serialize_content(Content())

    hdr = header.pack()
    dek = open_(kek, good.nonce_w, good.wrapped_key, b"PVLT/v1/wrap" + hdr)
    with pytest.raises(AuthenticationError):
        open_(kek, good.nonce_w, good.wrapped_key, b"PVLT/v1/data" + hdr)
    with pytest.raises(AuthenticationError):
        open_(dek, good.nonce_d, good.ciphertext, b"PVLT/v1/wrap" + hdr + good.wrapped_key)
    # And the exact associated data of the design does open C.
    open_(dek, good.nonce_d, good.ciphertext, b"PVLT/v1/data" + hdr + good.wrapped_key)


def test_content_that_authenticates_but_is_not_a_valid_content(tmp_path: Path) -> None:
    """Check 4 also covers padding and schema, for a file made by someone who has the key."""
    header = Header(Purpose.VAULT, 65536, 3, 4, os.urandom(16), os.urandom(16), 1)
    kek = derive_kek(MASTER.encode(), header.salt, 65536, 3, 4)
    path = tmp_path / "boveda.pvlt"
    path.write_bytes(seal_file(kek, header, b'{"schema":2,"entries":[],"settings":{}}'))
    with pytest.raises(TamperedContentError) as info:
        reopen(path)
    assert info.value.reason == "schema"


# --- T6: fresh DEK and nonces on every save ---------------------------------


def test_t6_ten_thousand_saves_never_repeat_dek_or_nonce() -> None:
    header = Header(Purpose.VAULT, 65536, 3, 4, os.urandom(16), os.urandom(16), 1)
    kek = os.urandom(32)
    content = serialize_content(Content())
    wrap_aad = b"PVLT/v1/wrap" + header.pack()

    nonces_w: set[bytes] = set()
    nonces_d: set[bytes] = set()
    deks: set[bytes] = set()
    wrapped: set[bytes] = set()
    for _ in range(10_000):
        file = unpack(seal_file(kek, header, content), Purpose.VAULT)
        nonces_w.add(file.nonce_w)
        nonces_d.add(file.nonce_d)
        wrapped.add(file.wrapped_key)
        deks.add(open_(kek, file.nonce_w, file.wrapped_key, wrap_aad))

    assert len(nonces_w) == len(nonces_d) == len(deks) == len(wrapped) == 10_000
    assert not nonces_w & nonces_d
    assert all(len(d) == 32 for d in deks)


@pytest.mark.slow
def test_t6_saves_through_the_vault_on_disk(vault: Vault, vault_path: Path) -> None:
    """Same property through the real path: operation, atomic save, file on disk."""
    kek = bytes(vault._kek or b"")
    entry = vault.add(**synthetic_entry(0))
    seen_nonces: set[bytes] = set()
    seen_deks: set[bytes] = set()
    generations: list[int] = []
    for i in range(200):
        vault.update(entry.id, notes=f"nota sintética {i}")
        file = load(vault_path)
        generations.append(file.header.generation)
        seen_nonces |= {file.nonce_w, file.nonce_d}
        aad = b"PVLT/v1/wrap" + file.header.pack()
        seen_deks.add(open_(kek, file.nonce_w, file.wrapped_key, aad))
    assert len(seen_nonces) == 400
    assert len(seen_deks) == 200
    assert generations == list(range(3, 203))  # no persistent counter other than this one
