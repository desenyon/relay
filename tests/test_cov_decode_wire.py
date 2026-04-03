"""Exhaustive decoder / wire-frame tests for full line coverage."""

from __future__ import annotations

import struct
from io import BytesIO
from uuid import UUID

import pytest

from relay.decoder import RelayStreamDecoder, decode, decode_stream
from relay.encoder import encode
from relay.errors import (
    DecodingError,
    ParseError,
    SchemaHashMismatch,
    SchemaNotFoundError,
    TypeMismatchError,
)
from relay.schema import RelaySchema
from relay.types import MAGIC, VERSION, MessageType, TypeTag


def _fh(msg_type: int, sh: bytes, payload: bytes) -> bytes:
    h = bytearray(12)
    h[0] = MAGIC
    h[1] = VERSION
    struct.pack_into("<H", h, 2, msg_type)
    h[4:8] = sh[:4]
    struct.pack_into("<I", h, 8, len(payload))
    return bytes(h) + payload


def _ff(fid: int, tag: int, body: bytes) -> bytes:
    b = bytearray(7)
    struct.pack_into("<H", b, 0, fid)
    b[2] = tag & 0xFF
    struct.pack_into("<I", b, 3, len(body))
    return bytes(b) + body


@pytest.fixture
def ping() -> RelaySchema:
    return RelaySchema.from_dict(
        {
            "name": "ping",
            "version": 1,
            "fields": [{"name": "msg", "type": "string", "required": True}],
            "enums": {},
        }
    )


def test_decode_header_too_short() -> None:
    with pytest.raises(ParseError):
        decode(b"")


def test_decode_bad_magic() -> None:
    with pytest.raises(ParseError) as e:
        decode(bytes([0, VERSION]) + b"\x00" * 10)
    assert "magic" in str(e.value).lower()


def test_decode_bad_version() -> None:
    with pytest.raises(ParseError) as e:
        decode(bytes([MAGIC, 99]) + b"\x00" * 10)
    assert "version" in str(e.value).lower()


def test_decode_truncated_payload(ping: RelaySchema, isolated_registry: object) -> None:
    isolated_registry.register(ping)
    raw = encode({"msg": "hi"}, ping)
    cut = raw[:12]
    with pytest.raises(ParseError) as e:
        decode(cut, registry=isolated_registry)
    assert "Truncated" in str(e.value) or "payload" in str(e.value).lower()


def test_decode_trailing_bytes(ping: RelaySchema, isolated_registry: object) -> None:
    isolated_registry.register(ping)
    raw = encode({"msg": "x"}, ping) + b"EXTRA"
    with pytest.raises(ParseError) as e:
        decode(raw, registry=isolated_registry)
    assert "Trailing" in str(e.value)


def test_decode_zero_hash_no_override(isolated_registry: object) -> None:
    with pytest.raises(SchemaNotFoundError):
        decode(_fh(MessageType.FULL, b"\x00\x00\x00\x00", b""), registry=isolated_registry)


def test_decode_override_hash_mismatch(ping: RelaySchema, isolated_registry: object) -> None:
    isolated_registry.register(ping)
    other = b"\xff\xee\xdd\xcc"
    payload = _ff(1, int(TypeTag.STRING), b"x")
    frame = _fh(MessageType.FULL, other, payload)
    with pytest.raises(SchemaHashMismatch):
        decode(frame, schema=ping, registry=isolated_registry)


def test_decode_registry_miss(isolated_registry: object) -> None:
    raw = _fh(MessageType.FULL, b"\xab\xcd\xef\x01", b"")
    with pytest.raises(SchemaNotFoundError):
        decode(raw, registry=isolated_registry)


def test_decode_schema_def_paths(isolated_registry: object) -> None:
    p = _ff(2, int(TypeTag.STRING), b"nope") + _ff(1, int(TypeTag.STRING), b"ok")
    frame = _fh(MessageType.SCHEMA_DEF, b"\x00\x00\x00\x00", p)
    with pytest.raises(TypeMismatchError):
        decode(frame, registry=isolated_registry)

    p2 = _ff(1, int(TypeTag.STRING), b"a") + _ff(1, int(TypeTag.STRING), b"b")
    frame2 = _fh(MessageType.SCHEMA_DEF, b"\x00\x00\x00\x00", p2)
    with pytest.raises(ParseError):
        decode(frame2, registry=isolated_registry)


def test_decode_ref_only_bad(ping: RelaySchema, isolated_registry: object) -> None:
    isolated_registry.register(ping)
    uid = UUID("550e8400-e29b-41d4-a716-446655440000")
    refb = uid.bytes + struct.pack("<I", 0) + b"path\x00"
    two = _ff(1, int(TypeTag.REF), refb) + _ff(2, int(TypeTag.REF), refb)
    frame = _fh(MessageType.REF_ONLY, ping.hash_bytes()[:4], two)
    with pytest.raises(TypeMismatchError):
        decode(frame, registry=isolated_registry)


def test_decode_delta_unknown_field(ping: RelaySchema, isolated_registry: object) -> None:
    isolated_registry.register(ping)
    uid = UUID("550e8400-e29b-41d4-a716-446655440000")
    refb = uid.bytes + struct.pack("<I", 0) + b"\x00"
    bad = _ff(0, int(TypeTag.REF), refb) + _ff(99, int(TypeTag.STRING), b"x")
    frame = _fh(MessageType.DELTA, ping.hash_bytes()[:4], bad)
    with pytest.raises(TypeMismatchError):
        decode(frame, registry=isolated_registry)


