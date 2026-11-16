"""Behaviour of the crypto layer beyond the published vectors. All data is synthetic."""

from __future__ import annotations

import pytest

from pvlt import params
from pvlt.crypto import (
    AuthenticationError,
    KdfParameterError,
    derive_kek,
    open_,
    random_bytes,
    seal,
    validate_kdf_params,
    zeroize,
)
from pvlt.crypto import kdf as kdf_module
from pvlt.params import CONFIG_A

KEY = bytes(range(32))
NONCE = bytes(range(12))
AAD = params.WRAP_LABEL + b"synthetic-header"
PLAINTEXT = b"synthetic plaintext, not a real secret"

# Small parameters for tests that only care about the interface, not the cost.
FAST = {"m_cost": 64, "t_cost": 1, "parallelism": 1}


# --- AEAD -------------------------------------------------------------------


def test_seal_open_roundtrip() -> None:
    sealed = seal(KEY, NONCE, PLAINTEXT, AAD)
    assert len(sealed) == len(PLAINTEXT) + params.TAG_LEN
    assert PLAINTEXT not in sealed
    assert open_(KEY, NONCE, sealed, AAD) == PLAINTEXT


def test_seal_accepts_bytearray_key() -> None:
    assert seal(bytearray(KEY), NONCE, PLAINTEXT, AAD) == seal(KEY, NONCE, PLAINTEXT, AAD)


def test_empty_plaintext_is_authenticated() -> None:
    sealed = seal(KEY, NONCE, b"", AAD)
    assert len(sealed) == params.TAG_LEN
    assert open_(KEY, NONCE, sealed, AAD) == b""
    with pytest.raises(AuthenticationError):
        open_(KEY, NONCE, sealed, AAD + b"x")


def test_open_rejects_wrong_key() -> None:
    sealed = seal(KEY, NONCE, PLAINTEXT, AAD)
    with pytest.raises(AuthenticationError):
        open_(bytes(32), NONCE, sealed, AAD)


def test_open_rejects_wrong_nonce() -> None:
    sealed = seal(KEY, NONCE, PLAINTEXT, AAD)
    with pytest.raises(AuthenticationError):
        open_(KEY, bytes(12), sealed, AAD)


def test_open_rejects_wrong_domain_label() -> None:
    """Something sealed as `wrap` must not open as `data` (domain separation)."""
    sealed = seal(KEY, NONCE, PLAINTEXT, params.WRAP_LABEL + b"hdr")
    with pytest.raises(AuthenticationError):
        open_(KEY, NONCE, sealed, params.DATA_LABEL + b"hdr")


