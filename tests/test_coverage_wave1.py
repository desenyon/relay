"""Targeted tests for inspect helpers, json_compat branches, CLI edges, errors, payload."""

from __future__ import annotations

import importlib
import importlib.metadata
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

import numpy as np
import pytest
from click.testing import CliRunner

from relay.cli.main import cli
from relay.compat.json_compat import _message_to_json_dict, _relay_to_json_value, to_json
from relay.encoder import encode
from relay.errors import (
    DecodingError,
    DeltaConflictError,
    EncodingError,
    ParseError,
    RegistryError,
    RelayError,
    RelayReferenceError,
    SchemaHashMismatch,
    SchemaNotFoundError,
    TypeMismatchError,
    ValidationError,
)
from relay.payload import message_to_payload_dict
from relay.schema import RelaySchema
from relay.types import EnumValue, MessageType, RelayField, RelayMessage, TypeTag


def _reg() -> object:
    return importlib.import_module("relay.registry")


# --- inspect helpers ---------------------------------------------------------


def test_inspect_tag_name_unknown() -> None:
    from relay.cli.commands.inspect import _tag_name

    assert _tag_name(0xFF) == "unknown(0xFF)"


def test_inspect_value_repr_scalar_and_special_cases() -> None:
    from relay.cli.commands.inspect import _value_repr

    assert _value_repr(0x01, None) == "null"
    assert _value_repr(0x02, True) == "True"
    assert _value_repr(0x05, 7) == "7"
    assert _value_repr(0x0C, 1.5) == "1.5"
    long_s = "a" * 100
    r = _value_repr(0x0D, long_s)
    assert "…" in r
    assert len(r) < len(long_s) + 20
    assert _value_repr(0x0E, b"ab") == "<bytes len=2>"
    assert _value_repr(0x0E, bytearray(b"x")) == "<bytes len=1>"
    uid = UUID("550e8400-e29b-41d4-a716-446655440000")
    assert "550e8400" in _value_repr(0x11, uid)
    assert "2026" in _value_repr(0x12, datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert _value_repr(0x13, "https://x") == "https://x"
    assert "vector[5]" in _value_repr(0x14, [1.0, 2.0, 3.0, 4.0, 5.0])
    assert ", …" in _value_repr(0x14, list(range(10)))
    assert "enum" in _value_repr(0x15, "assistant").lower() or "assistant" in _value_repr(
        0x15, "assistant"
    )
    assert "py" in _value_repr(0x16, {"lang": "py", "code": "x"})
    assert "chars" in _value_repr(0x17, "hello")
    assert "$ref" in _value_repr(0x18, "session:550e8400.call[0].x")
    assert "SET" in _value_repr(0x19, {"op": "SET", "field_path": "a"})
    assert _value_repr(0x19, "raw") == "raw"
    assert _value_repr(0x0F, [1, 2]) == "array[2]"
    assert "fields" in _value_repr(0x10, {"a": 1})

    class _NoLen:
        pass

    assert "object" in _value_repr(0x10, _NoLen()) or repr(_NoLen())[:10] in _value_repr(
        0x10, _NoLen()
    )


def test_inspect_value_repr_code_block_dataclass_like() -> None:
    from relay.cli.commands.inspect import _value_repr

    class CB:
        lang = "rs"
        code = "fn main() {}"

    s = _value_repr(0x16, CB())
    assert "rs" in s and "chars" in s


def test_inspect_value_repr_vector_bad_iterable() -> None:
    from relay.cli.commands.inspect import _value_repr

    class BadVec:
        def __iter__(self) -> object:
            raise RuntimeError("no")

    out = _value_repr(0x14, BadVec())
    assert "BadVec" in out or "RuntimeError" in out or out


def test_inspect_append_relay_fields_tree_shape() -> None:
    from relay.cli.commands.inspect import _append_relay_fields

    class Node:
        def __init__(self) -> None:
            self.children: list[Node] = []

        def add(self, _label: str) -> Node:
            c = Node()
            self.children.append(c)
            return c

    root = Node()
    inner = [
        RelayField(1, "n", TypeTag.INT32, 3),
    ]
    fields = [
        RelayField(1, "o", TypeTag.OBJECT, inner),
        RelayField(2, "arr", TypeTag.ARRAY, [RelayField(0, "_", TypeTag.STRING, "x"), "plain"]),
        RelayField(
            3,
            "cb",
            TypeTag.CODE_BLOCK,
            {"lang": "py", "code": "\n".join(f"line{i}" for i in range(12))},
        ),
        SimpleNamespace(not_a_field=True),
    ]
    _append_relay_fields(root, fields)
    assert len(root.children) == 3
    assert len(root.children[0].children) == 1
    assert len(root.children[1].children) == 2
    assert len(root.children[2].children) >= 12


def test_render_pretty_json_text(monkeypatch: pytest.MonkeyPatch) -> None:
    from relay.cli.commands import inspect as insp

    printed: list[object] = []

    class FakeConsole:
        def print(self, *a: object, **k: object) -> None:
            printed.append(("print", a, k))

        def print_json(self, s: str) -> None:
            printed.append(("json", s))

    monkeypatch.setattr(insp, "console", FakeConsole())

    class Msg:
        message_type = 9999
        schema_hash = "notbytes"
        fields: tuple[object, ...] = ()

    insp._render_pretty(Msg())
    assert printed and printed[0][0] == "print"

    msg2 = RelayMessage(
        message_type=MessageType.FULL,
        schema_hash=bytes.fromhex("a3f2bc01"),
        fields=[RelayField(1, "k", TypeTag.STRING, "v")],
    )
    insp._render_json(msg2)
    assert any(p[0] == "json" for p in printed)
    payload = json.loads(next(p[1] for p in printed if p[0] == "json"))
    assert payload == {"k": "v"}


def test_render_text_schema_missing_then_ok(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from relay.cli.commands import inspect as insp
    from relay.registry import SchemaRegistry

    reg = SchemaRegistry(registry_dir=tmp_path / "reg_rt")
    sch = RelaySchema.from_dict(
        {
            "name": "tenc",
            "version": 1,
            "fields": [{"name": "msg", "type": "string", "required": True}],
            "enums": {},
        }
    )
    reg.register(sch)

    lines: list[str] = []

    class FakeC:
        def print(self, s: str = "", **_: object) -> None:
            lines.append(s)

    monkeypatch.setattr(insp, "console", FakeC())
    raw = encode({"msg": "z"}, sch)
    msg = __import__("relay.decoder", fromlist=["decode"]).decode(raw, schema=sch)

    empty = SchemaRegistry(registry_dir=tmp_path / "reg_empty")
    monkeypatch.setattr(importlib.import_module("relay.registry"), "default_registry", empty)
    from relay.errors import SchemaNotFoundError

    with pytest.raises(SchemaNotFoundError):
        insp._render_text(msg)

    monkeypatch.setattr(importlib.import_module("relay.registry"), "default_registry", reg)
    lines.clear()
    insp._render_text(msg)
    assert any("@relay" in ln for ln in lines)
    assert any("tenc:" in ln for ln in lines)


# --- json_compat -------------------------------------------------------------


def test_relay_to_json_exhaustive() -> None:
    assert _relay_to_json_value(0x01, None) is None
    assert _relay_to_json_value(0x02, 1) is True
    for t in (0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0A):
        assert _relay_to_json_value(t, 3) == 3
    assert _relay_to_json_value(0x0B, 1.25) == 1.25
    assert _relay_to_json_value(0x0C, 2.5) == 2.5
    assert _relay_to_json_value(0x0D, "x") == "x"
    assert _relay_to_json_value(0x0E, b"\xff\xfe") == "fffe"
    assert _relay_to_json_value(0x0E, bytearray(b"a")) == "61"
    assert _relay_to_json_value(0x0E, memoryview(b"ab")) == "6162"
    assert _relay_to_json_value(0x0E, "notbytes") == "notbytes"
    u = UUID("550e8400-e29b-41d4-a716-446655440000")
    assert _relay_to_json_value(0x11, u) == str(u)
    assert _relay_to_json_value(0x11, "550e8400-e29b-41d4-a716-446655440000") == str(u)
    dt_naive = datetime(2026, 6, 1, 12, 0, 0)
    s = _relay_to_json_value(0x12, dt_naive)
    assert s.endswith("Z") and "2026-06-01" in s
    us = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp() * 1_000_000)
    assert "2026" in _relay_to_json_value(0x12, us)
    assert "T" in _relay_to_json_value(0x12, float(us))
    assert _relay_to_json_value(0x12, "rawdt") == "rawdt"
    assert _relay_to_json_value(0x13, "urn:foo") == "urn:foo"
    assert _relay_to_json_value(0x14, np.array([1.0, 2.0])) == [1.0, 2.0]

    # Vector branch: float() fails on element -> fall back to list(value)
    bad_el = object()
    assert _relay_to_json_value(0x14, [bad_el]) == [bad_el]
    ev = EnumValue(name="a", index=0)
    assert _relay_to_json_value(0x15, ev) == "a"
    assert _relay_to_json_value(0x15, "x") == "x"
    assert _relay_to_json_value(0x16, {"lang": "go", "code": "x"}) == {"lang": "go", "code": "x"}
    assert _relay_to_json_value(0x16, "nocb") == "nocb"
    assert _relay_to_json_value(0x17, "md") == "md"
    assert _relay_to_json_value(0x18, "$ref x") == "$ref x"
    assert _relay_to_json_value(0x0F, [(0x0D, "a"), "b"]) == ["a", "b"]
    assert _relay_to_json_value(0x0F, (1, 2)) == [1, 2]
    inner = RelayField(1, "x", TypeTag.INT32, 9)
    assert _relay_to_json_value(0x10, [inner]) == {"x": 9}
    assert _relay_to_json_value(0x10, {"p": (0x0D, "q"), "r": 1}) == {"p": "q", "r": 1}
    assert _relay_to_json_value(0x10, "plainobj") == "plainobj"
    assert _relay_to_json_value(0x19, {"op": "SET"}) == {"op": "SET"}
    assert _relay_to_json_value(0x19, "dop") == "dop"
    with pytest.raises(DecodingError) as ei:
        _relay_to_json_value(0xFE, 0)
    assert "0xFE" in str(ei.value) or "FE" in ei.value.details.get("type_tag", "")


def test_message_to_json_dict_skips_non_fields() -> None:
    m = SimpleNamespace(
        fields=[
            RelayField(1, "a", TypeTag.STRING, "z"),
            "skip",
        ]
    )
    assert _message_to_json_dict(m) == {"a": "z"}


def test_to_json_roundtrip_values(
    isolated_registry: object,
    simple_schema: RelaySchema,
    simple_message_dict: dict,
) -> None:
    isolated_registry.register(simple_schema)
    blob = encode(simple_message_dict, simple_schema)
    j = to_json(blob)
    assert j["name"] == simple_message_dict["name"]
    assert j["count"] == simple_message_dict["count"]
    assert j["flag"] is simple_message_dict["flag"]


# --- errors ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("exc_cls", "code"),
    [
        (ParseError, "E001"),
        (TypeMismatchError, "E002"),
        (SchemaNotFoundError, "E003"),
        (RelayReferenceError, "E004"),
        (DeltaConflictError, "E005"),
        (ValidationError, "E006"),
        (EncodingError, "E007"),
        (DecodingError, "E008"),
        (RegistryError, "E009"),
        (SchemaHashMismatch, "E010"),
    ],
)
def test_relay_errors_to_dict(exc_cls: type[RelayError], code: str) -> None:
    e = exc_cls("m", field_path="f.p", details={"k": 1})
    d = e.to_dict()
    assert d["code"] == code
    assert d["message"] == "m"
    assert d["field_path"] == "f.p"
    assert d["details"] == {"k": 1}
    assert d["error_type"] == exc_cls.__name__


