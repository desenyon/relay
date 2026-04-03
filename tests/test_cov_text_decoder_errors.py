"""decode_text and text_decoder helpers — error paths and branches."""

from __future__ import annotations

import pytest

import relay.text_decoder as td
from relay.errors import ParseError
from relay.schema import RelaySchema, SchemaField
from relay.text_decoder import decode_text
from relay.types import DeltaOpType


def _doc(
    name: str,
    h: str,
    msg_t: str,
    body: str = "",
    *,
    base: str | None = None,
) -> str:
    lines = ["@relay 1.0", f"@schema {name}:{h}", f"@type {msg_t}"]
    if base is not None:
        lines.append(base)
    return "\n".join(lines) + "\n\n" + body


def test_decode_text_empty_and_bad_preamble(isolated_registry, ping) -> None:
    isolated_registry.register(ping)
    h = ping.hash()
    with pytest.raises(ParseError, match="Empty"):
        decode_text("", registry=isolated_registry)
    with pytest.raises(ParseError, match="First line"):
        decode_text("nope", registry=isolated_registry)
    with pytest.raises(ParseError, match="Missing @schema"):
        decode_text("@relay 1.0", registry=isolated_registry)
    with pytest.raises(ParseError, match="Bad @schema"):
        decode_text("@relay 1.0\n@schema bad\n@type FULL\n\n", registry=isolated_registry)
    with pytest.raises(ParseError, match="Missing @type"):
        decode_text(f"@relay 1.0\n@schema {ping.name}:{h}\n", registry=isolated_registry)
    with pytest.raises(ParseError, match="Bad @type"):
        decode_text(
            f"@relay 1.0\n@schema {ping.name}:{h}\n@type FULL trailing\n\n",
            registry=isolated_registry,
        )
    with pytest.raises(ParseError, match="Unknown message type"):
        decode_text(_doc(ping.name, h, "BOGUS"), registry=isolated_registry)


def test_decode_text_unsupported_message_type(isolated_registry, ping) -> None:
    isolated_registry.register(ping)
    h = ping.hash()
    with pytest.raises(ParseError, match="does not support"):
        decode_text(_doc(ping.name, h, "SCHEMA_DEF"), registry=isolated_registry)


def test_decode_text_blank_line_required(isolated_registry, ping) -> None:
    isolated_registry.register(ping)
    h = ping.hash()
    bad = f'@relay 1.0\n@schema {ping.name}:{h}\n@type FULL\nx: string "y"\n'
    with pytest.raises(ParseError, match="blank line"):
        decode_text(bad, registry=isolated_registry)


def test_delta_needs_base_and_bad_base(isolated_registry, ping) -> None:
    isolated_registry.register(ping)
    h = ping.hash()
    bad = f"@relay 1.0\n@schema {ping.name}:{h}\n@type DELTA\n\n"
    with pytest.raises(ParseError, match="@base"):
        decode_text(bad, registry=isolated_registry)
    bad2 = f"@relay 1.0\n@schema {ping.name}:{h}\n@type DELTA\n@base not-a-ref-token\n\n"
    with pytest.raises(ParseError, match="bad ref"):
        decode_text(bad2, registry=isolated_registry)


def test_ref_only_body_errors(isolated_registry) -> None:
    sch = RelaySchema(
        "ronly",
        1,
        [SchemaField("r", "ref", True)],
        {},
    )
    isolated_registry.register(sch)
    h = sch.hash()
    uid = "550e8400-e29b-41d4-a716-446655440000"
    ref = f"$ref session:{uid}.call[0]"
    preamble = _doc("ronly", h, "REF_ONLY")
    with pytest.raises(ParseError, match="exactly one"):
        decode_text(preamble, registry=isolated_registry)
    with pytest.raises(ParseError, match="expects"):
        decode_text(preamble + 'r: string "x"\n', registry=isolated_registry)
    with pytest.raises(ParseError, match="Unknown field"):
        decode_text(preamble + f"x: ref {ref}\n", registry=isolated_registry)


def test_encode_ref_only_binary_bad_field(isolated_registry, ping) -> None:
    isolated_registry.register(ping)
    with pytest.raises(ParseError, match="REF_ONLY requires"):
        td._encode_ref_only_binary(
            "msg",
            td._parse_ref_token("$ref session:550e8400-e29b-41d4-a716-446655440000.call[0]"),
            ping,
        )


