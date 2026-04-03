"""
Binary Relay encoder — Python dicts to wire-format bytes.

Operates directly on Python objects; JSON is not used as an intermediate
representation for message payloads.
"""

from __future__ import annotations

import struct
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import numpy as np

from relay.errors import EncodingError, TypeMismatchError, ValidationError
from relay.schema import RelaySchema as SourceSchema
from relay.schema_compile import compile_schema
from relay.types import (
    FIELD_HEADER_SIZE,
    FRAME_HEADER_SIZE,
    MAGIC,
    VECTOR_DTYPE_ITEMSIZE,
    VERSION,
    CodeBlock,
    DeltaOp,
    DeltaOpType,
    EnumValue,
    MarkdownBlock,
    MessageType,
    RelayRef,
    SchemaField,
    TypeTag,
    VectorDtype,
    VectorValue,
)
from relay.validate import validate_dict

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def encode(
    obj: dict[str, Any],
    schema: SourceSchema,
    *,
    message_type: MessageType = MessageType.FULL,
) -> bytes:
    """Encode a Python dict as a binary Relay FULL message.

    Parameters
    ----------
    obj : dict
        Field names must match the schema; values must conform to wire types.
    schema : relay.schema.RelaySchema
        Source schema (string type names).
    message_type : MessageType, optional
        Defaults to ``FULL``. Other types use dedicated helpers where needed.

    Returns
    -------
    bytes
        Complete frame: 12-byte header + payload.

    Raises
    ------
    ValidationError
        If a required field is missing.
    TypeMismatchError
        If a value does not match the declared type (including int→float).
    EncodingError
        On other encoding failures.
    """
    compiled = compile_schema(schema)
    validate_dict(obj, compiled)

    if message_type != MessageType.FULL:
        raise EncodingError(
            "encode() only builds FULL messages; use delta.encode_delta_frame() for DELTA",
            details={"message_type": message_type.name},
        )

    payload = _encode_full_payload(obj, compiled)
    return _build_frame(MessageType.FULL, compiled.schema_hash, payload)


def _build_frame(msg_type: MessageType, schema_hash: bytes, payload: bytes) -> bytes:
    header = bytearray(FRAME_HEADER_SIZE)
    header[0] = MAGIC
    header[1] = VERSION
    struct.pack_into("<H", header, 2, int(msg_type))
    header[4:8] = schema_hash[:4]
    struct.pack_into("<I", header, 8, len(payload))
    return bytes(header) + payload


def _encode_full_payload(obj: dict[str, Any], schema: Any) -> bytes:
    chunks: list[bytes] = []
    for cf in sorted(schema.fields, key=lambda f: f.field_id):
        if cf.name not in obj:
            continue
        val = obj[cf.name]
        if val is None and cf.required:
            raise ValidationError(
                f"Required field {cf.name!r} cannot be null",
                field_path=cf.name,
            )
        if val is None and not cf.required:
            # Optional omitted — skip field entirely (canonical: no null for optional)
            continue
        chunks.append(_encode_top_field(cf, val))
    return b"".join(chunks)


def _encode_top_field(cf: SchemaField, value: Any) -> bytes:
    body = _encode_typed_value(cf, value, cf.name)
    return _pack_field_frame(cf.field_id, _value_type_tag(cf, value), body)


def _value_type_tag(cf: SchemaField, value: Any) -> int:
    """Return wire type tag for *value* under *cf* (handles EnumValue etc.)."""
    return int(cf.type_tag)


def _pack_field_frame(field_id: int, type_tag: int, value_bytes: bytes) -> bytes:
    hdr = bytearray(FIELD_HEADER_SIZE)
    struct.pack_into("<H", hdr, 0, field_id)
    hdr[2] = type_tag & 0xFF
    struct.pack_into("<I", hdr, 3, len(value_bytes))
    return bytes(hdr) + value_bytes


