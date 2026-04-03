"""Exercise relay.text_encoder branches for coverage."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

import numpy as np
import pytest

from relay.errors import EncodingError, TypeMismatchError
from relay.schema import RelaySchema, SchemaField
from relay.text_encoder import (
    RelayTextEncoder,
    _encode_value_inline,
    _format_float,
    _infer_type,
    _type_name_to_tag,
    encode_text,
)
from relay.types import (
    CodeBlock,
    DeltaOp,
    DeltaOpType,
    EnumValue,
    MarkdownBlock,
    RelayField,
    RelayRef,
    TypeTag,
    VectorDtype,
    VectorValue,
)


def _minimal_schema(fields: list[SchemaField]) -> RelaySchema:
    return RelaySchema("te", 1, fields, {})


def test_type_name_to_tag_variants() -> None:
    assert _type_name_to_tag("int32") == TypeTag.INT32
    assert _type_name_to_tag("enum<Role>") == TypeTag.ENUM
    assert _type_name_to_tag("vector<f,1>") == TypeTag.VECTOR
    assert _type_name_to_tag("code_block<py>") == TypeTag.CODE_BLOCK
    with pytest.raises(EncodingError):
        _type_name_to_tag("not_a_real_type")


def test_encode_text_required_missing() -> None:
    sch = _minimal_schema([SchemaField("a", "string", True)])
    enc = RelayTextEncoder(sch)
    with pytest.raises(EncodingError):
        enc.encode_text({})


def test_field_bytes_datetime_uuid_enum_vector_code_markdown() -> None:
    sch = _minimal_schema(
        [
            SchemaField("b", "bytes", True),
            SchemaField("d", "datetime", True),
            SchemaField("u", "uuid", True),
            SchemaField("e", "enum<E>", True),
            SchemaField("v", "vector<float32, 2>", True),
            SchemaField("c", "code_block<python>", True),
            SchemaField("m", "markdown_block", True),
        ]
    )
    sch.enums = {"E": ["a", "b"]}
    enc = RelayTextEncoder(sch)
    dt = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    vv = VectorValue(VectorDtype.FLOAT32, 2, np.array([1.0, 2.0], dtype=np.float32))
    out = enc.encode_text(
        {
            "b": b"\x01\xff",
            "d": dt,
            "u": UUID("550e8400-e29b-41d4-a716-446655440000"),
            "e": EnumValue("a", 0),
            "v": vv,
            "c": CodeBlock("python", "print(1)"),
            "m": MarkdownBlock("hi"),
        }
    )
    assert "01ff" in out.replace("0x", "")
    assert "datetime" in out
    assert "550e8400" in out
    assert "enum<E>" in out
    assert "vector<float32, 2>" in out
    assert "code_block<python>" in out
    assert "markdown_block" in out

    out2 = enc.encode_text(
        {
            "b": "cafe00",
            "d": 1_000_000,
            "u": "550e8400-e29b-41d4-a716-446655440000",
            "e": "b",
            "v": [3.0, 4.0],
            "c": {"lang": "json", "code": "{}"},
            "m": "plain md",
        }
    )
    assert "550e8400" in out2
    assert "3.0" in out2


def test_field_bytes_uuid_datetime_type_errors() -> None:
    for fields, bad in (
        ([SchemaField("b", "bytes", True)], {"b": 1}),
        ([SchemaField("u", "uuid", True)], {"u": 3}),
        ([SchemaField("d", "datetime", True)], {"d": object()}),
    ):
        enc = RelayTextEncoder(_minimal_schema(fields))
        with pytest.raises(TypeMismatchError):
            enc.encode_text(bad)
    enc_b = RelayTextEncoder(_minimal_schema([SchemaField("b", "bytes", True)]))
    enc_b.encode_text({"b": b"\x00"})


def test_field_enum_vector_errors() -> None:
    sch = _minimal_schema(
        [
            SchemaField("e", "enum<E>", True),
            SchemaField("v", "vector<float64, 1>", True),
        ]
    )
    sch.enums = {"E": ["x"]}
    enc = RelayTextEncoder(sch)
    with pytest.raises(TypeMismatchError):
        enc.encode_text({"e": 1.2, "v": [1.0]})
    with pytest.raises(TypeMismatchError):
        enc.encode_text({"e": "x", "v": "nope"})


def test_field_object_nested_and_relayfield_list() -> None:
    inner = SchemaField("n", "string", True)
    sch = _minimal_schema([SchemaField("o", "object", True, nested_fields=[inner])])
    enc = RelayTextEncoder(sch)
    t1 = enc.encode_text({"o": {"n": "hi"}})
    assert "object" in t1
    assert "n: string" in t1

    rf = RelayField(1, "n", TypeTag.STRING, "x")
    t2 = enc.encode_text({"o": [rf]})
    assert "n: string" in t2

    with pytest.raises(TypeMismatchError):
        enc.encode_text({"o": 3})


def test_field_array_typed_and_heterogeneous() -> None:
    sch = _minimal_schema(
        [
            SchemaField("at", "array<int32>", True),
            SchemaField("ah", "array", True),
        ]
    )
    enc = RelayTextEncoder(sch)
    t = enc.encode_text({"at": [1, 2], "ah": [True, "z"]})
    assert "array<int32>" in t
    assert "[0]" in t
    with pytest.raises(TypeMismatchError):
        enc.encode_text({"at": 1, "ah": []})
    with pytest.raises(TypeMismatchError):
        enc.encode_text({"at": [], "ah": 1})


def test_field_ref_variants() -> None:
    sch = _minimal_schema([SchemaField("r", "ref", True)])
    enc = RelayTextEncoder(sch)
    uid = UUID("550e8400-e29b-41d4-a716-446655440000")
    ref = RelayRef(uid, 2, "out.x")
    t1 = enc.encode_text({"r": ref})
    assert "$ref session:" in t1
    t2 = enc.encode_text({"r": "$ref session:550e8400-e29b-41d4-a716-446655440000.call[0]"})
    assert "$ref" in t2
    with pytest.raises(TypeMismatchError):
        enc.encode_text({"r": 9})


def test_field_unrecognised_type_raises() -> None:
    sch = _minimal_schema([SchemaField("x", "string", True)])
    enc = RelayTextEncoder(sch)
    with pytest.raises(EncodingError):
        enc._encode_field_text("x", "weird_type<z>", "v", sch.fields[0], 0)


def test_delta_op_text_all_and_unknown() -> None:
    sch = _minimal_schema([])
    enc = RelayTextEncoder(sch)
    ref_uuid = UUID("550e8400-e29b-41d4-a716-446655440000")
    base = RelayRef(ref_uuid, 1, "")
    ops = [
        DeltaOp(DeltaOpType.DEL, "a", None, None),
        DeltaOp(DeltaOpType.SET, "b", TypeTag.FLOAT64, 0.5),
        DeltaOp(DeltaOpType.APP, "c", TypeTag.STRING, "x"),
        DeltaOp(DeltaOpType.SPL, "d", TypeTag.INT32, 7, splice_start=0, splice_end=1),
    ]
    text = enc.encode_delta_text(ops, base)
    assert "DEL" in text
    assert "SET" in text
    assert "APP" in text
    assert "SPL" in text

    bad = SimpleNamespace(
        op_type="NOPE",
        field_path="p",
        type_tag=TypeTag.STRING,
        value="v",
        splice_start=None,
        splice_end=None,
    )
    with pytest.raises(EncodingError):
        enc._encode_delta_op_text(bad)  # type: ignore[arg-type]


def test_format_float_scientific_unchanged() -> None:
    s = _format_float(1e25)
    assert "e" in s.lower() or "." in s


def test_infer_type_all_primitives() -> None:
    uid = UUID("550e8400-e29b-41d4-a716-446655440000")
    dt = datetime(2026, 1, 1, tzinfo=timezone.utc)
    vv = VectorValue(VectorDtype.FLOAT64, 1, np.array([1.0], dtype=np.float64))
    assert _infer_type(None) == "null"
    assert _infer_type(True) == "bool"
    assert _infer_type(3) == "int64"
    assert _infer_type(1.5) == "float64"
    assert _infer_type("s") == "string"
    assert _infer_type(b"x") == "bytes"
    assert _infer_type(uid) == "uuid"
    assert _infer_type(dt) == "datetime"
    assert _infer_type(vv) == "vector<float64, 1>"
    assert _infer_type(CodeBlock("go", "x")) == "code_block<go>"
    assert _infer_type(MarkdownBlock("m")) == "markdown_block"
    assert _infer_type(EnumValue("a", 0)) == "enum"
    assert _infer_type(RelayRef(uid, 0, "")) == "ref"
    assert _infer_type({"a": 1}) == "object"
    assert _infer_type([1]) == "array"

    class X:
        pass

    assert _infer_type(X()) == "string"


def test_encode_value_inline_exhaustive() -> None:
    dt = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    assert _encode_value_inline("bool", True) == "true"
    assert _encode_value_inline("int32", 4) == "4"
    assert _encode_value_inline("float64", 0.25) == "0.25"
    assert '"hi"' in _encode_value_inline("string", "hi")
    assert "550e" in _encode_value_inline("uuid", "550e8400-e29b-41d4-a716-446655440000")
    assert _encode_value_inline("datetime", dt).startswith('"')
    assert _encode_value_inline("datetime", "raw").startswith('"')
    assert _encode_value_inline("uri", "https://a").startswith('"')
    ev = EnumValue("role", 1)
    assert "enum<" in _encode_value_inline("enum<Role>", ev)
    vv = VectorValue(VectorDtype.FLOAT32, 2, np.array([1.0, 2.0], dtype=np.float32))
    assert "[1.0, 2.0]" in _encode_value_inline("vector<float32, 2>", vv)
    assert "[1.0]" in _encode_value_inline("vector<float32, 1>", [1.0])
    out = _encode_value_inline("totally_other", 123)
    assert '"' in out and "123" in out


def test_module_encode_text_wrapper() -> None:
    sch = _minimal_schema([SchemaField("z", "bool", True)])
    s = encode_text({"z": False}, sch)
    assert "@relay" in s
    assert "false" in s


def test_datetime_type_mismatch_and_code_block_mismatch() -> None:
    sch = _minimal_schema(
        [
            SchemaField("d", "datetime", True),
            SchemaField("c", "code_block<py>", True),
        ]
    )
    enc = RelayTextEncoder(sch)
    with pytest.raises(TypeMismatchError):
        enc.encode_text({"d": [], "c": CodeBlock("py", "x")})
    with pytest.raises(TypeMismatchError):
        enc.encode_text({"d": "2026-01-01T00:00:00Z", "c": 123})


def test_format_float_nan_gets_decimal_suffix() -> None:
    s = _format_float(float("nan"))
    assert s.endswith(".0")


def test_encode_value_inline_null_and_enum_str() -> None:
    assert _encode_value_inline("string", None) == "null"
    assert _encode_value_inline("enum<Role>", "assistant") == "assistant"