def test_decode_full_duplicate_field(ping: RelaySchema, isolated_registry: object) -> None:
    isolated_registry.register(ping)
    one = _ff(1, int(TypeTag.STRING), b"aa")
    dup = one + one
    frame = _fh(MessageType.FULL, ping.hash_bytes()[:4], dup)
    with pytest.raises(ParseError):
        decode(frame, registry=isolated_registry)


def test_decode_full_unknown_field(ping: RelaySchema, isolated_registry: object) -> None:
    isolated_registry.register(ping)
    bad = _ff(9, int(TypeTag.STRING), b"x")
    frame = _fh(MessageType.FULL, ping.hash_bytes()[:4], bad)
    with pytest.raises(TypeMismatchError):
        decode(frame, registry=isolated_registry)


def test_decode_full_tag_mismatch(ping: RelaySchema, isolated_registry: object) -> None:
    isolated_registry.register(ping)
    wrong = _ff(1, int(TypeTag.INT32), struct.pack("<i", 1))
    frame = _fh(MessageType.FULL, ping.hash_bytes()[:4], wrong)
    with pytest.raises(TypeMismatchError):
        decode(frame, registry=isolated_registry)


def _reg_one(
    isolated_registry: object,
    name: str,
    fname: str,
    ftype: str,
    enums: dict | None = None,
) -> tuple[RelaySchema, int, bytes]:
    sch = RelaySchema.from_dict(
        {
            "name": name,
            "version": 1,
            "fields": [{"name": fname, "type": ftype, "required": True}],
            "enums": enums or {},
        }
    )
    isolated_registry.register(sch)
    from relay.schema_compile import compile_schema

    cf = compile_schema(sch).field_by_name(fname)
    assert cf is not None
    return sch, cf.field_id, sch.hash_bytes()[:4]


def test_decode_enum_out_of_range(isolated_registry: object) -> None:
    _sch, fid, sh = _reg_one(isolated_registry, "e1", "e", "enum<Role>", {"Role": ["a"]})
    bad = _ff(fid, int(TypeTag.ENUM), struct.pack("<I", 99))
    with pytest.raises(TypeMismatchError):
        decode(_fh(MessageType.FULL, sh, bad), registry=isolated_registry)


def test_decode_vector_errors(isolated_registry: object) -> None:
    _sch, fid, sh = _reg_one(isolated_registry, "v1", "v", "vector<float32, 2>")
    bad = _ff(fid, int(TypeTag.VECTOR), struct.pack("<II", 2, 2) + b"\x00")
    with pytest.raises((ParseError, TypeMismatchError)):
        decode(_fh(MessageType.FULL, sh, bad), registry=isolated_registry)


def test_decode_markdown_too_short(isolated_registry: object) -> None:
    _sch, fid, sh = _reg_one(isolated_registry, "m1", "m", "markdown_block")
    bad = _ff(fid, int(TypeTag.MARKDOWN_BLOCK), b"\x01\x02\x03")
    with pytest.raises(ParseError):
        decode(_fh(MessageType.FULL, sh, bad), registry=isolated_registry)


def test_decode_unsupported_value_tag(isolated_registry: object) -> None:
    sch = RelaySchema.from_dict(
        {
            "name": "s",
            "version": 1,
            "fields": [{"name": "x", "type": "string", "required": True}],
            "enums": {},
        }
    )
    isolated_registry.register(sch)
    bad = _ff(1, 0xFE, b"")
    frame = _fh(MessageType.FULL, sch.hash_bytes()[:4], bad)
    with pytest.raises((DecodingError, ValueError, TypeMismatchError)):
        decode(frame, registry=isolated_registry)


def test_decode_stream_flush_yield(
    monkeypatch: pytest.MonkeyPatch, ping: RelaySchema, isolated_registry: object
) -> None:
    isolated_registry.register(ping)
    full = encode({"msg": "flush"}, ping)

    def feed_no_extract(self: RelayStreamDecoder, data: bytes) -> list:
        self._buf.extend(data)
        return []

    monkeypatch.setattr(RelayStreamDecoder, "feed", feed_no_extract)
    stream = BytesIO(full)
    msgs = list(
        decode_stream(stream, schema=ping, registry=isolated_registry, chunk_size=len(full))
    )
    assert len(msgs) == 1
    assert msgs[0].get_field("msg").value == "flush"


def test_stream_decoder_flush_incomplete_raises() -> None:
    dec = RelayStreamDecoder()
    dec._buf.extend(b"\xde\x01")
    with pytest.raises(ParseError):
        dec.flush()


def test_decode_error_message_type(isolated_registry: object) -> None:
    payload = (
        _ff(1, int(TypeTag.UINT16), struct.pack("<H", 1))
        + _ff(2, int(TypeTag.STRING), b"e")
        + _ff(3, int(TypeTag.STRING), b"m")
    )
    frame = _fh(MessageType.ERROR, b"\x00\x00\x00\x00", payload)
    m = decode(frame, registry=isolated_registry)
    assert m.message_type == MessageType.ERROR


def test_registry_get_re_raises(
    isolated_registry: object, ping: RelaySchema, monkeypatch: pytest.MonkeyPatch
) -> None:
    reg = isolated_registry
    reg.register(ping)

    def boom(_h: str) -> RelaySchema:
        raise SchemaNotFoundError("x")

    monkeypatch.setattr(reg, "get_by_hash", boom)
    raw = encode({"msg": "z"}, ping)
    with pytest.raises(SchemaNotFoundError):
        decode(raw, registry=reg)