def _encode_typed_value(cf: SchemaField, value: Any, path: str) -> bytes:
    tag = cf.type_tag

    if tag == TypeTag.NULL:
        if value is not None:
            raise TypeMismatchError(
                f"Expected null at {path}",
                field_path=path,
                details={"got": type(value).__name__},
            )
        return b""

    if tag == TypeTag.BOOL:
        if not isinstance(value, bool):
            raise TypeMismatchError(
                f"Expected bool at {path}, got {type(value).__name__}",
                field_path=path,
            )
        return b"\x01" if value else b"\x00"

    if tag in (
        TypeTag.INT8, TypeTag.INT16, TypeTag.INT32, TypeTag.INT64,
        TypeTag.UINT8, TypeTag.UINT16, TypeTag.UINT32, TypeTag.UINT64,
    ):
        return _encode_int_family(tag, value, path)

    if tag == TypeTag.FLOAT32:
        if isinstance(value, bool) or not isinstance(value, float):
            raise TypeMismatchError(
                f"float32 field {path} requires Python float, not {type(value).__name__}",
                field_path=path,
                details={"expected": "float32", "got": type(value).__name__},
            )
        return struct.pack("<f", float(value))

    if tag == TypeTag.FLOAT64:
        if isinstance(value, bool) or not isinstance(value, float):
            raise TypeMismatchError(
                f"float64 field {path} requires Python float, not {type(value).__name__}",
                field_path=path,
            )
        return struct.pack("<d", float(value))

    if tag == TypeTag.STRING:
        if not isinstance(value, str):
            raise TypeMismatchError(
                f"Expected str at {path}",
                field_path=path,
            )
        return value.encode("utf-8")

    if tag == TypeTag.BYTES:
        if isinstance(value, (bytes, bytearray, memoryview)):
            return bytes(value)
        raise TypeMismatchError(
            f"Expected bytes at {path}",
            field_path=path,
        )

    if tag == TypeTag.UUID:
        u = _as_uuid(value, path)
        return u.bytes

    if tag == TypeTag.DATETIME:
        return _encode_datetime(value, path)

    if tag == TypeTag.URI:
        if not isinstance(value, str):
            raise TypeMismatchError(f"URI field {path} expects str", field_path=path)
        _basic_uri_check(value, path)
        return value.encode("utf-8")

    if tag == TypeTag.ENUM:
        return _encode_enum(cf, value, path)

    if tag == TypeTag.VECTOR:
        return _encode_vector(cf, value, path)

    if tag == TypeTag.CODE_BLOCK:
        return _encode_code_block(value, path)

    if tag == TypeTag.MARKDOWN_BLOCK:
        if isinstance(value, MarkdownBlock):
            raw = value.content.encode("utf-8")
        elif isinstance(value, str):
            raw = value.encode("utf-8")
        else:
            raise TypeMismatchError(
                f"markdown_block expects str or MarkdownBlock at {path}",
                field_path=path,
            )
        return struct.pack("<I", len(raw)) + raw

    if tag == TypeTag.REF:
        if not isinstance(value, RelayRef):
            raise TypeMismatchError(
                f"ref field expects RelayRef at {path}",
                field_path=path,
            )
        return _encode_ref_bytes(value)

    if tag == TypeTag.ARRAY:
        return _encode_array(cf, value, path)

    if tag == TypeTag.OBJECT:
        if not isinstance(value, dict):
            raise TypeMismatchError(
                f"object field {path} expects dict",
                field_path=path,
            )
        return _encode_object(cf, value, path)

    if tag == TypeTag.DELTA_OP:
        if not isinstance(value, DeltaOp):
            raise TypeMismatchError(
                f"delta_op expects DeltaOp at {path}",
                field_path=path,
            )
        return _encode_delta_op_bytes(value)

    raise EncodingError(
        f"Unsupported type tag {tag!r} at {path}",
        field_path=path,
    )


def _encode_int_family(tag: TypeTag, value: Any, path: str) -> bytes:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeMismatchError(
            f"Integer field {path} expects int",
            field_path=path,
            details={"got": type(value).__name__},
        )
    v = int(value)
    try:
        if tag == TypeTag.INT8:
            if not (-128 <= v <= 127):
                raise ValueError
            return struct.pack("<b", v)
        if tag == TypeTag.INT16:
            return struct.pack("<h", v)
        if tag == TypeTag.INT32:
            return struct.pack("<i", v)
        if tag == TypeTag.INT64:
            return struct.pack("<q", v)
        if tag == TypeTag.UINT8:
            if not (0 <= v <= 255):
                raise ValueError
            return struct.pack("<B", v)
        if tag == TypeTag.UINT16:
            if not (0 <= v <= 65535):
                raise ValueError
            return struct.pack("<H", v)
        if tag == TypeTag.UINT32:
            if not (0 <= v <= 4294967295):
                raise ValueError
            return struct.pack("<I", v)
        if tag == TypeTag.UINT64:
            if v < 0 or v > 2**64 - 1:
                raise ValueError
            return struct.pack("<Q", v)
    except (struct.error, ValueError) as exc:
        raise TypeMismatchError(
            f"Integer value out of range for {tag.name} at {path}: {v}",
            field_path=path,
            details={"value": v},
        ) from exc
    raise EncodingError(f"Unhandled int tag {tag}", field_path=path)


