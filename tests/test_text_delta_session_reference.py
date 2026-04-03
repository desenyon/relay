"""Text encode/decode, delta, session, and reference resolution coverage."""

from __future__ import annotations

import importlib
from uuid import UUID, uuid4

import pytest

from relay.decoder import decode
from relay.delta import apply_delta, delta
from relay.encoder import encode
from relay.errors import (
    EncodingError,
    ParseError,
    RelayReferenceError,
    SchemaNotFoundError,
    TypeMismatchError,
)
from relay.reference import resolve_path
from relay.registry import SchemaRegistry
from relay.session import Session
from relay.text_decoder import decode_text
from relay.text_encoder import RelayTextEncoder, encode_text
from relay.types import (
    DeltaOp,
    DeltaOpType,
    MarkdownBlock,
    MessageType,
    RelayRef,
    TypeTag,
)


def _reg_mod():
    return importlib.import_module("relay.registry")


@pytest.fixture
def reg(tmp_path) -> SchemaRegistry:
    d = tmp_path / "reg"
    d.mkdir()
    return SchemaRegistry(registry_dir=d)


def test_encode_text_unknown_type_raises() -> None:
    from relay.schema import RelaySchema

    sch = RelaySchema.from_dict(
        {
            "name": "badt",
            "version": 1,
            "fields": [{"name": "x", "type": "weird_type_xyz", "required": True}],
            "enums": {},
        }
    )
    enc = RelayTextEncoder(sch)
    with pytest.raises(EncodingError):
        enc.encode_text({"x": 1})


def test_full_text_roundtrip_simple(reg: SchemaRegistry, monkeypatch: pytest.MonkeyPatch) -> None:
    from relay.schema import RelaySchema

    sch = RelaySchema.from_dict(
        {
            "name": "t1",
            "version": 1,
            "fields": [
                {"name": "msg", "type": "string", "required": True},
                {"name": "n", "type": "int32", "required": True},
            ],
            "enums": {},
        }
    )
    reg.register(sch)
    monkeypatch.setattr(_reg_mod(), "default_registry", reg)
    obj = {"msg": "hello", "n": -7}
    text = encode_text(obj, sch)
    msg = decode_text(text, registry=reg)
    assert msg.message_type == MessageType.FULL
    assert msg.get_field("msg").value == "hello"
    assert msg.get_field("n").value == -7


