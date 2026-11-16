"""Binary format v1: layout, round trip, check 1 (T4) and check 2 with bit flips (T5)."""

from __future__ import annotations

import hashlib
import itertools
import struct

import pytest

from pvlt import params
from pvlt.storage import CorruptedFileError, FormatError, Purpose, StorageError, unpack
from pvlt.storage import format as fmt
from tests.storage.helpers import flip_bit, make_file, patch, redigest

F = fmt.FIELD

# Offsets copied by hand from the table of docs/diseno.md section 5. They are
# deliberately not derived from the code: this is what pins the code to the design.
DESIGN_TABLE = [
    ("magic", 0, 4),
    ("format_version", 4, 6),
    ("purpose", 6, 7),
    ("kdf_id", 7, 8),
    ("kdf_version", 8, 9),
    ("m_cost", 9, 13),
    ("t_cost", 13, 17),
    ("parallelism", 17, 18),
    ("salt", 18, 34),
    ("aead_id", 34, 35),
    ("vault_id", 35, 51),
    ("generation", 51, 59),
    ("nonce_w", 59, 71),
    ("wrapped_key", 71, 119),
    ("nonce_d", 119, 131),
    ("len_c", 131, 135),
]


# --- Layout -----------------------------------------------------------------


def test_field_table_matches_the_design() -> None:
    assert [(f.name, f.start, f.end) for f in fmt.FIXED_FIELDS] == DESIGN_TABLE
    assert fmt.HEADER_LEN == 59
    assert fmt.FIXED_LEN == 135
    assert fmt.MIN_FILE_LEN == 135 + 4096 + 16 + 32


def test_structs_agree_with_the_table() -> None:
    assert fmt._HEADER_STRUCT.size == fmt.HEADER_LEN
    assert fmt._ENVELOPE_STRUCT.size == fmt.FIXED_LEN - fmt.HEADER_LEN


def test_file_fields_cover_the_whole_file_without_gaps() -> None:
    data = make_file(blocks=2).pack()
    fields = fmt.file_fields(2 * 4096 + 16)
    assert fields[0].start == 0
    assert all(a.end == b.start for a, b in itertools.pairwise(fields))
    assert fields[-1].end == len(data)
    assert fields[-1].name == "digest"
    assert fields[-1].size == 32


def test_pack_places_every_value_at_its_offset() -> None:
    vf = make_file(generation=0x0102030405060708, purpose=Purpose.EXPORT)
    data = vf.pack()

    def at(name: str) -> bytes:
        return data[F[name].start : F[name].end]

    assert at("magic") == b"PVLT"
    assert at("format_version") == b"\x00\x01"
    assert at("purpose") == b"\x02"
    assert at("kdf_id") == b"\x01"
    assert at("kdf_version") == b"\x13"
    assert at("m_cost") == (65536).to_bytes(4, "big")
    assert at("t_cost") == (3).to_bytes(4, "big")
    assert at("parallelism") == b"\x04"
    assert at("salt") == vf.header.salt
    assert at("aead_id") == b"\x01"
    assert at("vault_id") == vf.header.vault_id
    assert at("generation") == bytes(range(1, 9))  # big-endian
    assert at("nonce_w") == vf.nonce_w
    assert at("wrapped_key") == vf.wrapped_key
    assert at("nonce_d") == vf.nonce_d
    assert at("len_c") == (4112).to_bytes(4, "big")
    assert data[135 : 135 + 4112] == vf.ciphertext
    assert data[-32:] == hashlib.sha256(data[:-32]).digest()
    assert data[:59] == vf.header.pack()


@pytest.mark.parametrize("blocks", [1, 2, 37])
@pytest.mark.parametrize("purpose", list(Purpose))
def test_round_trip(blocks: int, purpose: Purpose) -> None:
    vf = make_file(generation=7, purpose=purpose, blocks=blocks)
    data = vf.pack()
    assert len(data) == 135 + blocks * 4096 + 16 + 32
    assert unpack(data, purpose) == vf
    assert unpack(data, purpose).pack() == data


def test_header_refuses_values_check_1_would_reject() -> None:
    good = make_file().header
    for change in (
        {"salt": bytes(15)},
        {"vault_id": bytes(17)},
        {"generation": 0},
        {"generation": 2**64},
        {"t_cost": 17},
        {"parallelism": 0},
        {"m_cost": params.M_COST_MAX_KIB + 1},
    ):
        fields = {name: getattr(good, name) for name in good.__dataclass_fields__} | change
        with pytest.raises(ValueError, match=r"bytes|out of range"):
            fmt.Header(**fields)


