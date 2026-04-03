"""Direct tests for ``relay.text_decoder`` helpers and error paths."""

from __future__ import annotations

import pytest

from relay.errors import ParseError
from relay.registry import SchemaRegistry
from relay.schema import RelaySchema
from relay.text_decoder import decode_text
from relay.types import MessageType


@pytest.fixture
def reg(tmp_path) -> SchemaRegistry:
    d = tmp_path / "r"
    d.mkdir()
    return SchemaRegistry(registry_dir=d)


def _sch() -> RelaySchema:
    return RelaySchema.from_dict(
        {
            "name": "td",
            "version": 1,
            "fields": [
                {"name": "msg", "type": "string", "required": True},
                {
                    "name": "nest",
                    "type": "object",
                    "required": False,
                    "fields": [{"name": "k", "type": "int32", "required": True}],
                },
                {"name": "arr", "type": "array<int32>", "required": False},
                {"name": "role", "type": "enum<Role>", "required": False},
                {"name": "vec", "type": "vector<float32, 2>", "required": False},
                {"name": "md", "type": "markdown_block", "required": False},
                {"name": "cb", "type": "code_block", "required": False},
                {"name": "r", "type": "ref", "required": False},
            ],
            "enums": {"Role": ["a", "b"]},
        }
    )


def test_decode_text_preamble_errors(reg: SchemaRegistry) -> None:
    s = _sch()
    reg.register(s)
    hx = s.hash()
    with pytest.raises(ParseError):
        decode_text("", registry=reg)
    with pytest.raises(ParseError):
        decode_text("no relay\n", registry=reg)
    with pytest.raises(ParseError):
        decode_text("@relay 1.0\n", registry=reg)
    with pytest.raises(ParseError):
        decode_text("@relay 1.0\n@schema BAD\n@type FULL\n\n", registry=reg)
    with pytest.raises(ParseError):
        decode_text(f"@relay 1.0\n@schema td:{hx}\n@type BOGUS\n\n", registry=reg)
    with pytest.raises(ParseError):
        decode_text(
            f"@relay 1.0\n@schema td:{hx}\n@type {MessageType.SCHEMA_DEF.name}\n\n",
            registry=reg,
        )


def test_decode_text_delta_base_errors(reg: SchemaRegistry) -> None:
    s = _sch()
    reg.register(s)
    hx = s.hash()
    with pytest.raises(ParseError):
        decode_text(f"@relay 1.0\n@schema td:{hx}\n@type DELTA\n\n", registry=reg)
    with pytest.raises(ParseError):
        decode_text(
            f"@relay 1.0\n@schema td:{hx}\n@type DELTA\n@base\n\n",
            registry=reg,
        )


def test_decode_text_blank_line_and_unknown_field(reg: SchemaRegistry) -> None:
    import relay.text_decoder as td

    s = _sch()
    reg.register(s)
    hx = s.hash()
    bad = f'@relay 1.0\n@schema td:{hx}\n@type FULL\n\nnope: string "x"\n'
    with pytest.raises(ParseError):
        decode_text(bad, registry=reg)

    lines = ['  bad: string "x"']
    with pytest.raises(ParseError):
        td._parse_full_body(lines, s)


def test_text_delta_helpers() -> None:
    import relay.text_decoder as td

    with pytest.raises(ParseError):
        td._parse_delta_op_line("WAT x")
    with pytest.raises(ParseError):
        td._split_delta_set_app("only", "SET")
    with pytest.raises(ParseError):
        td._scalar_type_name_to_tag("notatype")
    with pytest.raises(ParseError):
        td._parse_delta_scalar("string", "x")
    with pytest.raises(ParseError):
        td._parse_spl_line("bad")
    assert td._parse_delta_scalar("null", "null") is None
    assert td._parse_delta_scalar("bool", "true") is True
    assert td._parse_delta_scalar("int32", "3") == 3
    assert td._parse_delta_scalar("float64", "1.5") == 1.5
    assert td._parse_delta_scalar("bytes", "ff") == b"\xff"
    ev = td._parse_delta_scalar("enum", '"z"')
    assert ev.name == "z"