def test_full_text_roundtrip_tool_call(
    reg: SchemaRegistry,
    tool_call_schema: object,
    tool_call_message_dict: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reg.register(tool_call_schema)
    monkeypatch.setattr(_reg_mod(), "default_registry", reg)
    text = encode_text(tool_call_message_dict, tool_call_schema)
    msg = decode_text(text, registry=reg)
    assert msg.message_type == MessageType.FULL
    assert msg.get_field("role").value == tool_call_message_dict["role"]


def test_decode_text_errors(reg: SchemaRegistry, monkeypatch: pytest.MonkeyPatch) -> None:
    from relay.schema import RelaySchema

    sch = RelaySchema.from_dict(
        {
            "name": "e1",
            "version": 1,
            "fields": [{"name": "a", "type": "string", "required": True}],
            "enums": {},
        }
    )
    reg.register(sch)
    monkeypatch.setattr(_reg_mod(), "default_registry", reg)
    with pytest.raises(ParseError):
        decode_text("", registry=reg)
    with pytest.raises(ParseError):
        decode_text("no header\n", registry=reg)
    bad = (
        f"@relay 1.0\n@schema {sch.name}:ffffffff\n@type FULL\n\n"
        "a: string \"x\"\n"
    )
    with pytest.raises(SchemaNotFoundError):
        decode_text(bad, registry=reg)


def test_delta_text_roundtrip(reg: SchemaRegistry, monkeypatch: pytest.MonkeyPatch) -> None:
    from relay.schema import RelaySchema

    sch = RelaySchema.from_dict(
        {
            "name": "d1",
            "version": 1,
            "fields": [{"name": "rate", "type": "float64", "required": True}],
            "enums": {},
        }
    )
    reg.register(sch)
    monkeypatch.setattr(_reg_mod(), "default_registry", reg)
    sid = UUID("550e8400-e29b-41d4-a716-446655440000")
    ref = RelayRef(sid, 0, "")
    ops = [DeltaOp(DeltaOpType.SET, "rate", TypeTag.FLOAT64, 0.25)]
    enc = RelayTextEncoder(sch)
    text = enc.encode_delta_text(ops, ref)
    msg = decode_text(text, registry=reg)
    assert msg.message_type == MessageType.DELTA


def test_delta_apply_and_encode(
    tool_call_schema: object,
    tool_call_message_dict: dict,
) -> None:
    data = encode(tool_call_message_dict, tool_call_schema)
    base = decode(data, schema=tool_call_schema, validate=True)
    base.delta_base_ref = RelayRef(uuid4(), 0, "")
    op = DeltaOp(
        DeltaOpType.SET,
        "content",
        TypeTag.MARKDOWN_BLOCK,
        MarkdownBlock(content="patched"),
    )
    dbytes = delta(base, [op], schema=tool_call_schema)
    dmsg = decode(dbytes, schema=tool_call_schema, validate=False)
    merged = apply_delta(base, dmsg, schema=tool_call_schema)
    assert merged.message_type == MessageType.FULL
    assert merged.get_field("content").value.content == "patched"


def test_session_record_resolve(
    tool_call_schema: object,
    tool_call_message_dict: dict,
) -> None:
    sid = UUID("550e8400-e29b-41d4-a716-446655440000")
    sess = Session(session_id=sid)
    msg = decode(encode(tool_call_message_dict, tool_call_schema), schema=tool_call_schema)
    idx = sess.record(msg)
    assert idx == 0
    ref = RelayRef(sid, 0, "tool_call.name")
    assert sess.resolve_ref(ref) == "calculate_npv"


def test_session_errors(tool_call_schema: object, tool_call_message_dict: dict) -> None:
    sess = Session()
    msg = decode(encode(tool_call_message_dict, tool_call_schema), schema=tool_call_schema)
    sess.record(msg)
    bad_sid = RelayRef(uuid4(), 0, "")
    with pytest.raises(RelayReferenceError):
        sess.resolve_ref(bad_sid)
    with pytest.raises(RelayReferenceError):
        sess.resolve_ref(RelayRef(sess.session_id, 99, "x"))


def test_resolve_path_empty_and_nested(tool_call_schema: object, tool_call_message_dict: dict) -> None:
    msg = decode(encode(tool_call_message_dict, tool_call_schema), schema=tool_call_schema)
    d = resolve_path(msg, "")
    assert "role" in d
    assert resolve_path(msg, "tool_call.name") == "calculate_npv"


def test_resolve_path_errors(tool_call_schema: object, tool_call_message_dict: dict) -> None:
    msg = decode(encode(tool_call_message_dict, tool_call_schema), schema=tool_call_schema)
    with pytest.raises(RelayReferenceError):
        resolve_path(msg, "nope.field")
    with pytest.raises(RelayReferenceError):
        resolve_path(msg, "tool_call.arguments.cash_flows[99]")


def test_compat_json_openai_roundtrip(
    openai_tool_call_dict: dict,
    reg: SchemaRegistry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from relay.compat import (
        from_openai_tool_call,
        openai_tool_call_schema,
        to_json,
        to_openai_tool_call,
    )

    sch = openai_tool_call_schema()
    reg.register(sch)
    monkeypatch.setattr(_reg_mod(), "default_registry", reg)
    b = from_openai_tool_call(openai_tool_call_dict)
    roundtrip = to_openai_tool_call(b)
    assert roundtrip["id"] == openai_tool_call_dict["id"]
    assert roundtrip["function"]["name"] == openai_tool_call_dict["function"]["name"]
    j = to_json(b)
    assert isinstance(j, dict)
    assert j["id"] == openai_tool_call_dict["id"]


def test_compat_json_anthropic_roundtrip(
    anthropic_tool_use_dict: dict,
    reg: SchemaRegistry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from relay.compat import (
        anthropic_tool_use_schema,
        from_anthropic_tool_use,
        to_anthropic_tool_use,
        to_json,
    )

    sch = anthropic_tool_use_schema()
    reg.register(sch)
    monkeypatch.setattr(_reg_mod(), "default_registry", reg)
    b = from_anthropic_tool_use(anthropic_tool_use_dict)
    assert to_anthropic_tool_use(b)["name"] == anthropic_tool_use_dict["name"]
    decode(b, schema=sch, validate=True)
    tj = to_json(b)
    assert tj["name"] == anthropic_tool_use_dict["name"]


def test_compat_openai_errors() -> None:
    from relay.compat import from_openai_tool_call

    with pytest.raises(TypeMismatchError):
        from_openai_tool_call([])  # type: ignore[arg-type]
    with pytest.raises(TypeMismatchError):
        from_openai_tool_call(
            {
                "id": "x",
                "type": "function",
                "function": {"name": "f", "arguments": 1},
            }
        )


def test_compat_anthropic_errors() -> None:
    from relay.compat import from_anthropic_tool_use

    with pytest.raises(TypeMismatchError):
        from_anthropic_tool_use("x")  # type: ignore[arg-type]
    with pytest.raises(TypeMismatchError):
        from_anthropic_tool_use({"id": "i", "name": "n", "input": []})  # type: ignore[dict-item]


def test_from_json_to_json(reg: SchemaRegistry, monkeypatch: pytest.MonkeyPatch) -> None:
    from relay.compat import from_json, to_json
    from relay.schema import RelaySchema

    sch = RelaySchema.from_dict(
        {
            "name": "fj",
            "version": 1,
            "fields": [{"name": "k", "type": "string", "required": True}],
            "enums": {},
        }
    )
    reg.register(sch)
    monkeypatch.setattr(_reg_mod(), "default_registry", reg)
    payload = {"k": "v"}
    b = from_json(payload, sch)
    assert to_json(b)["k"] == "v"


def test_registry_delete_exists(reg: SchemaRegistry) -> None:
    from relay.schema import RelaySchema

    sch = RelaySchema.from_dict(
        {"name": "z", "version": 1, "fields": [], "enums": {}},
    )
    reg.register(sch)
    hx = sch.hash()
    assert reg.exists("z", hx)
    reg.delete("z", hx)
    assert not reg.exists("z", hx)