def _encode_datetime(value: Any, path: str) -> bytes:
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(timezone.utc)
        us = int(dt.timestamp() * 1_000_000)
    elif isinstance(value, int):
        us = int(value)
    else:
        raise TypeMismatchError(
            f"datetime field {path} expects datetime or int (microseconds)",
            field_path=path,
        )
    return struct.pack("<q", us)


def _as_uuid(value: Any, path: str) -> UUID:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        return UUID(value)
    raise TypeMismatchError(
        f"uuid field {path} expects UUID or str",
        field_path=path,
    )


def _encode_enum(cf: SchemaField, value: Any, path: str) -> bytes:
    names = cf.enum_values
    if not names:
        raise EncodingError(
            f"Enum field {path} has no enum_values on compiled schema",
            field_path=path,
        )
    if isinstance(value, EnumValue):
        idx = value.index
    elif isinstance(value, str):
        if value not in names:
            raise TypeMismatchError(
                f"Invalid enum symbol {value!r} at {path}",
                field_path=path,
                details={"allowed": names},
            )
        idx = names.index(value)
    elif isinstance(value, int):
        idx = int(value)
        if idx < 0 or idx >= len(names):
            raise TypeMismatchError(
                f"Enum index {idx} out of range at {path}",
                field_path=path,
            )
    else:
        raise TypeMismatchError(
            f"Enum field {path} expects str, int, or EnumValue",
            field_path=path,
        )
    return struct.pack("<I", idx)


def _encode_vector(cf: SchemaField, value: Any, path: str) -> bytes:
    if cf.vector_dtype is None or cf.vector_dim is None:
        raise EncodingError(
            f"Vector field {path} missing dtype/dim on schema",
            field_path=path,
        )
    dtype = cf.vector_dtype
    dim = cf.vector_dim
    itemsize = VECTOR_DTYPE_ITEMSIZE[dtype]

    if isinstance(value, VectorValue):
        vv = value
        if vv.dtype != dtype or vv.dim != dim:
            raise TypeMismatchError(
                f"VectorValue dtype/dim mismatch at {path}",
                field_path=path,
            )
        arr = vv.data
    elif isinstance(value, np.ndarray):
        if value.shape != (dim,):
            raise TypeMismatchError(
                f"Vector at {path} must have shape ({dim},), got {value.shape}",
                field_path=path,
            )
        arr = value.astype(vector_dtype_to_np(dtype), copy=False)
    elif isinstance(value, (list, tuple)):
        if len(value) != dim:
            raise TypeMismatchError(
                f"Vector at {path} needs length {dim}, got {len(value)}",
                field_path=path,
            )
        arr = np.array(value, dtype=vector_dtype_to_np(dtype))
    else:
        raise TypeMismatchError(
            f"Vector field {path} expects list, ndarray, or VectorValue",
            field_path=path,
        )

    body = struct.pack("<II", int(dtype), dim) + arr.tobytes()
    if len(body) != 8 + dim * itemsize:
        raise EncodingError("Vector byte length mismatch", field_path=path)
    return body


def vector_dtype_to_np(dt: VectorDtype) -> type:
    return {
        VectorDtype.FLOAT16: np.float16,
        VectorDtype.FLOAT32: np.float32,
        VectorDtype.FLOAT64: np.float64,
        VectorDtype.INT8: np.int8,
    }[dt]


def _encode_code_block(value: Any, path: str) -> bytes:
    if isinstance(value, CodeBlock):
        lang, code = value.lang, value.code
    elif isinstance(value, dict):
        lang = str(value.get("lang", ""))
        code = str(value.get("code", ""))
    else:
        raise TypeMismatchError(
            f"code_block at {path} expects CodeBlock or dict",
            field_path=path,
        )
    if not lang:
        raise ValidationError(
            "code_block language must be non-empty",
            field_path=path,
        )
    lb = lang.encode("utf-8")
    cb = code.encode("utf-8")
    return struct.pack("<H", len(lb)) + lb + struct.pack("<I", len(cb)) + cb