def test_parse_field_array_and_object_errors(reg: SchemaRegistry) -> None:
    import relay.text_decoder as td

    s = RelaySchema.from_dict(
        {
            "name": "ar",
            "version": 1,
            "fields": [{"name": "items", "type": "array<int32>", "required": True}],
            "enums": {},
        }
    )
    lines = [
        "items: array<int32>",
        "  [0]: int32 1",
        "   [1]: int32 2",
    ]
    with pytest.raises(ParseError):
        td._parse_field_lines(lines, 0, s, None)

    s2 = RelaySchema.from_dict(
        {
            "name": "ob",
            "version": 1,
            "fields": [
                {
                    "name": "o",
                    "type": "object",
                    "required": True,
                    "fields": [{"name": "k", "type": "string", "required": True}],
                }
            ],
            "enums": {},
        }
    )
    lines2 = [
        "o: object",
        '  k: string "a"',
        '   z: string "x"',
    ]
    with pytest.raises(ParseError):
        td._parse_field_lines(lines2, 0, s2, None)

    lines3 = ["items: array<int32>", "  [0]: int32 1", '  [0]: string "x"']
    with pytest.raises(ParseError):
        td._parse_field_lines(lines3, 0, s, None)


def test_markdown_code_block_parse_errors() -> None:
    import relay.text_decoder as td

    with pytest.raises(ParseError):
        td._parse_markdown_block(["x"], 0)
    with pytest.raises(ParseError):
        td._parse_markdown_block(["md: markdown_block", "  noquote"], 0)
    with pytest.raises(ParseError):
        td._parse_markdown_block(['  """', "  x"], 0)

    with pytest.raises(ParseError):
        td._parse_code_block(["x"], 0, "code_block<py>")
    with pytest.raises(ParseError):
        td._parse_code_block(["cb: code_block<py>", "  nofence"], 0, "code_block<py>")


def test_inline_parse_errors() -> None:
    import relay.text_decoder as td

    with pytest.raises(ParseError):
        td._parse_inline_value([], 0, "enum<R>", "bad")
    with pytest.raises(ParseError):
        td._parse_inline_value([], 0, "vector<float32, 2>", "vector<float32, 2> nobracket")
    with pytest.raises(ParseError):
        td._parse_inline_value([], 0, "string", "string notquoted")
    with pytest.raises(ParseError):
        td._parse_inline_value([], 0, "weird_t", "x")
    with pytest.raises(ParseError):
        td._read_quoted_string("noq", 0)
    with pytest.raises(ParseError):
        td._read_quoted_string('"abc', 0)
    with pytest.raises(ParseError):
        td._parse_ref_token("bad")


def test_fix_enum_indices_nested(reg: SchemaRegistry) -> None:
    import relay.text_decoder as td

    s = _sch()
    reg.register(s)
    obj = {
        "role": __import__("relay.types", fromlist=["EnumValue"]).EnumValue(name="b", index=0),
        "nest": {
            "k": 1,
        },
    }
    td._fix_enum_indices(obj, s)
    assert obj["role"].index == 1


def test_parse_field_bad_line() -> None:
    import relay.text_decoder as td

    s = _sch()
    with pytest.raises(ParseError):
        td._parse_field_lines(["not a field"], 0, s, None)


def test_array_bad_element_line(reg: SchemaRegistry) -> None:
    import relay.text_decoder as td

    s = RelaySchema.from_dict(
        {
            "name": "a2",
            "version": 1,
            "fields": [{"name": "items", "type": "array<int32>", "required": True}],
            "enums": {},
        }
    )
    lines = ["items: array<int32>", "  notindex: int32 1"]
    with pytest.raises(ParseError):
        td._parse_field_lines(lines, 0, s, None)