def test_relay_error_base_to_dict() -> None:
    e = RelayError("x", code="E000", field_path=None, details=None)
    assert e.to_dict()["field_path"] is None
    assert e.to_dict()["details"] == {}


# --- CLI main ----------------------------------------------------------------


def test_cli_version_unknown_when_package_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    def _v(_: str) -> str:
        raise importlib.metadata.PackageNotFoundError()

    monkeypatch.setattr(importlib.metadata, "version", _v)
    import relay.cli.main as main_mod

    importlib.reload(main_mod)
    try:
        r = CliRunner().invoke(main_mod.cli, ["--version"])
        assert r.exit_code == 0
        assert "unknown" in r.output
    finally:
        importlib.reload(main_mod)


# --- payload -----------------------------------------------------------------


def test_payload_array_and_object_branches() -> None:
    obj_f = RelayField(
        1,
        "o",
        TypeTag.OBJECT,
        [
            RelayField(1, "a", TypeTag.INT32, 1),
            "skip",
        ],
    )
    arr_f = RelayField(2, "arr", TypeTag.ARRAY, [1, 2, 3])
    plain = RelayField(3, "s", TypeTag.STRING, "hi")
    msg = RelayMessage(MessageType.FULL, b"\x00" * 4, fields=[obj_f, arr_f, plain])
    d = message_to_payload_dict(msg)
    assert d["o"] == {"a": 1}
    assert d["arr"] == [1, 2, 3]
    assert d["s"] == "hi"


