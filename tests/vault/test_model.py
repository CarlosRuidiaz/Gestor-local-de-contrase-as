"""Content model: canonical JSON, strict parsing, padding and secret-free representations."""

from __future__ import annotations

import json

import pytest

from pvlt.vault import GeneratorSettings, Settings, TamperedContentError, ValidationError
from pvlt.vault.model import (
    Content,
    Entry,
    pad,
    parse_content,
    serialize_content,
    unpad,
)

ID_1 = "11111111-1111-4111-8111-111111111111"
ID_2 = "22222222-2222-4222-9222-222222222222"
STAMP = "2026-11-16T12:00:00Z"


def entry(entry_id: str = ID_1, **changes: str) -> Entry:
    fields = {
        "id": entry_id,
        "site": "sitio-sintetico.example",
        "username": "usuario.sintetico",
        "password": "CLAVE-SINTETICA-zxqj",
        "notes": "nota sintética con ñ",
        "created": STAMP,
        "modified": STAMP,
    }
    return Entry(**(fields | changes))


# --- Canonical JSON ---------------------------------------------------------


def test_empty_content_has_the_documented_shape() -> None:
    assert json.loads(serialize_content(Content())) == {
        "schema": 1,
        "entries": [],
        "settings": {
            "autolock_seconds": 300,
            "generator": {
                "length": 20,
                "lower": True,
                "upper": True,
                "digits": True,
                "symbols": True,
            },
        },
    }


def test_serialization_is_canonical() -> None:
    data = serialize_content(Content(entries=(entry(),)))
    assert b" " not in data.replace(b"nota sint\xc3\xa9tica con \xc3\xb1", b"")
    assert b"\n" not in data
    assert "ñ".encode() in data  # ensure_ascii=False
    assert data.index(b'"entries"') < data.index(b'"schema"') < data.index(b'"settings"')


def test_round_trip() -> None:
    content = Content(
        entries=(entry(ID_1), entry(ID_2, site="otro.example", notes="")),
        settings=Settings(
            autolock_seconds=60,
            generator=GeneratorSettings(
                length=32, lower=True, upper=False, digits=True, symbols=False
            ),
        ),
    )
    assert parse_content(serialize_content(content)) == content


def reject(data: bytes) -> None:
    with pytest.raises(TamperedContentError) as info:
        parse_content(data)
    assert info.value.reason == "schema"
    assert str(info.value) == "Contenido manipulado"


def mutated(change: object) -> bytes:
    obj = json.loads(serialize_content(Content(entries=(entry(),))))
    change(obj)  # type: ignore[operator]
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"null",
        b"[]",
        b"{}",
        b"not json",
        b"\xff\xfe",
        b'{"schema":1,"entries":[],"settings":{}}',
    ],
)
def test_parse_rejects_things_that_are_not_a_content(data: bytes) -> None:
    reject(data)


@pytest.mark.parametrize(
    "change",
    [
        lambda o: o.update(schema=2),
        lambda o: o.update(schema="1"),
        lambda o: o.update(schema=True),
        lambda o: o.update(extra=1),
        lambda o: o.pop("settings"),
        lambda o: o.update(entries={}),
        lambda o: o["entries"][0].update(extra="x"),
        lambda o: o["entries"][0].pop("notes"),
        lambda o: o["entries"][0].update(id="not-a-uuid"),
        lambda o: o["entries"][0].update(id="AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"),
        lambda o: o["entries"][0].update(site=""),
        lambda o: o["entries"][0].update(site=5),
        lambda o: o["entries"][0].update(password=None),
        lambda o: o["entries"][0].update(password="x" * 1025),
        lambda o: o["entries"][0].update(notes="x" * 8193),
        lambda o: o["entries"][0].update(created="2026-11-16 12:00:00"),
        lambda o: o["entries"][0].update(modified="2026-13-40T99:00:00Z"),
        lambda o: o["entries"].append(dict(o["entries"][0])),  # duplicated id
        lambda o: o["settings"].update(autolock_seconds=0),
        lambda o: o["settings"].update(autolock_seconds=300.0),
        lambda o: o["settings"]["generator"].update(length=4),
        lambda o: o["settings"]["generator"].update(lower=1),
        lambda o: o["settings"]["generator"].update(
            lower=False, upper=False, digits=False, symbols=False
        ),
    ],
)
def test_parse_rejects_schema_violations(change: object) -> None:
    reject(mutated(change))


