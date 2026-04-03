"""Encoder validation and error paths for full coverage."""

from __future__ import annotations

import numpy as np
import pytest

from relay.encoder import encode
from relay.errors import EncodingError, TypeMismatchError, ValidationError
from relay.schema import RelaySchema
from relay.types import (
    CodeBlock,
    DeltaOp,
    DeltaOpType,
    MessageType,
    VectorDtype,
    VectorValue,
)


def S(fields: list[dict], enums: dict | None = None, name: str = "t") -> RelaySchema:
    return RelaySchema.from_dict(
        {"name": name, "version": 1, "fields": fields, "enums": enums or {}}
    )


def test_encode_required_null_field_validation_error() -> None:
    sch = S([{"name": "x", "type": "null", "required": True}])
    with pytest.raises(ValidationError):
        encode({"x": None}, sch)


def test_encode_null_field_non_null() -> None:
    sch = S([{"name": "n", "type": "null", "required": False}])
    with pytest.raises(TypeMismatchError):
        encode({"n": 1}, sch)


def test_encode_bool_wrong() -> None:
    sch = S([{"name": "b", "type": "bool", "required": True}])
    with pytest.raises(TypeMismatchError):
        encode({"b": 1}, sch)


def test_encode_float32_requires_float() -> None:
    sch = S([{"name": "f", "type": "float32", "required": True}])
    with pytest.raises(TypeMismatchError):
        encode({"f": 1}, sch)


def test_encode_float64_requires_float() -> None:
    sch = S([{"name": "f", "type": "float64", "required": True}])
    with pytest.raises(TypeMismatchError):
        encode({"f": 1}, sch)


def test_encode_string_wrong() -> None:
    sch = S([{"name": "s", "type": "string", "required": True}])
    with pytest.raises(TypeMismatchError):
        encode({"s": 1}, sch)


def test_encode_bytes_wrong() -> None:
    sch = S([{"name": "b", "type": "bytes", "required": True}])
    with pytest.raises(TypeMismatchError):
        encode({"b": "x"}, sch)


def test_encode_uri_invalid() -> None:
    sch = S([{"name": "u", "type": "uri", "required": True}])
    with pytest.raises(TypeMismatchError):
        encode({"u": "no-scheme"}, sch)


def test_encode_markdown_wrong_type() -> None:
    sch = S([{"name": "m", "type": "markdown_block", "required": True}])
    with pytest.raises(TypeMismatchError):
        encode({"m": 1}, sch)


def test_encode_ref_wrong() -> None:
    sch = S([{"name": "r", "type": "ref", "required": True}])
    with pytest.raises(TypeMismatchError):
        encode({"r": "nope"}, sch)


def test_encode_object_not_dict() -> None:
    sch = S([{"name": "o", "type": "object", "required": True, "fields": []}])
    with pytest.raises(TypeMismatchError):
        encode({"o": []}, sch)


def test_encode_delta_op_wrong() -> None:
    sch = S([{"name": "d", "type": "delta_op", "required": True}])
    with pytest.raises(TypeMismatchError):
        encode({"d": "x"}, sch)


def test_encode_int_bool_rejected() -> None:
    sch = S([{"name": "i", "type": "int32", "required": True}])
    with pytest.raises(TypeMismatchError):
        encode({"i": True}, sch)


def test_encode_int8_overflow() -> None:
    sch = S([{"name": "i", "type": "int8", "required": True}])
    with pytest.raises(TypeMismatchError):
        encode({"i": 200}, sch)


def test_encode_uint8_overflow() -> None:
    sch = S([{"name": "i", "type": "uint8", "required": True}])
    with pytest.raises(TypeMismatchError):
        encode({"i": 300}, sch)


def test_encode_datetime_wrong() -> None:
    sch = S([{"name": "d", "type": "datetime", "required": True}])
    with pytest.raises(TypeMismatchError):
        encode({"d": "2026-01-01"}, sch)