def _encode_ref_bytes(ref: RelayRef) -> bytes:
    fp = ref.field_path.encode("utf-8") + b"\x00"
    return ref.session_id.bytes + struct.pack("<I", ref.call_index) + fp


def _encode_array(cf: SchemaField, value: Any, path: str) -> bytes:
    if not isinstance(value, (list, tuple)):
        raise TypeMismatchError(
            f"array field {path} expects list",
            field_path=path,
        )
    elem_tag = cf.element_type_tag
    if elem_tag is None:
        raise EncodingError(
            f"array field {path} missing element_type_tag",
            field_path=path,
        )
    parts = [struct.pack("<I", len(value))]
    for i, item in enumerate(value):
        sub_cf = _synthetic_element_field(elem_tag)
        vb = _encode_typed_value(sub_cf, item, f"{path}[{i}]")
        parts.append(_pack_field_frame(0, int(elem_tag), vb))
    return b"".join(parts)


def _synthetic_element_field(elem_tag: TypeTag) -> SchemaField:
    """Minimal SchemaField used only to dispatch scalar array elements."""
    return SchemaField(
        name="_elem",
        type_tag=elem_tag,
        field_id=0,
        required=True,
        sub_fields=[],
        enum_values=[],
        vector_dtype=None,
        vector_dim=None,
        element_type_tag=None,
    )


def _encode_object(cf: SchemaField, obj: dict[str, Any], path: str) -> bytes:
    parts: list[bytes] = []
    for sub in sorted(cf.sub_fields, key=lambda f: f.field_id):
        if sub.name not in obj:
            if sub.required:
                raise ValidationError(
                    f"Missing required nested field {sub.name!r} under {path}",
                    field_path=f"{path}.{sub.name}",
                )
            continue
        val = obj[sub.name]
        if val is None and not sub.required:
            continue
        if val is None and sub.required:
            raise ValidationError(
                f"Required nested field {sub.name!r} is null under {path}",
                field_path=f"{path}.{sub.name}",
            )
        body = _encode_typed_value(sub, val, f"{path}.{sub.name}")
        parts.append(_pack_field_frame(sub.field_id, _value_type_tag(sub, val), body))
    return b"".join(parts)


def _basic_uri_check(s: str, path: str) -> None:
    if not s or " " in s or "\n" in s:
        raise TypeMismatchError(
            f"Invalid URI at {path}",
            field_path=path,
        )
    if ":" not in s:
        raise TypeMismatchError(
            f"URI at {path} must be absolute (scheme:...)",
            field_path=path,
        )


_OP_TO_BYTE = {
    DeltaOpType.SET: 0x01,
    DeltaOpType.DEL: 0x02,
    DeltaOpType.APP: 0x03,
    DeltaOpType.SPL: 0x04,
}


def _encode_delta_op_bytes(op: DeltaOp) -> bytes:
    opc = _OP_TO_BYTE.get(op.op_type)
    if opc is None:
        raise EncodingError(
            f"Unknown delta op {op.op_type!r}",
            details={"op": op.op_type},
        )
    fp = op.field_path.encode("utf-8") + b"\x00"
    head = bytes([opc]) + fp
    if op.op_type == DeltaOpType.DEL:
        return head
    if op.op_type in (DeltaOpType.SET, DeltaOpType.APP):
        if op.type_tag is None:
            raise EncodingError("SET/APP delta op requires type_tag")
        vb = _encode_delta_value(int(op.type_tag), op.value)
        return head + bytes([int(op.type_tag) & 0xFF]) + struct.pack("<I", len(vb)) + vb
    if op.op_type == DeltaOpType.SPL:
        if (
            op.splice_start is None
            or op.splice_end is None
            or op.type_tag is None
        ):
            raise EncodingError("SPL delta op requires splice_start, splice_end, type_tag")
        vb = _encode_delta_value(int(op.type_tag), op.value)
        return (
            head
            + struct.pack("<II", op.splice_start, op.splice_end)
            + bytes([int(op.type_tag) & 0xFF])
            + struct.pack("<I", len(vb))
            + vb
        )
    raise EncodingError(f"Unhandled delta op {op.op_type}")


def _encode_delta_value(type_tag: int, value: Any) -> bytes:
    """Encode a value for delta payload (scalar / small structure)."""
    cf = _synthetic_element_field(TypeTag(type_tag))
    return _encode_typed_value(cf, value, "__delta__")


__all__ = ["_build_frame", "_pack_field_frame", "encode"]
