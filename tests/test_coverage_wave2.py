"""Stream decoder, CLI failure paths, compat edge cases, delta conflicts."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from click.testing import CliRunner

from relay.cli.main import cli
from relay.decoder import RelayStreamDecoder, decode, decode_stream
from relay.delta import apply_delta, delta
from relay.encoder import encode
from relay.errors import (
    DeltaConflictError,
    EncodingError,
    ParseError,
    TypeMismatchError,
    ValidationError,
)
from relay.schema import RelaySchema
from relay.types import (
    DeltaOp,
    DeltaOpType,
    MessageType,
    RelayField,
    RelayMessage,
    RelayRef,
    TypeTag,
)


def _reg_mod():
    return importlib.import_module("relay.registry")


def test_stream_decoder_flush_incomplete(
    isolated_registry: object, cli_ping_schema: RelaySchema
) -> None:
    isolated_registry.register(cli_ping_schema)
    dec = RelayStreamDecoder(schema=cli_ping_schema, registry=isolated_registry)
    dec.feed(bytes([0xDE, 0xAD]))  # not a full frame
    with pytest.raises(ParseError) as ei:
        dec.flush()
    assert "Incomplete" in str(ei.value)


def test_stream_decoder_feed_and_flush_full(
    isolated_registry: object, cli_ping_schema: RelaySchema
) -> None:
    isolated_registry.register(cli_ping_schema)
    raw = encode({"msg": "stream"}, cli_ping_schema)
    dec = RelayStreamDecoder(schema=cli_ping_schema, registry=isolated_registry)
    assert dec.feed(raw[:5]) == []
    rest = dec.feed(raw[5:])
    assert len(rest) == 1
    assert rest[0].get_field("msg").value == "stream"
    assert dec.flush() == []


def test_decode_stream_one_byte_chunks(
    isolated_registry: object, cli_ping_schema: RelaySchema
) -> None:
    isolated_registry.register(cli_ping_schema)
    raw = encode({"msg": "chunked"}, cli_ping_schema)

    class OneByte:
        def __init__(self, data: bytes) -> None:
            self._d = data
            self._i = 0

        def read(self, _n: int = 1) -> bytes:
            if self._i >= len(self._d):
                return b""
            b = self._d[self._i : self._i + 1]
            self._i += 1
            return b

    msgs = list(decode_stream(OneByte(raw), schema=cli_ping_schema, registry=isolated_registry))
    assert len(msgs) == 1
    assert msgs[0].get_field("msg").value == "chunked"


def test_inspect_decode_relay_error(
    isolated_registry: object, cli_ping_schema: RelaySchema, tmp_path: Path
) -> None:
    isolated_registry.register(cli_ping_schema)
    f = tmp_path / "bad.bin"
    f.write_bytes(b"\xde")  # truncated frame -> ParseError (RelayError)
    r = CliRunner().invoke(cli, ["inspect", str(f)])
    assert r.exit_code != 0
    assert "Relay decode error" in r.output or "E001" in r.output


def test_inspect_decode_generic_error(
    isolated_registry: object,
    cli_ping_schema: RelaySchema,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    isolated_registry.register(cli_ping_schema)
    f = tmp_path / "x.bin"
    f.write_bytes(encode({"msg": "ok"}, cli_ping_schema))

    def boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr("relay.decoder.decode", boom)
    r = CliRunner().invoke(cli, ["inspect", str(f)])
    assert r.exit_code != 0
    assert "Unexpected error" in r.output


def test_inspect_oserror(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    f = tmp_path / "ro.bin"
    f.write_bytes(b"x")

    def boom(self: object) -> bytes:
        raise OSError("simulated read failure")

    monkeypatch.setattr(Path, "read_bytes", boom)
    r = CliRunner().invoke(cli, ["inspect", str(f)])
    assert r.exit_code != 0
    assert "Cannot read file" in r.output


def test_inspect_schema_override_bad_warning(
    isolated_registry: object, cli_ping_schema: RelaySchema, tmp_path: Path
) -> None:
    isolated_registry.register(cli_ping_schema)
    f = tmp_path / "m.bin"
    f.write_bytes(encode({"msg": "h"}, cli_ping_schema))
    r = CliRunner().invoke(cli, ["inspect", str(f), "--schema", "___notfound___:deadbeef"])
    assert r.exit_code == 0
    assert "Warning" in r.output


def test_validate_relay_error(
    isolated_registry: object, cli_ping_schema: RelaySchema, tmp_path: Path
) -> None:
    isolated_registry.register(cli_ping_schema)
    f = tmp_path / "badv.bin"
    f.write_bytes(b"\xde")  # ParseError
    r = CliRunner().invoke(cli, ["validate", str(f)])
    assert r.exit_code != 0
    assert "Invalid" in r.output


def test_convert_relay_error_exit(
    isolated_registry: object, cli_ping_schema: RelaySchema, tmp_path: Path
) -> None:
    isolated_registry.register(cli_ping_schema)
    jf = tmp_path / "bad.json"
    jf.write_text(json.dumps({"msg": 12345}), encoding="utf-8")
    sid = f"cli_ping:{cli_ping_schema.hash()}"
    r = CliRunner().invoke(
        cli,
        ["convert", str(jf), "--from", "json", "--to", "relay", "--schema", sid],
    )
    assert r.exit_code != 0
    assert "E002" in r.output or "E007" in r.output


def test_convert_load_schema_by_hash_only(
    isolated_registry: object, cli_ping_schema: RelaySchema, tmp_path: Path
) -> None:
    isolated_registry.register(cli_ping_schema)
    jf = tmp_path / "ok.json"
    jf.write_text(json.dumps({"msg": "viahash"}), encoding="utf-8")
    r = CliRunner().invoke(
        cli,
        [
            "convert",
            str(jf),
            "--from",
            "json",
            "--to",
            "json",
            "--schema",
            cli_ping_schema.hash(),
        ],
    )
    assert r.exit_code == 0
    out = json.loads(r.output)
    assert out["msg"] == "viahash"


def test_openai_tool_call_errors_and_to_openai_edges(
    isolated_registry: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    import relay.decoder as decoder_mod
    from relay.compat import from_openai_tool_call, openai_tool_call_schema, to_openai_tool_call

    sch = openai_tool_call_schema()
    isolated_registry.register(sch)
    monkeypatch.setattr(_reg_mod(), "default_registry", isolated_registry)

    with pytest.raises(TypeMismatchError):
        from_openai_tool_call(
            {"id": "a", "type": "function", "function": "notdict"},
        )
    from relay.errors import ParseError

    with pytest.raises(ParseError):
        from_openai_tool_call(
            {
                "id": "a",
                "type": "function",
                "function": {"name": "f", "arguments": "not-json{{{"},
            }
        )
    b = from_openai_tool_call(
        {
            "id": "a",
            "type": "function",
            "function": {"name": "f", "arguments": {"x": 1}},
        }
    )
    with patch.object(
        decoder_mod,
        "decode",
        return_value=RelayMessage(
            MessageType.FULL,
            sch.hash_bytes(),
            fields=[
                RelayField(1, "id", TypeTag.STRING, "a"),
                RelayField(2, "type", TypeTag.STRING, "function"),
                RelayField(3, "function_name", TypeTag.STRING, "f"),
                RelayField(4, "arguments", TypeTag.STRING, 123),  # type: ignore[arg-type]
            ],
        ),
    ):
        with pytest.raises(TypeMismatchError):
            to_openai_tool_call(b)

    bad_args = encode(
        {
            "id": "z",
            "type": "function",
            "function_name": "g",
            "arguments": "{not valid json",
        },
        sch,
    )
    o = to_openai_tool_call(bad_args)
    assert o["function"]["arguments"] == "{}"


def test_anthropic_missing_fields_and_to_anthropic_json_recovery(
    isolated_registry: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    import relay.decoder as decoder_mod
    from relay.compat import (
        anthropic_tool_use_schema,
        from_anthropic_tool_use,
        to_anthropic_tool_use,
    )

    sch = anthropic_tool_use_schema()
    isolated_registry.register(sch)
    monkeypatch.setattr(_reg_mod(), "default_registry", isolated_registry)

    with pytest.raises(TypeMismatchError):
        from_anthropic_tool_use({"type": "tool_use", "name": "n", "input": {}})
    with pytest.raises(TypeMismatchError):
        from_anthropic_tool_use({"id": "i", "type": "tool_use", "input": {}})

    b = from_anthropic_tool_use(
        {"id": "i", "type": "tool_use", "name": "n", "input": {"a": 1}},
    )
    with patch.object(
        decoder_mod,
        "decode",
        return_value=RelayMessage(
            MessageType.FULL,
            bytes.fromhex(sch.hash()),
            fields=[
                RelayField(1, "type", TypeTag.STRING, "tool_use"),
                RelayField(2, "id", TypeTag.STRING, "i"),
                RelayField(3, "name", TypeTag.STRING, []),  # type: ignore[arg-type]
                RelayField(4, "input", TypeTag.STRING, "{}"),
            ],
        ),
    ):
        with pytest.raises(TypeMismatchError):
            to_anthropic_tool_use(b)

    bad_in = encode(
        {"type": "tool_use", "id": "x", "name": "y", "input": "{bad"},
        sch,
    )
    t = to_anthropic_tool_use(bad_in)
    assert t["input"] == {}


def test_delta_requires_base_ref(cli_ping_schema: RelaySchema, isolated_registry: object) -> None:
    isolated_registry.register(cli_ping_schema)
    base = decode(encode({"msg": "base"}, cli_ping_schema), schema=cli_ping_schema)
    with pytest.raises(EncodingError):
        delta(base, [DeltaOp(DeltaOpType.SET, "msg", TypeTag.STRING, "x")])


def test_delta_schema_lookup_missing(
    isolated_registry: object, cli_ping_schema: RelaySchema, tmp_path: Path
) -> None:
    from relay.errors import SchemaNotFoundError

    delta_module = importlib.import_module("relay.delta")
    isolated_registry.register(cli_ping_schema)
    base = decode(encode({"msg": "z"}, cli_ping_schema), schema=cli_ping_schema)
    base.delta_base_ref = RelayRef(uuid4(), 0, "")
    er = tmp_path / "empty_reg"
    er.mkdir(parents=True, exist_ok=True)
    empty = importlib.import_module("relay.registry").SchemaRegistry(registry_dir=er)
    with patch.object(delta_module, "get_default_registry", return_value=empty):
        with pytest.raises(SchemaNotFoundError):
            delta(base, [DeltaOp(DeltaOpType.SET, "msg", TypeTag.STRING, "q")])


def test_apply_delta_wrong_message_types(
    cli_ping_schema: RelaySchema, isolated_registry: object
) -> None:
    isolated_registry.register(cli_ping_schema)
    base = decode(encode({"msg": "m"}, cli_ping_schema), schema=cli_ping_schema)
    with pytest.raises(ValidationError):
        apply_delta(
            RelayMessage(MessageType.DELTA, base.schema_hash, fields=[]),
            RelayMessage(MessageType.DELTA, base.schema_hash, fields=[]),
            schema=cli_ping_schema,
        )

    base.delta_base_ref = RelayRef(uuid4(), 0, "")
    dframe = delta(
        base,
        [DeltaOp(DeltaOpType.SET, "msg", TypeTag.STRING, "n")],
        schema=cli_ping_schema,
    )
    dmsg = decode(dframe, schema=cli_ping_schema, validate=False)
    with pytest.raises(ValidationError):
        apply_delta(dmsg, dmsg, schema=cli_ping_schema)


def test_apply_delta_path_conflicts(cli_ping_schema: RelaySchema) -> None:
    from relay.delta import _apply_one_op

    plain = {"tool_call": {"name": "x"}}
    with pytest.raises(DeltaConflictError):
        _apply_one_op(plain, DeltaOp(DeltaOpType.SET, "tool_call.name.extra", TypeTag.STRING, "y"))

    plain2 = {"items": "notlist"}
    with pytest.raises(DeltaConflictError):
        _apply_one_op(plain2, DeltaOp(DeltaOpType.APP, "items", TypeTag.STRING, "a"))

    plain3 = {"items": [1, 2]}
    with pytest.raises(DeltaConflictError):
        _apply_one_op(
            plain3,
            DeltaOp(
                DeltaOpType.SPL,
                "items",
                TypeTag.INT32,
                9,
                splice_start=0,
                splice_end=10,
            ),
        )

    plain4 = {"items": [1, 2]}
    with pytest.raises(DeltaConflictError):
        _apply_one_op(
            plain4,
            DeltaOp(
                DeltaOpType.SPL,
                "items",
                TypeTag.INT32,
                9,
                splice_start=2,
                splice_end=1,
            ),
        )

    plain5 = {"items": [1, 2]}
    with pytest.raises(DeltaConflictError):
        _apply_one_op(
            plain5,
            DeltaOp(
                DeltaOpType.SPL,
                "missing",
                TypeTag.INT32,
                9,
                splice_start=0,
                splice_end=1,
            ),
        )

    op = DeltaOp(DeltaOpType.SPL, "items", TypeTag.INT32, None, splice_start=0, splice_end=1)
    op.splice_start = None  # type: ignore[assignment]
    with pytest.raises(DeltaConflictError):
        _apply_one_op({"items": [1, 2, 3]}, op)

    bogus = DeltaOp(DeltaOpType.SET, "a.b", TypeTag.INT32, 2)
    bogus.op_type = "NOTREAL"  # type: ignore[assignment]
    with pytest.raises(DeltaConflictError) as ei:
        _apply_one_op({"a": {"b": 1}}, bogus)
    assert "Unknown op" in str(ei.value)


def test_inspect_value_repr_unknown_tag() -> None:
    from relay.cli.commands.inspect import _value_repr

    assert "1" in _value_repr(0x99, 1) or "0x99" in _value_repr(0x99, 1)


def test_inspect_value_repr_code_block_fallback() -> None:
    from relay.cli.commands.inspect import _value_repr

    s = _value_repr(0x16, 42)
    assert s == "42" or "42" in s