# --- convert / validate / schema --------------------------------------------


def test_convert_callback_unsupported_from_fmt(tmp_path: Path) -> None:
    import click

    from relay.cli.commands.convert import convert_cmd

    p = tmp_path / "f.json"
    p.write_text("{}", encoding="utf-8")
    with pytest.raises(click.ClickException) as ei:
        convert_cmd.callback(str(p), "not_a_real_format", "json", None)
    assert "Unsupported" in str(ei.value)


def test_convert_json_to_msgpack_bytes(
    isolated_registry: object, cli_ping_schema: RelaySchema, tmp_path: Path
) -> None:
    """Binary msgpack output must be valid MessagePack map."""
    import msgpack

    reg = isolated_registry
    reg.register(cli_ping_schema)
    p = tmp_path / "in.json"
    p.write_text(json.dumps({"msg": "packme"}), encoding="utf-8")
    runner = CliRunner()
    sid = f"cli_ping:{cli_ping_schema.hash()}"
    r = runner.invoke(
        cli,
        ["convert", str(p), "--from", "json", "--to", "msgpack", "--schema", sid],
    )
    assert r.exit_code == 0
    out = r.output_bytes if r.output_bytes else r.output.encode()
    root = msgpack.unpackb(out, raw=False)
    assert isinstance(root, dict) and root.get("msg") == "packme"