def test_encode_uuid_wrong() -> None:
    sch = S([{"name": "u", "type": "uuid", "required": True}])
    with pytest.raises(TypeMismatchError):
        encode({"u": 123}, sch)


def test_encode_enum_empty_values_direct() -> None:
    from relay.encoder import _encode_enum
    from relay.types import SchemaField, TypeTag

    cf = SchemaField("e", TypeTag.ENUM, field_id=1, enum_values=[])
    with pytest.raises(EncodingError):
        _encode_enum(cf, "a", "e")


def test_encode_enum_invalid_string() -> None:
    sch = S([{"name": "e", "type": "enum<R>", "required": True}], {"R": ["a"]})
    with pytest.raises(TypeMismatchError):
        encode({"e": "z"}, sch)


def test_encode_enum_bad_index() -> None:
    sch = S([{"name": "e", "type": "enum<R>", "required": True}], {"R": ["a"]})
    with pytest.raises(TypeMismatchError):
        encode({"e": 9}, sch)


def test_encode_enum_bad_type() -> None:
    sch = S([{"name": "e", "type": "enum<R>", "required": True}], {"R": ["a"]})
    with pytest.raises(TypeMismatchError):
        encode({"e": 3.14}, sch)


def test_encode_vector_bad() -> None:
    sch = S([{"name": "v", "type": "vector<float32, 2>", "required": True}])
    with pytest.raises(TypeMismatchError):
        encode({"v": [1.0]}, sch)
    vv = VectorValue(VectorDtype.FLOAT64, 2, np.array([1.0, 2.0]))
    with pytest.raises(TypeMismatchError):
        encode({"v": vv}, sch)


def test_encode_vector_not_array_like() -> None:
    sch = S([{"name": "v", "type": "vector<float32, 2>", "required": True}])
    with pytest.raises(TypeMismatchError):
        encode({"v": "n"}, sch)


def test_encode_code_block_bad() -> None:
    sch = S([{"name": "c", "type": "code_block", "required": True}])
    with pytest.raises(TypeMismatchError):
        encode({"c": 1}, sch)


def test_encode_code_block_empty_lang() -> None:
    sch = S([{"name": "c", "type": "code_block", "required": True}])
    with pytest.raises(ValidationError):
        encode({"c": CodeBlock(lang="", code="x")}, sch)


def test_encode_array_not_list() -> None:
    sch = S([{"name": "a", "type": "array<int32>", "required": True}])
    with pytest.raises(TypeMismatchError):
        encode({"a": 1}, sch)


def test_encode_nested_required_missing() -> None:
    sch = S(
        [
            {
                "name": "o",
                "type": "object",
                "required": True,
                "fields": [{"name": "k", "type": "int32", "required": True}],
            }
        ]
    )
    with pytest.raises(ValidationError):
        encode({"o": {}}, sch)


def test_encode_nested_null_required() -> None:
    sch = S(
        [
            {
                "name": "o",
                "type": "object",
                "required": True,
                "fields": [{"name": "k", "type": "int32", "required": True}],
            }
        ]
    )
    with pytest.raises(ValidationError):
        encode({"o": {"k": None}}, sch)


def test_encode_delta_op_bytes_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    import relay.encoder as enc
    from relay.types import TypeTag

    with pytest.raises(EncodingError):
        enc._encode_delta_op_bytes(DeltaOp(DeltaOpType.SET, "p", None, 1))
    with pytest.raises(EncodingError):
        enc._encode_delta_op_bytes(
            DeltaOp(DeltaOpType.SPL, "p", TypeTag.INT32, 1, splice_start=None, splice_end=1),
        )
    monkeypatch.setattr(enc, "_OP_TO_BYTE", {})
    with pytest.raises(EncodingError):
        enc._encode_delta_op_bytes(DeltaOp(DeltaOpType.SET, "p", TypeTag.STRING, "x"))


def test_encode_message_type_not_full() -> None:
    sch = S([{"name": "m", "type": "string", "required": True}])
    with pytest.raises(EncodingError):
        encode({"m": "x"}, sch, message_type=MessageType.DELTA)
