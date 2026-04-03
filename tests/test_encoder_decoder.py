"""Encoder/decoder round-trips and type-tag coverage."""

from __future__ import annotations

import io
from datetime import datetime, timezone
from uuid import UUID

import numpy as np
import pytest

from relay.decoder import RelayStreamDecoder, decode, decode_stream
from relay.encoder import encode
from relay.errors import ParseError, TypeMismatchError
from relay.schema import RelaySchema
from relay.types import (
    CodeBlock,
    DeltaOp,
    DeltaOpType,
    EnumValue,
    MarkdownBlock,
    MessageType,
    RelayField,
    RelayMessage,
    RelayRef,
    TypeTag,
    VectorDtype,
    VectorValue,
)


def _s(name: str, fields: list[dict], enums: dict | None = None) -> RelaySchema:
    return RelaySchema.from_dict(
        {
            "name": name,
            "version": 1,
            "fields": fields,
            "enums": enums or {},
        }
    )


def test_roundtrip_integers_and_float():
    sch = _s(
        "n",
        [
            {"name": "a", "type": "int8", "required": True},
            {"name": "b", "type": "uint32", "required": True},
            {"name": "c", "type": "float64", "required": True},
        ],
    )
    obj = {"a": -1, "b": 42, "c": 3.14}
    m = decode(encode(obj, sch), schema=sch)
    assert m.get_field("a").value == -1
    assert m.get_field("b").value == 42
    assert m.get_field("c").value == 3.14


def test_float_rejects_int():
    sch = _s("f", [{"name": "x", "type": "float64", "required": True}])
    with pytest.raises(TypeMismatchError):
        encode({"x": 1}, sch)


def test_bool_null_string_bytes():
    sch = _s(
        "mix",
        [
            {"name": "u", "type": "bool", "required": True},
            {"name": "v", "type": "null", "required": False},
            {"name": "w", "type": "string", "required": True},
            {"name": "z", "type": "bytes", "required": True},
        ],
    )
    obj = {"u": True, "v": None, "w": "hi", "z": b"\xff\x00"}
    m = decode(encode(obj, sch), schema=sch)
    assert m.get_field("u").value is True
    assert m.get_field("w").value == "hi"
    assert m.get_field("z").value == b"\xff\x00"


def test_uuid_uri_datetime_enum_vector():
    sch = _s(
        "sem",
        [
            {"name": "id", "type": "uuid", "required": True},
            {"name": "u", "type": "uri", "required": True},
            {"name": "d", "type": "datetime", "required": True},
            {"name": "r", "type": "enum<Role>", "required": True},
            {"name": "vec", "type": "vector<float32, 2>", "required": True},
        ],
        {"Role": ["a", "b"]},
    )
    uid = UUID("550e8400-e29b-41d4-a716-446655440000")
    dt = datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc)
    obj = {
        "id": uid,
        "u": "https://example.com/x",
        "d": dt,
        "r": "b",
        "vec": VectorValue(
            VectorDtype.FLOAT32, 2, np.array([1.0, 2.0], dtype=np.float32)
        ),
    }
    m = decode(encode(obj, sch), schema=sch)
    assert m.get_field("id").value == uid
    assert m.get_field("u").value.startswith("https://")
    assert isinstance(m.get_field("d").value, datetime)
    ev = m.get_field("r").value
    assert isinstance(ev, EnumValue) and ev.name == "b" and ev.index == 1
    vv = m.get_field("vec").value
    assert isinstance(vv, VectorValue) and vv.dim == 2


def test_code_markdown_ref():
    sch = _s(
        "x",
        [
            {"name": "c", "type": "code_block", "required": True},
            {"name": "m", "type": "markdown_block", "required": True},
            {"name": "r", "type": "ref", "required": True},
        ],
    )
    ref = RelayRef(uid := UUID("550e8400-e29b-41d4-a716-446655440000"), 3, "out.x")
    obj = {
        "c": CodeBlock(lang="py", code="print(1)"),
        "m": MarkdownBlock(content="# T"),
        "r": ref,
    }
    m = decode(encode(obj, sch), schema=sch)
    assert m.get_field("r").value.session_id == uid


def test_nested_object():
    sch = _s(
        "nest",
        [
            {
                "name": "o",
                "type": "object",
                "required": True,
                "fields": [
                    {"name": "n", "type": "int32", "required": True},
                ],
            }
        ],
    )
    m = decode(encode({"o": {"n": 9}}, sch), schema=sch)
    inner = m.get_field("o").value
    assert isinstance(inner, list)
    assert inner[0].name == "n" and inner[0].value == 9


def test_array_int32():
    sch = _s(
        "arr",
        [{"name": "items", "type": "array<int32>", "required": True}],
    )
    m = decode(encode({"items": [1, 2, 3]}, sch), schema=sch)
    assert m.get_field("items").value == [1, 2, 3]


def test_decode_stream_chunked():
    sch = _s("p", [{"name": "k", "type": "string", "required": True}])
    data = encode({"k": "z"}, sch)
    buf = io.BytesIO()
    for b in data:
        buf.write(bytes([b]))
    buf.seek(0)
    msgs = list(decode_stream(buf, schema=sch, chunk_size=3))
    assert len(msgs) == 1
    assert msgs[0].get_field("k").value == "z"


def test_stream_decoder_one_byte():
    sch = _s("p", [{"name": "k", "type": "string", "required": True}])
    data = encode({"k": "ab"}, sch)
    dec = RelayStreamDecoder(schema=sch)
    out: list = []
    for b in data:
        out.extend(dec.feed(bytes([b])))
    assert len(out) == 1


def test_parse_error_trailing():
    sch = _s("p", [{"name": "k", "type": "string", "required": True}])
    data = encode({"k": "x"}, sch) + b"extra"
    with pytest.raises(ParseError):
        decode(data, schema=sch)


def test_schema_def_message():
    from relay.encoder import _build_frame

    inner = _s("inner", [{"name": "k", "type": "string", "required": True}])
    rtext = "schema inner {\n version: 1\n fields:\n  k: string required\n}\n"
    payload = b""
    from relay.encoder import _pack_field_frame

    body = rtext.encode("utf-8")
    payload = _pack_field_frame(1, int(TypeTag.STRING), body)
    frame = _build_frame(MessageType.SCHEMA_DEF, inner.hash_bytes(), payload)
    m = decode(frame, schema=inner, validate=False)
    assert m.message_type == MessageType.SCHEMA_DEF


def test_error_frame():
    import struct

    from relay.encoder import _build_frame, _pack_field_frame

    payload = b""
    payload += _pack_field_frame(1, int(TypeTag.UINT16), struct.pack("<H", 1))
    payload += _pack_field_frame(2, int(TypeTag.STRING), b"ParseError")
    payload += _pack_field_frame(3, int(TypeTag.STRING), b"bad")
    frame = _build_frame(MessageType.ERROR, b"\x00\x00\x00\x00", payload)
    m = decode(frame, validate=False)
    assert m.message_type == MessageType.ERROR


def test_ref_only_single_ref():
    from relay.encoder import _build_frame, _encode_ref_bytes, _pack_field_frame

    sch = _s("r", [{"name": "p", "type": "ref", "required": True}])
    ref = RelayRef(UUID(int=0), 0, "")
    body = _encode_ref_bytes(ref)
    payload = _pack_field_frame(1, int(TypeTag.REF), body)
    frame = _build_frame(MessageType.REF_ONLY, sch.hash_bytes(), payload)
    m = decode(frame, schema=sch, validate=False)
    assert m.message_type == MessageType.REF_ONLY