def test_vault_file_refuses_bad_lengths() -> None:
    vf = make_file()
    for change in (
        {"nonce_w": bytes(11)},
        {"nonce_d": bytes(13)},
        {"wrapped_key": bytes(47)},
        {"ciphertext": bytes(4096)},  # no room for the tag
        {"ciphertext": bytes(4113)},
        {"ciphertext": bytes(16)},
    ):
        fields = {name: getattr(vf, name) for name in vf.__dataclass_fields__} | change
        with pytest.raises(ValueError, match=r"bytes|out of range"):
            fmt.VaultFile(**fields)


# --- Check 1 (T4, format part). The digest is always recomputed, so the only
# --- thing that can reject these files is the structural check. -------------


def expect_format_error(data: bytes, reason: str, purpose: Purpose = Purpose.VAULT) -> None:
    with pytest.raises(FormatError) as info:
        unpack(data, purpose)
    assert info.value.reason == reason
    assert str(info.value) == "Formato no reconocido"


@pytest.mark.parametrize("length", [0, 1, 4, 58, 59, 134, 135, 167, 4278])
def test_truncated_file(length: int) -> None:
    expect_format_error(make_file().pack()[:length], "too_short")


def test_truncated_by_one_block_or_one_byte() -> None:
    data = make_file(blocks=2).pack()
    expect_format_error(data[:-1], "total_length")
    expect_format_error(data[:-4096], "total_length")


@pytest.mark.parametrize("extra", [1, 16, 4096])
def test_trailing_bytes(extra: int) -> None:
    expect_format_error(make_file().pack() + bytes(extra), "total_length")


def test_empty_and_garbage() -> None:
    expect_format_error(b"", "too_short")
    expect_format_error(bytes(8000), "magic")
    expect_format_error(b"{" + b" " * 8000, "magic")  # a plaintext JSON is not a vault


def test_file_larger_than_the_format_allows() -> None:
    expect_format_error(bytes(fmt.MAX_FILE_LEN + 1), "too_long")


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("magic", b"PVLU", "magic"),
        ("magic", b"pvlt", "magic"),
        ("format_version", b"\x00\x00", "format_version"),
        ("format_version", b"\x00\x02", "format_version"),
        ("format_version", b"\x01\x00", "format_version"),
        ("purpose", b"\x00", "purpose"),
        ("purpose", b"\x03", "purpose"),
        ("kdf_id", b"\x00", "kdf_id"),
        ("kdf_id", b"\x02", "kdf_id"),
        ("kdf_version", b"\x10", "kdf_version"),  # Argon2 v1.0
        ("kdf_version", b"\x14", "kdf_version"),
        ("aead_id", b"\x00", "aead_id"),
        ("aead_id", b"\x02", "aead_id"),
        ("generation", bytes(8), "generation"),
    ],
)
def test_unknown_identifiers(field: str, value: bytes, reason: str) -> None:
    data = patch(make_file().pack(), F[field].start, value)
    expect_format_error(data, reason)


def test_purpose_must_be_the_expected_one() -> None:
    """An export cannot be opened as a vault and a vault cannot be imported."""
    expect_format_error(make_file(purpose=Purpose.EXPORT).pack(), "purpose", Purpose.VAULT)
    expect_format_error(make_file(purpose=Purpose.VAULT).pack(), "purpose", Purpose.EXPORT)


@pytest.mark.parametrize(
    ("m_cost", "t_cost", "parallelism", "reason"),
    [
        (params.M_COST_MAX_KIB + 1, 3, 4, "m_cost"),
        (2**32 - 1, 3, 4, "m_cost"),
        (0, 3, 4, "m_cost"),
        (31, 3, 4, "m_cost"),  # below 8 KiB per lane
        (65536, 0, 4, "t_cost"),
        (65536, 17, 4, "t_cost"),
        (65536, 2**32 - 1, 4, "t_cost"),
        (65536, 3, 0, "parallelism"),
        (65536, 3, 17, "parallelism"),
        (65536, 3, 255, "parallelism"),
    ],
)
def test_kdf_parameters_out_of_limits(
    m_cost: int, t_cost: int, parallelism: int, reason: str
) -> None:
    """P7: a hostile header cannot ask for unbounded memory or time."""
    packed = struct.pack(">IIB", m_cost, t_cost, parallelism)
    data = patch(make_file().pack(), F["m_cost"].start, packed)
    expect_format_error(data, reason)


@pytest.mark.parametrize(
    ("m_cost", "t_cost", "parallelism"),
    [(8, 1, 1), (128, 16, 16), (params.M_COST_MAX_KIB, 1, 1)],
)
def test_kdf_parameters_at_the_limits_are_accepted(
    m_cost: int, t_cost: int, parallelism: int
) -> None:
    packed = struct.pack(">IIB", m_cost, t_cost, parallelism)
    data = patch(make_file().pack(), F["m_cost"].start, packed)
    header = unpack(data, Purpose.VAULT).header
    assert (header.m_cost, header.t_cost, header.parallelism) == (m_cost, t_cost, parallelism)


