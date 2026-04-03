"""Direct ``relay.decoder._decode_value`` / header edge cases for coverage."""

from __future__ import annotations

import struct

import pytest

import relay.decoder as dec
from relay.errors import DecodingError, ParseError, TypeMismatchError
from relay.types import SchemaField, TypeTag, VectorDtype


def _sf(
    tag: TypeTag,
    *,
    enum_values: list[str] | None = None,
    vector_dtype: VectorDtype | None = None,
    vector_dim: int | None = None,
    element_type_tag: TypeTag | None = None,
    sub_fields: list[SchemaField] | None = None,
) -> SchemaField:
    return SchemaField(
        name="p",
        type_tag=tag,
        field_id=1,
        required=True,
        sub_fields=sub_fields or [],
        enum_values=enum_values or [],
        vector_dtype=vector_dtype,
        vector_dim=vector_dim,
        element_type_tag=element_type_tag,
    )


@pytest.mark.parametrize(
    ("tag", "raw"),
    [
        (TypeTag.NULL, b"x"),
        (TypeTag.BOOL, b""),
        (TypeTag.INT8, b""),
        (TypeTag.INT16, b"\x00"),
        (TypeTag.INT32, b"\x00\x00\x00"),
        (TypeTag.INT64, b"\x00" * 7),
        (TypeTag.UINT8, b""),
        (TypeTag.UINT16, b"\x00"),
        (TypeTag.UINT32, b"\x00\x00\x00"),
        (TypeTag.UINT64, b"\x00" * 7),
        (TypeTag.FLOAT32, b"\x00\x00\x00"),
        (TypeTag.FLOAT64, b"\x00" * 7),
    ],
)
def test_decode_value_truncated_scalars(tag: TypeTag, raw: bytes) -> None:
    with pytest.raises(ParseError):
        dec._decode_value(raw, tag, _sf(tag), "p")


def test_decode_uuid_wrong_len() -> None:
    with pytest.raises(ParseError):
        dec._decode_value(b"\x00" * 15, TypeTag.UUID, _sf(TypeTag.UUID), "p")


def test_decode_markdown_length_mismatch() -> None:
    raw = struct.pack("<I", 10) + b"short"
    with pytest.raises(ParseError):
        dec._decode_value(raw, TypeTag.MARKDOWN_BLOCK, _sf(TypeTag.MARKDOWN_BLOCK), "p")


def test_decode_ref_bad_terminator() -> None:
    uid = b"\x00" * 16
    raw = uid + struct.pack("<I", 0) + b"nul"
    with pytest.raises(ParseError):
        dec._decode_value(raw, TypeTag.REF, _sf(TypeTag.REF), "p")


def test_decode_array_missing_elem_tag() -> None:
    with pytest.raises(DecodingError):
        dec._decode_value(struct.pack("<I", 0), TypeTag.ARRAY, _sf(TypeTag.ARRAY), "p")


def test_decode_array_trailing() -> None:
    sf = _sf(TypeTag.ARRAY, element_type_tag=TypeTag.INT32)
    raw = struct.pack("<I", 0) + b"extra"
    with pytest.raises(ParseError):
        dec._decode_value(raw, TypeTag.ARRAY, sf, "p")


def test_read_field_header_truncated() -> None:
    with pytest.raises(ParseError):
        dec._read_field_header(b"\x00\x00", 0)


def test_decode_vector_missing_schema() -> None:
    with pytest.raises(DecodingError):
        dec._decode_vector(b"\x00" * 16, _sf(TypeTag.VECTOR), "p")


def test_decode_vector_dtype_mismatch() -> None:
    sf = _sf(TypeTag.VECTOR, vector_dtype=VectorDtype.FLOAT32, vector_dim=1)
    raw = struct.pack("<II", int(VectorDtype.FLOAT64), 1) + b"\x00" * 8
    with pytest.raises(TypeMismatchError):
        dec._decode_value(raw, TypeTag.VECTOR, sf, "p")


def test_decode_code_block_truncated() -> None:
    with pytest.raises(ParseError):
        dec._decode_code_block(b"\x00", "p")