def test_open_rejects_every_single_bit_flip() -> None:
    sealed = seal(KEY, NONCE, PLAINTEXT, AAD)
    for i in range(len(sealed) * 8):
        tampered = bytearray(sealed)
        tampered[i // 8] ^= 1 << (i % 8)
        with pytest.raises(AuthenticationError):
            open_(KEY, NONCE, bytes(tampered), AAD)


@pytest.mark.parametrize("length", [0, 1, 15])
def test_open_rejects_input_shorter_than_tag(length: int) -> None:
    with pytest.raises(AuthenticationError):
        open_(KEY, NONCE, bytes(length), AAD)


def test_open_rejects_truncation() -> None:
    sealed = seal(KEY, NONCE, PLAINTEXT, AAD)
    with pytest.raises(AuthenticationError):
        open_(KEY, NONCE, sealed[:-1], AAD)


@pytest.mark.parametrize("key_len", [0, 16, 31, 33])
def test_bad_key_length(key_len: int) -> None:
    with pytest.raises(ValueError, match="key must be 32 bytes"):
        seal(bytes(key_len), NONCE, PLAINTEXT, AAD)
    with pytest.raises(ValueError, match="key must be 32 bytes"):
        open_(bytes(key_len), NONCE, bytes(32), AAD)


@pytest.mark.parametrize("nonce_len", [0, 8, 11, 13, 24])
def test_bad_nonce_length(nonce_len: int) -> None:
    with pytest.raises(ValueError, match="nonce must be 12 bytes"):
        seal(KEY, bytes(nonce_len), PLAINTEXT, AAD)


def test_authentication_error_carries_no_data() -> None:
    sealed = seal(KEY, NONCE, PLAINTEXT, AAD)
    with pytest.raises(AuthenticationError) as info:
        open_(bytes(32), NONCE, sealed, AAD)
    assert str(info.value) == "authentication failed"
    assert info.value.args == ("authentication failed",)
    # No chained InvalidTag whose frames would reference the key.
    assert info.value.__cause__ is None
    assert info.value.__suppress_context__


# --- KDF --------------------------------------------------------------------


def test_derive_kek_returns_mutable_32_bytes() -> None:
    kek = derive_kek(b"synthetic", bytes(16), **FAST)
    assert isinstance(kek, bytearray)
    assert len(kek) == params.KEY_LEN
    assert any(kek)


def test_derive_kek_is_deterministic_and_salted() -> None:
    a = derive_kek(b"synthetic", bytes(16), **FAST)
    b = derive_kek(b"synthetic", bytes(16), **FAST)
    c = derive_kek(b"synthetic", bytes([1]) * 16, **FAST)
    d = derive_kek(b"synthetic2", bytes(16), **FAST)
    assert a == b
    assert a is not b
    assert a != c
    assert a != d


def test_derive_kek_depends_on_every_cost_parameter() -> None:
    base = derive_kek(b"synthetic", bytes(16), m_cost=64, t_cost=1, parallelism=1)
    assert base != derive_kek(b"synthetic", bytes(16), m_cost=128, t_cost=1, parallelism=1)
    assert base != derive_kek(b"synthetic", bytes(16), m_cost=64, t_cost=2, parallelism=1)
    assert base != derive_kek(b"synthetic", bytes(16), m_cost=64, t_cost=1, parallelism=2)


def test_derived_kek_works_as_aead_key_and_can_be_erased() -> None:
    kek = derive_kek(b"synthetic", bytes(16), **FAST)
    sealed = seal(kek, NONCE, PLAINTEXT, AAD)
    assert open_(kek, NONCE, sealed, AAD) == PLAINTEXT
    zeroize(kek)
    assert kek == bytearray(32)
    with pytest.raises(AuthenticationError):
        open_(kek, NONCE, sealed, AAD)


@pytest.mark.parametrize(
    ("salt_len", "m_cost", "t_cost", "parallelism"),
    [
        (15, 65536, 3, 4),
        (17, 65536, 3, 4),
        (0, 65536, 3, 4),
        (16, params.M_COST_MAX_KIB + 1, 3, 4),
        (16, 2**32 - 1, 3, 4),
        (16, 31, 3, 4),  # below 8 KiB per lane
        (16, 0, 1, 1),
        (16, 65536, 0, 4),
        (16, 65536, params.T_COST_MAX + 1, 4),
        (16, 65536, 2**32 - 1, 4),
        (16, 65536, 3, 0),
        (16, 65536, 3, params.PARALLELISM_MAX + 1),
        (16, 65536, 3, 255),
        (16, -1, 3, 4),
    ],
)
def test_out_of_range_params_never_reach_argon2(
    monkeypatch: pytest.MonkeyPatch, salt_len: int, m_cost: int, t_cost: int, parallelism: int
) -> None:
    """Rule 6 and property P7: limits are checked before any Argon2id work."""

    def must_not_run(*args: object, **kwargs: object) -> None:
        raise AssertionError("Argon2id was constructed with out-of-range parameters")

    monkeypatch.setattr(kdf_module, "Argon2id", must_not_run)
    with pytest.raises(KdfParameterError):
        derive_kek(b"synthetic", bytes(salt_len), m_cost, t_cost, parallelism)


@pytest.mark.parametrize(
    ("m_cost", "t_cost", "parallelism"),
    [
        (8, 1, 1),
        (128, 16, 16),
        (params.M_COST_MAX_KIB, 1, 1),
        (CONFIG_A.m_cost, CONFIG_A.t_cost, CONFIG_A.parallelism),
        (params.CONFIG_B.m_cost, params.CONFIG_B.t_cost, params.CONFIG_B.parallelism),
        (params.CONFIG_C.m_cost, params.CONFIG_C.t_cost, params.CONFIG_C.parallelism),
    ],
)
def test_boundary_params_are_accepted(m_cost: int, t_cost: int, parallelism: int) -> None:
    validate_kdf_params(params.SALT_LEN, m_cost, t_cost, parallelism)


def test_kdf_error_message_has_no_values() -> None:
    with pytest.raises(KdfParameterError) as info:
        derive_kek(b"synthetic-master-password", bytes(16), 65536, 99, 4)
    assert str(info.value) == "t_cost out of range"


# --- Randomness and erasure -------------------------------------------------


@pytest.mark.parametrize("n", [1, 12, 16, 32])
def test_random_bytes_length(n: int) -> None:
    out = random_bytes(n)
    assert isinstance(out, bytes)
    assert len(out) == n


def test_random_bytes_do_not_repeat() -> None:
    assert len({random_bytes(12) for _ in range(10_000)}) == 10_000


@pytest.mark.parametrize("n", [0, -1])
def test_random_bytes_rejects_non_positive(n: int) -> None:
    with pytest.raises(ValueError, match="positive"):
        random_bytes(n)


def test_zeroize_overwrites_in_place() -> None:
    buf = bytearray(b"\xff" * 32)
    view = memoryview(buf)
    zeroize(buf)
    assert buf == bytearray(32)
    assert bytes(view) == bytes(32)  # same underlying buffer, not a rebinding


def test_zeroize_empty_buffer() -> None:
    buf = bytearray()
    zeroize(buf)
    assert buf == bytearray()