@pytest.mark.parametrize("len_c", [0, 16, 4096, 4111, 4113, 8192, 2**32 - 1])
def test_incoherent_len_c(len_c: int) -> None:
    data = patch(make_file().pack(), F["len_c"].start, len_c.to_bytes(4, "big"))
    expect_format_error(data, "len_c")


def test_len_c_valid_but_different_from_actual_size() -> None:
    data = patch(make_file(blocks=1).pack(), F["len_c"].start, (8192 + 16).to_bytes(4, "big"))
    expect_format_error(data, "total_length")
    data = patch(make_file(blocks=2).pack(), F["len_c"].start, (4096 + 16).to_bytes(4, "big"))
    expect_format_error(data, "total_length")


def test_check_1_runs_before_check_2() -> None:
    """A file that fails both is reported as unrecognized, not as damaged."""
    data = patch(make_file().pack(), 0, b"XXXX", fix_digest=False)
    expect_format_error(data, "magic")


# --- Check 2 and bit flips (T5, storage part) -------------------------------


def test_every_field_rejects_a_flipped_bit() -> None:
    """One bit altered in each field, first and last byte, digest left as it was."""
    data = make_file(blocks=2).pack()
    for field in fmt.file_fields(2 * 4096 + 16):
        for index, bit in ((field.start, 0), (field.end - 1, 7)):
            with pytest.raises(StorageError):
                unpack(flip_bit(data, index, bit), Purpose.VAULT)


def test_every_bit_of_the_fixed_part_and_the_tags_is_covered() -> None:
    data = make_file().pack()
    tag_of_c = range(len(data) - 32 - 16, len(data) - 32)
    digest = range(len(data) - 32, len(data))
    for index in [*range(fmt.FIXED_LEN), *tag_of_c, *digest]:
        for bit in range(8):
            with pytest.raises(StorageError):
                unpack(flip_bit(data, index, bit), Purpose.VAULT)


@pytest.mark.parametrize("field", ["salt", "vault_id", "nonce_w", "wrapped_key", "nonce_d"])
def test_accidental_damage_is_reported_as_corruption(field: str) -> None:
    data = flip_bit(make_file().pack(), F[field].start)
    with pytest.raises(CorruptedFileError) as info:
        unpack(data, Purpose.VAULT)
    assert str(info.value) == "Archivo dañado"


def test_damage_in_ciphertext_or_digest_is_reported_as_corruption() -> None:
    data = make_file().pack()
    for index in (
        fmt.FIXED_LEN,
        fmt.FIXED_LEN + 2000,
        len(data) - 33,
        len(data) - 32,
        len(data) - 1,
    ):
        with pytest.raises(CorruptedFileError):
            unpack(flip_bit(data, index), Purpose.VAULT)


@pytest.mark.parametrize(
    "field", ["salt", "vault_id", "generation", "nonce_w", "wrapped_key", "nonce_d"]
)
def test_digest_is_not_a_security_boundary(field: str) -> None:
    """Documented limit of this layer.

    Whoever alters a field and recomputes the SHA-256 gets past checks 1 and 2.
    Rejecting that file is the job of the AEAD tags in checks 3 and 4, which the
    vault tests cover (T5). This test exists so nobody mistakes the digest for
    integrity protection.
    """
    original = make_file(generation=5)
    tampered = redigest(flip_bit(original.pack(), F[field].start))
    assert unpack(tampered, Purpose.VAULT) != original


def test_swapping_ciphertext_between_files_passes_storage_only_with_a_new_digest() -> None:
    a, b = make_file().pack(), make_file().pack()
    swapped = a[: fmt.FIXED_LEN] + b[fmt.FIXED_LEN : -32] + a[-32:]
    with pytest.raises(CorruptedFileError):
        unpack(swapped, Purpose.VAULT)
    assert unpack(redigest(swapped), Purpose.VAULT).ciphertext == b[fmt.FIXED_LEN : -32]


def test_errors_do_not_echo_file_content() -> None:
    marker = b"SYNTHETIC-MARKER"
    data = patch(make_file().pack(), F["salt"].start, marker, fix_digest=False)
    with pytest.raises(StorageError) as info:
        unpack(data, Purpose.VAULT)
    text = f"{info.value!s} {info.value!r} {info.value.args}"
    assert "SYNTHETIC" not in text
    assert marker.hex() not in text