def test_parse_rejects_more_than_500_entries() -> None:
    def too_many(o: dict[str, list[dict[str, str]]]) -> None:
        base = o["entries"][0]
        o["entries"] = [base | {"id": f"{i:08d}-0000-4000-8000-000000000000"} for i in range(501)]

    reject(mutated(too_many))


def test_parse_rejects_non_canonical_encodings() -> None:
    canonical = serialize_content(Content(entries=(entry(),)))
    obj = json.loads(canonical)
    reject(json.dumps(obj, sort_keys=True).encode())  # with spaces
    reject(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode())  # \u escapes
    unsorted = dict(reversed(list(obj.items())))
    reject(json.dumps(unsorted, separators=(",", ":"), ensure_ascii=False).encode())
    reject(canonical + b"\n")
    reject(canonical.replace(b'"schema":1', b'"schema":1,"schema":1'))  # duplicate key


# --- Field validation on input ----------------------------------------------


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("site", ""),
        ("site", "x" * 257),
        ("site", "nul\x00inside"),
        ("username", "x" * 257),
        ("password", ""),
        ("password", "x" * 1025),
        ("password", "\ud800"),  # lone surrogate, not encodable
        ("notes", "x" * 8193),
        ("id", "123"),
        ("created", "ayer"),
    ],
)
def test_entry_rejects_invalid_fields(field: str, value: str) -> None:
    with pytest.raises(ValidationError) as info:
        entry(**{field: value})
    assert info.value.field == field
    assert str(info.value) == "Dato inválido"
    assert value not in str(info.value) or value == ""


def test_limits_are_inclusive() -> None:
    entry(site="x" * 256, username="", password="x" * 1024, notes="x" * 8192)


@pytest.mark.parametrize("seconds", [29, 3601, -1])
def test_settings_reject_autolock_out_of_range(seconds: int) -> None:
    with pytest.raises(ValidationError):
        Settings(autolock_seconds=seconds)


@pytest.mark.parametrize("length", [7, 129])
def test_generator_settings_reject_length_out_of_range(length: int) -> None:
    with pytest.raises(ValidationError):
        GeneratorSettings(length=length)


# --- No secrets in representations ------------------------------------------


def test_repr_never_shows_secrets() -> None:
    e = entry()
    content = Content(entries=(e,))
    for text in (repr(e), str(e), repr(content), f"{e}", repr([e]), repr({"k": content})):
        assert "CLAVE-SINTETICA" not in text
        assert "usuario.sintetico" not in text
        assert "sitio-sintetico" not in text
        assert "nota" not in text
    assert repr(e) == f"Entry(id='{ID_1}')"


# --- Padding ----------------------------------------------------------------


@pytest.mark.parametrize("length", [0, 1, 100, 4094, 4095, 4096, 4097, 8191, 8192, 20000])
def test_pad_round_trip(length: int) -> None:
    data = bytes([0x41]) * length
    padded = pad(data)
    assert len(padded) % 4096 == 0
    assert len(padded) - len(data) <= 4096  # minimal k
    assert len(padded) > len(data)
    assert padded[len(data)] == 0x80
    assert not any(padded[len(data) + 1 :])
    assert unpad(padded) == data


def test_pad_hides_small_size_differences() -> None:
    assert len(pad(b"x" * 10)) == len(pad(b"x" * 3000)) == 4096
    assert len(pad(b"x" * 4095)) == 4096
    assert len(pad(b"x" * 4096)) == 8192


def test_pad_keeps_data_that_ends_like_padding() -> None:
    for data in (b"\x80", b"abc\x80\x00\x00", b"\x00" * 10, b"\x80" * 4096):
        assert unpad(pad(data)) == data


@pytest.mark.parametrize(
    "padded",
    [
        b"",
        bytes(4096),  # no marker at all
        b"\x80" + bytes(4094),  # not a multiple of the block
        b"abc" + bytes(4093),  # zeros but no marker
        b"abc\x80" + bytes(4091) + b"\x01",  # garbage after the marker
        b"abc\x80" + bytes(4092 + 4096),  # a whole extra block of padding
        b"abc\x81" + bytes(4092),  # wrong marker
    ],
)
def test_unpad_is_strict(padded: bytes) -> None:
    with pytest.raises(TamperedContentError) as info:
        unpad(padded)
    assert info.value.reason == "padding"