def test_parse_delta_ops_and_split(isolated_registry) -> None:
    with pytest.raises(ParseError, match="Unrecognised"):
        td._parse_delta_op_line("NOPE x")
    with pytest.raises(ParseError, match="Invalid SET"):
        td._split_delta_set_app("a", "SET")
    with pytest.raises(ParseError, match="Cannot find type"):
        td._split_delta_set_app("a b notatype z", "SET")
    with pytest.raises(ParseError, match="Unknown delta value type"):
        td._scalar_type_name_to_tag("nope_type")
    with pytest.raises(ParseError, match="Unsupported delta scalar"):
        td._parse_delta_scalar("nope", "1")
    v = td._parse_delta_scalar("enum<Role>", "enum<Role>.assistant")
    assert v.name == "assistant"
    b = td._parse_delta_scalar("bytes", "00ff")
    assert b == b"\x00\xff"
    with pytest.raises(ParseError, match="Invalid SPL"):
        td._parse_spl_line("bad")


def test_parse_full_top_level_indent(isolated_registry, ping) -> None:
    isolated_registry.register(ping)
    with pytest.raises(ParseError, match="column 0"):
        td._parse_full_body(['  x: string "y"'], ping)


def test_nested_unknown_field(isolated_registry) -> None:
    sch = RelaySchema(
        "nest",
        1,
        [SchemaField("o", "object", True, nested_fields=[SchemaField("k", "string", True)])],
        {},
    )
    isolated_registry.register(sch)
    body = 'o: object\n  z: string "nope"\n'
    with pytest.raises(ParseError, match="Unknown nested"):
        td._parse_full_body(body.splitlines(), sch)


def test_array_parse_errors(isolated_registry) -> None:
    sch = RelaySchema(
        "arr",
        1,
        [SchemaField("a", "array<int32>", True)],
        {},
    )
    isolated_registry.register(sch)
    with pytest.raises(ParseError, match="Inconsistent array"):
        td._parse_field_lines(
            ["a: array<int32>", "  [0]: int32 1", "   [1]: int32 2"], 0, sch, None
        )
    with pytest.raises(ParseError, match="Bad array element"):
        td._parse_field_lines(["a: array<int32>", "  bad"], 0, sch, None)
    with pytest.raises(ParseError, match="does not match"):
        td._parse_field_lines(["a: array<int32>", "  [0]: int64 1"], 0, sch, None)


def test_object_inconsistent_indent(isolated_registry) -> None:
    sch = RelaySchema(
        "obj",
        1,
        [SchemaField("o", "object", True, nested_fields=[SchemaField("a", "string", True)])],
        {},
    )
    lines = ["o: object", '  a: string "1"', '   b: string "2"']
    with pytest.raises(ParseError, match="Inconsistent nested"):
        td._parse_field_lines(lines, 0, sch, None)


def test_markdown_and_code_block_errors() -> None:
    with pytest.raises(ParseError, match="opening triple"):
        td._parse_markdown_block(["x"], 0)
    with pytest.raises(ParseError, match="Unterminated markdown"):
        td._parse_markdown_block(['  """', " hi"], 0)
    with pytest.raises(ParseError, match="opening"):
        td._parse_code_block(["x"], 0, "code_block<py>")
    with pytest.raises(ParseError, match="Unterminated code"):
        td._parse_code_block(["  ```", " hi"], 0, "code_block<py>")


def test_parse_inline_value_errors() -> None:
    with pytest.raises(ParseError, match="enum field"):
        td._parse_inline_value([], 0, "enum<Role>", "bad")
    with pytest.raises(ParseError, match="vector"):
        td._parse_inline_value([], 0, "vector<float64, 2>", "float64 no bracket")
    with pytest.raises(ParseError, match="Expected quoted"):
        td._parse_inline_value([], 0, "string", "nope")
    with pytest.raises(ParseError, match="Unsupported type"):
        td._parse_inline_value([], 0, "weird", "x")


def test_read_quoted_string_errors() -> None:
    with pytest.raises(ParseError, match="opening quote"):
        td._read_quoted_string("x", 0)
    with pytest.raises(ParseError, match="unterminated"):
        td._read_quoted_string('"abc', 0)


