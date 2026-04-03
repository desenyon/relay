"""Exercise ``RelayMessage.to_dict`` / ``_field_to_dict`` and broad text encode paths."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import numpy as np
import pytest

from relay.encoder import encode
from relay.schema import RelaySchema
from relay.text_decoder import decode_text
from relay.text_encoder import RelayTextEncoder, encode_text
from relay.types import (
    CodeBlock,
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


def test_relay_message_to_dict_all_semantic_branches() -> None:
    uid = UUID("550e8400-e29b-41d4-a716-446655440000")
    sid = UUID("661f9511-f3ac-52e5-b827-557766551111")
    vec = VectorValue(VectorDtype.FLOAT32, 2, np.array([1.0, 2.0], dtype=np.float32))
    arr_inner = RelayField(1, "item", TypeTag.STRING, "x")
    obj_inner = RelayField(1, "inner", TypeTag.INT32, 7)
    us = int(datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc).timestamp() * 1_000_000)
    fields = [
        RelayField(1, "obj", TypeTag.OBJECT, [obj_inner]),
        RelayField(2, "arr", TypeTag.ARRAY, [arr_inner, "raw"]),
        RelayField(3, "vec", TypeTag.VECTOR, vec),
        RelayField(4, "uid", TypeTag.UUID, uid),
        RelayField(5, "dt", TypeTag.DATETIME, us),
        RelayField(6, "en", TypeTag.ENUM, EnumValue(name="a", index=0)),
        RelayField(7, "cb", TypeTag.CODE_BLOCK, CodeBlock(lang="py", code="1")),
        RelayField(8, "md", TypeTag.MARKDOWN_BLOCK, MarkdownBlock(content="hi")),
        RelayField(9, "rf", TypeTag.REF, RelayRef(sid, 2, "out.x")),
        RelayField(10, "plain", TypeTag.STRING, "s"),
    ]
    msg = RelayMessage(MessageType.FULL, b"\xab\xcd\xef\x01", fields=fields)
    d = msg.to_dict()
    assert d["message_type"] == "FULL"
    assert d["schema_hash"] == "abcdef01"
    fd = {f["name"]: f for f in d["fields"]}
    assert fd["vec"]["value"]["dtype"] == "FLOAT32"
    assert fd["uid"]["value"] == str(uid)
    assert fd["en"]["value"] == {"name": "a", "index": 0}
    assert fd["cb"]["value"] == {"lang": "py", "code": "1"}
    assert fd["md"]["value"] == {"content": "hi"}
    assert fd["rf"]["value"]["session_id"] == str(sid)
    assert fd["arr"]["value"][1] == "raw"


@pytest.fixture
def mega_text_schema() -> RelaySchema:
    return RelaySchema.from_dict(
        {
            "name": "mega_text",
            "version": 1,
            "fields": [
                {"name": "nul", "type": "null", "required": False},
                {"name": "b", "type": "bool", "required": True},
                {"name": "i8", "type": "int8", "required": True},
                {"name": "u8", "type": "uint8", "required": True},
                {"name": "f32", "type": "float32", "required": True},
                {"name": "f64", "type": "float64", "required": True},
                {"name": "st", "type": "string", "required": True},
                {"name": "u", "type": "uuid", "required": True},
                {"name": "uri", "type": "uri", "required": True},
                {"name": "role", "type": "enum<Role>", "required": True},
                {"name": "role_i", "type": "enum<Role>", "required": True},
                {"name": "vec", "type": "vector<float32, 2>", "required": True},
                {"name": "md", "type": "markdown_block", "required": True},
                {"name": "rf", "type": "ref", "required": True},
                {
                    "name": "nest",
                    "type": "object",
                    "required": True,
                    "fields": [{"name": "x", "type": "int32", "required": True}],
                },
                {"name": "nums", "type": "array<int32>", "required": True},
            ],
            "enums": {"Role": ["one", "two"]},
        }
    )


def test_text_encode_decode_mega_schema(
    mega_text_schema: RelaySchema, isolated_registry: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    import importlib

    isolated_registry.register(mega_text_schema)
    monkeypatch.setattr(
        importlib.import_module("relay.registry"), "default_registry", isolated_registry
    )
    uid = UUID("550e8400-e29b-41d4-a716-446655440000")
    payload = {
        "nul": None,
        "b": False,
        "i8": -8,
        "u8": 200,
        "f32": 1.5,
        "f64": 2.5,
        "st": 'quote "inner"',
        "u": uid,
        "uri": "https://ex.test/p",
        "role": "two",
        "role_i": 0,
        "vec": [0.25, 0.75],
        "md": MarkdownBlock(content="# T"),
        "rf": RelayRef(uid, 4, "a.b"),
        "nest": {"x": -3},
        "nums": [1, 2, 3],
    }
    text = encode_text(payload, mega_text_schema)
    assert "@type FULL" in text
    msg = decode_text(text, registry=isolated_registry)
    assert msg.get_field("st").value == payload["st"]
    assert msg.get_field("nums").value == [1, 2, 3]
    inner = msg.get_field("nest").value
    assert isinstance(inner, list) and inner[0].name == "x" and inner[0].value == -3


def test_text_encoder_delta_ops_variants(mega_text_schema: RelaySchema) -> None:
    from relay.types import DeltaOp, DeltaOpType

    enc = RelayTextEncoder(mega_text_schema)
    ref = RelayRef(UUID("550e8400-e29b-41d4-a716-446655440000"), 0, "")
    ops = [
        DeltaOp(DeltaOpType.DEL, "st"),
        DeltaOp(DeltaOpType.SET, "f64", TypeTag.FLOAT64, 9.0),
        DeltaOp(DeltaOpType.APP, "nums", TypeTag.INT32, 99),
        DeltaOp(
            DeltaOpType.SPL,
            "nums",
            TypeTag.INT32,
            5,
            splice_start=0,
            splice_end=1,
        ),
    ]
    t = enc.encode_delta_text(ops, ref)
    assert "@type DELTA" in t
    assert "DEL " in t
    assert "SET " in t
    assert "APP " in t
    assert "SPL " in t


def test_bytes_text_encode_line() -> None:
    sch = RelaySchema.from_dict(
        {
            "name": "bonly",
            "version": 1,
            "fields": [{"name": "raw", "type": "bytes", "required": True}],
            "enums": {},
        }
    )
    t = encode_text({"raw": b"\xab\xcd"}, sch)
    assert "bytes" in t and "abcd" in t.replace("0x", "").lower()


def test_type_name_to_tag_branches() -> None:
    from relay.errors import EncodingError
    from relay.text_encoder import _type_name_to_tag
    from relay.types import TypeTag

    assert _type_name_to_tag("enum<X>") == TypeTag.ENUM
    assert _type_name_to_tag("vector<float64, 1>") == TypeTag.VECTOR
    assert _type_name_to_tag("code_block<python>") == TypeTag.CODE_BLOCK
    with pytest.raises(EncodingError):
        _type_name_to_tag("not_a_real_type_xyz")


def test_text_encoder_required_missing_raises(mega_text_schema: RelaySchema) -> None:
    from relay.errors import EncodingError

    enc = RelayTextEncoder(mega_text_schema)
    with pytest.raises(EncodingError) as ei:
        enc.encode_text({})
    assert "Required" in str(ei.value) or "missing" in str(ei.value).lower()


def test_text_encoder_type_mismatches(mega_text_schema: RelaySchema) -> None:
    from relay.errors import TypeMismatchError

    enc = RelayTextEncoder(mega_text_schema)
    base = {
        "b": True,
        "i8": 1,
        "u8": 1,
        "f32": 1.0,
        "f64": 1.0,
        "st": "a",
        "u": UUID("550e8400-e29b-41d4-a716-446655440000"),
        "uri": "https://a",
        "role": "one",
        "role_i": 0,
        "vec": [1.0, 2.0],
        "md": MarkdownBlock(content="m"),
        "rf": RelayRef(UUID("550e8400-e29b-41d4-a716-446655440000"), 0, "x"),
        "nest": {"x": 1},
        "nums": [1],
    }
    for key, bad in [
        ("b", "no"),
        ("i8", True),
        ("f32", "x"),
        ("st", 1),
        ("u", 1),
        ("uri", 1),
        ("role", object()),
        ("vec", "n"),
        ("md", 1),
        ("rf", object()),
        ("nest", "bad"),
        ("nums", {}),
    ]:
        bad_payload = {**base, key: bad}
        with pytest.raises(TypeMismatchError):
            enc.encode_text(bad_payload)


def test_inspect_with_hash_only_schema_override(
    isolated_registry: object,
    cli_ping_schema: RelaySchema,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib

    from click.testing import CliRunner

    from relay.cli.main import cli

    isolated_registry.register(cli_ping_schema)
    monkeypatch.setattr(
        importlib.import_module("relay.registry"), "default_registry", isolated_registry
    )
    raw = encode({"msg": "hashonly"}, cli_ping_schema)
    f = tmp_path / "h.bin"
    f.write_bytes(raw)
    r = CliRunner().invoke(cli, ["inspect", str(f), "--schema", cli_ping_schema.hash()])
    assert r.exit_code == 0