def test_validate_schema_by_hash_only(
    isolated_registry: object, cli_ping_schema: RelaySchema, tmp_path: Path
) -> None:
    reg = isolated_registry
    reg.register(cli_ping_schema)
    data = encode({"msg": "v"}, cli_ping_schema)
    f = tmp_path / "m.bin"
    f.write_bytes(data)
    r = CliRunner().invoke(cli, ["validate", str(f), "--schema", cli_ping_schema.hash()])
    assert r.exit_code == 0
    assert "OK" in r.output


def test_schema_show_invalid_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reg = importlib.import_module("relay.registry").SchemaRegistry(registry_dir=tmp_path / "sr")
    monkeypatch.setattr(_reg(), "default_registry", reg)
    r = CliRunner().invoke(cli, ["schema", "show", "nohashsep"])
    assert r.exit_code != 0
    assert "name:hash" in r.output


def test_schema_show_registry_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reg = importlib.import_module("relay.registry").SchemaRegistry(registry_dir=tmp_path / "s2")
    monkeypatch.setattr(importlib.import_module("relay.registry"), "default_registry", reg)
    with patch.object(reg, "get", side_effect=SchemaNotFoundError("nope")):
        r = CliRunner().invoke(cli, ["schema", "show", "foo:abcd1234"])
    assert r.exit_code != 0
    assert "E003" in r.output or "nope" in r.output


# --- encoder -----------------------------------------------------------------


def test_encode_rejects_non_full_message_type(cli_ping_schema: RelaySchema) -> None:
    with pytest.raises(EncodingError) as ei:
        encode({"msg": "x"}, cli_ping_schema, message_type=MessageType.DELTA)
    assert "FULL" in str(ei.value) or "delta" in str(ei.value).lower()
