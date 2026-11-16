"""T10: published test vectors of RFC 8439 (ChaCha20-Poly1305) and RFC 9106 (Argon2id)."""

from __future__ import annotations

from cryptography.hazmat.primitives.kdf.argon2 import Argon2id

from pvlt.crypto import derive_kek, open_, seal
from pvlt.params import CONFIG_A

# RFC 8439, section 2.8.2.
RFC8439_KEY = bytes(range(0x80, 0xA0))
RFC8439_NONCE = bytes.fromhex("070000004041424344454647")
RFC8439_AAD = bytes.fromhex("50515253c0c1c2c3c4c5c6c7")
RFC8439_PLAINTEXT = (
    b"Ladies and Gentlemen of the class of '99: If I could offer you "
    b"only one tip for the future, sunscreen would be it."
)
RFC8439_CIPHERTEXT = bytes.fromhex(
    "d31a8d34648e60db7b86afbc53ef7ec2"
    "a4aded51296e08fea9e2b5a736ee62d6"
    "3dbea45e8ca9671282fafb69da92728b"
    "1a71de0a9e060b2905d6a5b67ecd3b36"
    "92ddbd7f2d778b8c9803aee328091b58"
    "fab324e4fad675945585808b4831d7bc"
    "3ff4def08e4b7a9de576d26586cec64b"
    "6116"
)
RFC8439_TAG = bytes.fromhex("1ae10b594f09e26a7e902ecbd0600691")

# RFC 9106, section 5.3 (Argon2id, version 0x13).
RFC9106_PASSWORD = bytes([0x01]) * 32
RFC9106_SALT = bytes([0x02]) * 16
RFC9106_SECRET = bytes([0x03]) * 8
RFC9106_AD = bytes([0x04]) * 12
RFC9106_TAG = bytes.fromhex("0d640df58d78766c08c037a34a8b53c9d01ef0452d75b65eb52520e96b01e659")


def test_rfc8439_seal() -> None:
    out = seal(RFC8439_KEY, RFC8439_NONCE, RFC8439_PLAINTEXT, RFC8439_AAD)
    assert out == RFC8439_CIPHERTEXT + RFC8439_TAG


def test_rfc8439_open() -> None:
    out = open_(RFC8439_KEY, RFC8439_NONCE, RFC8439_CIPHERTEXT + RFC8439_TAG, RFC8439_AAD)
    assert out == RFC8439_PLAINTEXT


def test_rfc9106_argon2id_primitive() -> None:
    """The library implements Argon2id v1.3 exactly as the RFC specifies.

    The vector uses 32 KiB, a secret and associated data, which `derive_kek`
    does not expose, so the primitive is exercised directly.
    """
    kdf = Argon2id(
        salt=RFC9106_SALT,
        length=32,
        iterations=3,
        lanes=4,
        memory_cost=32,
        ad=RFC9106_AD,
        secret=RFC9106_SECRET,
    )
    assert kdf.derive(RFC9106_PASSWORD) == RFC9106_TAG


def test_derive_kek_matches_primitive() -> None:
    """`derive_kek` is that same primitive with our parameters and nothing else added."""
    password, salt = b"synthetic-master-password", bytes(range(16))
    reference = Argon2id(
        salt=salt,
        length=32,
        iterations=CONFIG_A.t_cost,
        lanes=CONFIG_A.parallelism,
        memory_cost=CONFIG_A.m_cost,
    ).derive(password)
    kek = derive_kek(password, salt, CONFIG_A.m_cost, CONFIG_A.t_cost, CONFIG_A.parallelism)
    assert bytes(kek) == reference