def test_parse_ref_token_bad() -> None:
    with pytest.raises(ParseError, match="bad ref"):
        td._parse_ref_token("nope")


def test_fix_enum_nested(isolated_registry) -> None:
    sch = RelaySchema(
        "en",
        1,
        [
            SchemaField(
                "o",
                "object",
                True,
                nested_fields=[SchemaField("e", "enum<E>", True)],
            ),
        ],
        {"E": ["p", "q"]},
    )
    from relay.types import EnumValue

    root = {"o": {"e": EnumValue(name="q", index=0)}}
    td._fix_enum_indices(root, sch)
    assert root["o"]["e"].index == 1


def test_decode_text_ref_only_success(isolated_registry) -> None:
    sch = RelaySchema(
        "ronly",
        1,
        [SchemaField("r", "ref", True)],
        {},
    )
    isolated_registry.register(sch)
    h = sch.hash()
    uid = "550e8400-e29b-41d4-a716-446655440000"
    doc = _doc("ronly", h, "REF_ONLY") + f"r: ref $ref session:{uid}.call[1].out\n"
    msg = decode_text(doc, registry=isolated_registry)
    assert msg.message_type.name == "REF_ONLY"


def test_parse_delta_op_variants() -> None:
    d = td._parse_delta_op_line("DEL  a.b")
    assert d.op_type == DeltaOpType.DEL
    s = td._parse_delta_op_line('SET  x.y string "hi"')
    assert s.op_type == DeltaOpType.SET
    a = td._parse_delta_op_line("APP  items int32 3")
    assert a.op_type == DeltaOpType.APP
    sp = td._parse_delta_op_line("SPL  items 0 1 int32 9")
    assert sp.op_type == DeltaOpType.SPL
    assert sp.splice_start == 0 and sp.splice_end == 1


def test_parse_delta_scalar_string_uuid() -> None:
    assert td._parse_delta_scalar("string", '"x"') == "x"
    assert str(td._parse_delta_scalar("uuid", '"550e8400-e29b-41d4-a716-446655440000"')) == (
        "550e8400-e29b-41d4-a716-446655440000"
    )


def test_parse_full_body_skips_blank_lines(isolated_registry, ping) -> None:
    isolated_registry.register(ping)
    body = '\n\nmsg: string "a"\n'
    d = td._parse_full_body(body.splitlines(), ping)
    assert d["msg"] == "a"


def test_array_empty_and_vector_inline(isolated_registry) -> None:
    sch = RelaySchema(
        "av",
        1,
        [
            SchemaField("a", "array<int32>", True),
            SchemaField("v", "vector<float64, 2>", True),
        ],
        {},
    )
    isolated_registry.register(sch)
    _, _, av = td._parse_field_lines(["a: array<int32>"], 0, sch, None)
    assert av == []
    _, _, vv = td._parse_field_lines(["v: vector<float64, 2> [1.0, 2.0]"], 0, sch, None)
    assert vv.dim == 2


def test_object_with_blank_inside(isolated_registry) -> None:
    sch = RelaySchema(
        "obj",
        1,
        [SchemaField("o", "object", True, nested_fields=[SchemaField("a", "string", True)])],
        {},
    )
    lines = ["o: object", "", '  a: string "z"']
    _, _, obj = td._parse_field_lines(lines, 0, sch, None)
    assert obj["a"] == "z"


def test_markdown_and_code_success() -> None:
    mlines = ['  """', "  ..line", '  """']
    ni, mb = td._parse_markdown_block(mlines, 0)
    assert mb.content == "line"
    assert ni == 3
    clines = ["  ```", "  ..x", "  ```"]
    _ni2, cb = td._parse_code_block(clines, 0, "code_block<rs>")
    assert cb.lang == "rs" and cb.code == "x"


def test_parse_inline_bytes() -> None:
    v, _ = td._parse_inline_value([], 0, "bytes", "bytes ab")
    assert v == b"\xab"


def test_fix_enum_top_level(isolated_registry) -> None:
    from relay.types import EnumValue

    sch = RelaySchema(
        "top",
        1,
        [SchemaField("e", "enum<E>", True)],
        {"E": ["u", "v"]},
    )
    isolated_registry.register(sch)
    root = {"e": EnumValue(name="v", index=0)}
    td._fix_enum_indices(root, sch)
    assert root["e"].index == 1


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
