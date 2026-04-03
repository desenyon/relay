"""
Binary Relay decoder — wire bytes to :class:`~relay.types.RelayMessage`.

Supports one-shot :func:`decode`, incremental :class:`RelayStreamDecoder`, and
:class:`decode_stream` for file-like inputs.
"""

from __future__ import annotations

import struct
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any, BinaryIO
from uuid import UUID

import numpy as np

from relay.errors import (
    DecodingError,
    ParseError,
    SchemaHashMismatch,
    SchemaNotFoundError,
    TypeMismatchError,
)
from relay.registry import SchemaRegistry, get_default_registry
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
    RelayField,
    RelayMessage,
    RelayRef,
    SchemaField,
    TypeTag,
    VectorDtype,
    VectorValue,
)
from relay.validate import validate_message

_BYTE_TO_OP: dict[int, DeltaOpType] = {
    0x01: DeltaOpType.SET,
    0x02: DeltaOpType.DEL,
    0x03: DeltaOpType.APP,
    0x04: DeltaOpType.SPL,
}


def decode(
    data: bytes,
    schema: SourceSchema | None = None,
    *,
    registry: SchemaRegistry | None = None,
    validate: bool = True,
) -> RelayMessage:
    """Decode a complete binary Relay frame.

    Parameters
    ----------
    data : bytes
        Single message: 12-byte header + payload.
    schema : relay.schema.RelaySchema, optional
        If provided, used instead of registry lookup. Must match header hash
        unless the frame is ``ERROR`` (hash zero).
    registry : SchemaRegistry, optional
        Defaults to :data:`relay.registry.default_registry`.
    validate : bool, optional
        If ``True`` (default), run :func:`relay.validate.validate_message`.

    Returns
    -------
    RelayMessage

    Raises
    ------
    ParseError
        On malformed bytes.
    SchemaNotFoundError
        If the header hash cannot be resolved.
    TypeMismatchError
        If a field disagrees with the schema.
    """
    reg = registry or get_default_registry()
    msg, _off = _decode_one(data, 0, schema, reg, validate=validate)
    if _off != len(data):
        raise ParseError(
            "Trailing bytes after Relay frame",
            details={"offset": _off, "total": len(data)},
        )
    return msg


def decode_stream(
    stream: BinaryIO,
    schema: SourceSchema | None = None,
    *,
    registry: SchemaRegistry | None = None,
    validate: bool = True,
    chunk_size: int = 4096,
) -> Iterator[RelayMessage]:
    """Yield decoded messages from a byte stream (supports chunked reads).

    Parameters
    ----------
    stream : BinaryIO
        Readable binary stream.
    schema : relay.schema.RelaySchema, optional
        Passed through to :func:`decode` for every message.
    registry : SchemaRegistry, optional
        Registry for hash lookup.
    validate : bool, optional
        Validate each message.
    chunk_size : int, optional
        Read buffer size.

    Yields
    ------
    RelayMessage
        One complete message per iteration.
    """
    dec = RelayStreamDecoder(schema=schema, registry=registry, validate=validate)
    while True:
        chunk = stream.read(chunk_size)
        if not chunk:
            break
        for msg in dec.feed(chunk):
            yield msg
    for msg in dec.flush():
        yield msg


class RelayStreamDecoder:
    """Incremental decoder: feed byte chunks, obtain complete messages."""

    def __init__(
        self,
        schema: SourceSchema | None = None,
        *,
        registry: SchemaRegistry | None = None,
        validate: bool = True,
    ) -> None:
        self._schema = schema
        self._registry = registry or get_default_registry()
        self._validate = validate
        self._buf = bytearray()

    def feed(self, data: bytes) -> list[RelayMessage]:
        """Append *data* and return any newly completed messages."""
        self._buf.extend(data)
        out: list[RelayMessage] = []
        while True:
            msg, consumed = self._try_extract_one()
            if msg is None:
                break
            del self._buf[:consumed]
            out.append(msg)
        return out

    def flush(self) -> list[RelayMessage]:
        """Finish decoding; raises if the buffer is non-empty and incomplete."""
        if not self._buf:
            return []
        msg, consumed = self._try_extract_one()
        if msg is None or consumed != len(self._buf):
            raise ParseError(
                "Incomplete Relay frame in stream decoder",
                details={"buffered": len(self._buf)},
            )
        self._buf.clear()
        return [msg]

    def _try_extract_one(self) -> tuple[RelayMessage | None, int]:
        if len(self._buf) < FRAME_HEADER_SIZE:
            return None, 0
        total_len = FRAME_HEADER_SIZE + struct.unpack_from("<I", self._buf, 8)[0]
        if len(self._buf) < total_len:
            return None, 0
        chunk = bytes(self._buf[:total_len])
        msg, _ = _decode_one(
            chunk,
            0,
            self._schema,
            self._registry,
            validate=self._validate,
        )
        return msg, total_len


def _decode_one(
    data: bytes,
    start: int,
    override: SourceSchema | None,
    registry: SchemaRegistry,
    *,
    validate: bool,
) -> tuple[RelayMessage, int]:
    off = start
    if len(data) - off < FRAME_HEADER_SIZE:
        raise ParseError("Not enough bytes for frame header", details={"need": FRAME_HEADER_SIZE})

    magic = data[off]
    if magic != MAGIC:
        raise ParseError(
            "Invalid magic byte",
            details={"expected": hex(MAGIC), "got": hex(magic)},
        )
    ver = data[off + 1]
    if ver != VERSION:
        raise ParseError(
            "Unsupported wire version",
            details={"expected": VERSION, "got": ver},
        )
    msg_type = MessageType(struct.unpack_from("<H", data, off + 2)[0])
    schema_hash = data[off + 4 : off + 8]
    payload_len = struct.unpack_from("<I", data, off + 8)[0]
    off += FRAME_HEADER_SIZE
    if len(data) - off < payload_len:
        raise ParseError(
            "Truncated payload",
            details={"need": payload_len, "have": len(data) - off},
        )
    payload = data[off : off + payload_len]
    off += payload_len
    raw = data[start:off]

    if msg_type == MessageType.SCHEMA_DEF:
        fields = _decode_schema_def_payload(payload)
        msg = RelayMessage(
            message_type=msg_type,
            schema_hash=schema_hash,
            fields=fields,
            raw_bytes=raw,
        )
        return msg, off

    compiled, source_schema = _resolve_schema(
        msg_type,
        schema_hash,
        override,
        registry,
    )

    fields = _decode_payload(
        msg_type,
        payload,
        compiled,
        source_schema,
    )
    msg = RelayMessage(
        message_type=msg_type,
        schema_hash=schema_hash,
        fields=fields,
        raw_bytes=raw,
    )
    if validate and msg_type == MessageType.FULL:
        validate_message(msg, compiled)
    return msg, off


def _resolve_schema(
    msg_type: MessageType,
    schema_hash: bytes,
    override: SourceSchema | None,
    registry: SchemaRegistry,
) -> tuple[Any, SourceSchema | None]:
    """Return (compiled_types_schema, source_schema_or_none)."""
    if msg_type == MessageType.ERROR:
        fake = _error_message_compiled_schema()
        return fake, None

    if override is not None:
        compiled = compile_schema(override)
        if schema_hash != b"\x00\x00\x00\x00" and compiled.schema_hash != schema_hash:
            raise SchemaHashMismatch(
                "Schema override hash does not match frame header",
                details={
                    "header": schema_hash.hex(),
                    "schema": compiled.schema_hash.hex(),
                },
            )
        return compiled, override

    if schema_hash == b"\x00\x00\x00\x00":
        raise SchemaNotFoundError(
            "Frame header schema hash is zero but no schema override provided",
            details={"hash": schema_hash.hex()},
        )

    hx = schema_hash.hex()
    try:
        src = registry.get_by_hash(hx)
    except SchemaNotFoundError:
        raise SchemaNotFoundError(
            f"No schema registered for hash {hx}",
            details={"hash": hx},
        ) from None
    compiled = compile_schema(src)
    return compiled, src


def _error_message_compiled_schema() -> Any:
    """Minimal compiled schema for ERROR payloads."""
    from relay.types import RelaySchema as CompiledRelaySchema

    return CompiledRelaySchema(
        name="__error__",
        version=1,
        fields=[
            SchemaField("error_code", TypeTag.UINT16, 1, True, [], [], None, None, None),
            SchemaField("error_name", TypeTag.STRING, 2, True, [], [], None, None, None),
            SchemaField("message", TypeTag.STRING, 3, True, [], [], None, None, None),
            SchemaField("field_path", TypeTag.STRING, 4, False, [], [], None, None, None),
            SchemaField("expected_type", TypeTag.STRING, 5, False, [], [], None, None, None),
            SchemaField("actual_type", TypeTag.STRING, 6, False, [], [], None, None, None),
            SchemaField("schema_hash", TypeTag.BYTES, 7, False, [], [], None, None, None),
            SchemaField("context", TypeTag.STRING, 8, False, [], [], None, None, None),
        ],
        schema_hash=b"\x00\x00\x00\x00",
    )


def _decode_payload(
    msg_type: MessageType,
    payload: bytes,
    compiled: Any,
    source_schema: SourceSchema | None,
) -> list[RelayField]:
    # SCHEMA_DEF is handled entirely in ``_decode_one`` and never routed here.

    if msg_type == MessageType.REF_ONLY:
        return _decode_ref_only_payload(payload, compiled)

    if msg_type == MessageType.DELTA:
        return _decode_delta_payload(payload, compiled)

    # FULL, ERROR, and generic
    return _decode_full_like_payload(payload, compiled)


def _decode_schema_def_payload(payload: bytes) -> list[RelayField]:
    fields: list[RelayField] = []
    pos = 0
    while pos < len(payload):
        fid, tag, flen, pos2 = _read_field_header(payload, pos)
        pos = pos2
        raw = payload[pos : pos + flen]
        pos += flen
        if fid != 1 or tag != TypeTag.STRING:
            raise TypeMismatchError(
                "SCHEMA_DEF payload must be field 1 string",
                details={"field_id": fid, "tag": int(tag)},
            )
        text = raw.decode("utf-8")
        fields.append(RelayField(1, "schema_text", TypeTag.STRING, text))
    if len(fields) != 1:
        raise ParseError(
            "SCHEMA_DEF payload must contain exactly one string field",
            details={"count": len(fields)},
        )
    return fields


def _decode_ref_only_payload(payload: bytes, compiled: Any) -> list[RelayField]:
    out = _decode_full_like_payload(payload, compiled)
    if len(out) != 1 or out[0].type_tag != TypeTag.REF:
        raise TypeMismatchError(
            "REF_ONLY message must contain exactly one ref field",
        )
    return out


def _decode_delta_payload(payload: bytes, compiled: Any) -> list[RelayField]:
    fields: list[RelayField] = []
    pos = 0
    while pos < len(payload):
        fid, tag, flen, pos2 = _read_field_header(payload, pos)
        pos = pos2
        raw = payload[pos : pos + flen]
        pos += flen
        sf = compiled.field_by_id(fid) if fid != 0 else None
        if fid == 0 and tag == TypeTag.REF:
            name = "__base__"
            val = _decode_ref(raw, "__base__")
        elif tag == TypeTag.DELTA_OP:
            name = sf.name if sf else f"op_{fid}"
            val = _decode_delta_op(raw, name)
        else:
            if sf is None:
                raise TypeMismatchError(
                    f"Unknown field id {fid} in DELTA payload",
                    field_path=str(fid),
                )
            val = _decode_value(raw, tag, sf, sf.name)
            name = sf.name
        fields.append(RelayField(fid, name, TypeTag(tag), val))
    return fields


def _decode_full_like_payload(payload: bytes, compiled: Any) -> list[RelayField]:
    by_id: dict[int, RelayField] = {}
    pos = 0
    while pos < len(payload):
        fid, tag, flen, pos2 = _read_field_header(payload, pos)
        pos = pos2
        raw = payload[pos : pos + flen]
        pos += flen
        if fid in by_id:
            raise ParseError(
                "Duplicate field id in payload",
                details={"field_id": fid},
            )
        sf = compiled.field_by_id(fid)
        if sf is None:
            raise TypeMismatchError(
                f"Unknown field id {fid}",
                field_path=str(fid),
                details={"field_id": fid},
            )
        if int(tag) != int(sf.type_tag):
            raise TypeMismatchError(
                f"Type tag mismatch for field {sf.name}",
                field_path=sf.name,
                details={"expected": sf.type_tag.name, "got": hex(int(tag))},
            )
        val = _decode_value(raw, tag, sf, sf.name)
        by_id[fid] = RelayField(fid, sf.name, TypeTag(tag), val)
    return [by_id[i] for i in sorted(by_id)]


def _read_field_header(data: bytes, pos: int) -> tuple[int, TypeTag, int, int]:
    if len(data) - pos < FIELD_HEADER_SIZE:
        raise ParseError("Truncated field header", details={"offset": pos})
    fid = struct.unpack_from("<H", data, pos)[0]
    tag = TypeTag(data[pos + 2])
    flen = struct.unpack_from("<I", data, pos + 3)[0]
    return fid, tag, flen, pos + FIELD_HEADER_SIZE


def _decode_value(
    raw: bytes,
    tag: TypeTag,
    sf: SchemaField,
    path: str,
) -> Any:
    if tag == TypeTag.NULL:
        if len(raw) != 0:
            raise ParseError("null field must have length 0", field_path=path)
        return None
    if tag == TypeTag.BOOL:
        if len(raw) != 1:
            raise ParseError("bool length must be 1", field_path=path)
        return raw[0] != 0
    if tag == TypeTag.INT8:
        return _unpack_exact("<b", raw, 1, path)
    if tag == TypeTag.INT16:
        return _unpack_exact("<h", raw, 2, path)
    if tag == TypeTag.INT32:
        return _unpack_exact("<i", raw, 4, path)
    if tag == TypeTag.INT64:
        return _unpack_exact("<q", raw, 8, path)
    if tag == TypeTag.UINT8:
        return _unpack_exact("<B", raw, 1, path)
    if tag == TypeTag.UINT16:
        return _unpack_exact("<H", raw, 2, path)
    if tag == TypeTag.UINT32:
        return _unpack_exact("<I", raw, 4, path)
    if tag == TypeTag.UINT64:
        return _unpack_exact("<Q", raw, 8, path)
    if tag == TypeTag.FLOAT32:
        return float(_unpack_exact("<f", raw, 4, path))
    if tag == TypeTag.FLOAT64:
        return float(_unpack_exact("<d", raw, 8, path))
    if tag == TypeTag.STRING:
        return raw.decode("utf-8")
    if tag == TypeTag.BYTES:
        return bytes(raw)
    if tag == TypeTag.UUID:
        if len(raw) != 16:
            raise ParseError("uuid must be 16 bytes", field_path=path)
        return UUID(bytes=bytes(raw))
    if tag == TypeTag.DATETIME:
        us = _unpack_exact("<q", raw, 8, path)
        return datetime.fromtimestamp(us / 1_000_000, tz=timezone.utc)
    if tag == TypeTag.URI:
        return raw.decode("utf-8")
    if tag == TypeTag.ENUM:
        idx = _unpack_exact("<I", raw, 4, path)
        if idx < 0 or idx >= len(sf.enum_values):
            raise TypeMismatchError(
                f"Enum index {idx} out of range at {path}",
                field_path=path,
            )
        name = sf.enum_values[idx]
        return EnumValue(name=name, index=idx)
    if tag == TypeTag.VECTOR:
        return _decode_vector(raw, sf, path)
    if tag == TypeTag.CODE_BLOCK:
        return _decode_code_block(raw, path)
    if tag == TypeTag.MARKDOWN_BLOCK:
        if len(raw) < 4:
            raise ParseError("markdown_block too short", field_path=path)
        ln = struct.unpack_from("<I", raw, 0)[0]
        body = raw[4 : 4 + ln]
        if len(body) != ln:
            raise ParseError("markdown_block length mismatch", field_path=path)
        return MarkdownBlock(content=body.decode("utf-8"))
    if tag == TypeTag.REF:
        return _decode_ref(raw, path)
    if tag == TypeTag.ARRAY:
        return _decode_array(raw, sf, path)
    if tag == TypeTag.OBJECT:
        return _decode_object(raw, sf, path)
    if tag == TypeTag.DELTA_OP:
        return _decode_delta_op(raw, path)
    raise DecodingError(  # pragma: no cover — all ``TypeTag`` values handled above
        f"Unsupported type tag {tag!r}",
        field_path=path,
    )


def _unpack_exact(fmt: str, raw: bytes, n: int, path: str) -> Any:
    if len(raw) != n:
        raise ParseError(
            f"Expected {n} bytes, got {len(raw)}",
            field_path=path,
        )
    return struct.unpack(fmt, raw)[0]


def _decode_vector(raw: bytes, sf: SchemaField, path: str) -> VectorValue:
    if sf.vector_dtype is None or sf.vector_dim is None:
        raise DecodingError("Vector field missing schema dtype/dim", field_path=path)
    if len(raw) < 8:
        raise ParseError("vector too short", field_path=path)
    dtype = VectorDtype(struct.unpack_from("<I", raw, 0)[0])
    dim = struct.unpack_from("<I", raw, 4)[0]
    if dtype != sf.vector_dtype or dim != sf.vector_dim:
        raise TypeMismatchError(
            f"Vector dtype/dim mismatch at {path}",
            field_path=path,
            details={
                "expected": (sf.vector_dtype.name, sf.vector_dim),
                "got": (dtype.name, dim),
            },
        )
    item = VECTOR_DTYPE_ITEMSIZE[dtype]
    need = 8 + dim * item
    if len(raw) != need:
        raise ParseError(
            f"vector byte length mismatch: need {need}, got {len(raw)}",
            field_path=path,
        )
    arr = np.frombuffer(raw, dtype=_np_dtype(dtype), count=dim, offset=8)
    return VectorValue(dtype=dtype, dim=dim, data=np.array(arr, copy=True))


def _np_dtype(dt: VectorDtype) -> type:
    return {
        VectorDtype.FLOAT16: np.float16,
        VectorDtype.FLOAT32: np.float32,
        VectorDtype.FLOAT64: np.float64,
        VectorDtype.INT8: np.int8,
    }[dt]


def _decode_code_block(raw: bytes, path: str) -> CodeBlock:
    if len(raw) < 2:
        raise ParseError("code_block too short", field_path=path)
    ll = struct.unpack_from("<H", raw, 0)[0]
    if len(raw) < 2 + ll + 4:
        raise ParseError("code_block truncated (lang)", field_path=path)
    lang = raw[2 : 2 + ll].decode("utf-8")
    cl = struct.unpack_from("<I", raw, 2 + ll)[0]
    body = raw[2 + ll + 4 : 2 + ll + 4 + cl]
    if len(body) != cl:
        raise ParseError("code_block truncated (code)", field_path=path)
    return CodeBlock(lang=lang, code=body.decode("utf-8"))


def _decode_ref(raw: bytes, path: str) -> RelayRef:
    if len(raw) < 21:
        raise ParseError("ref too short", field_path=path)
    sid = UUID(bytes=bytes(raw[0:16]))
    call_index = struct.unpack_from("<I", raw, 16)[0]
    rest = raw[20:]
    if not rest or rest[-1] != 0:
        raise ParseError("ref field_path must be null-terminated", field_path=path)
    fp = rest[:-1].decode("utf-8")
    return RelayRef(session_id=sid, call_index=call_index, field_path=fp)


def _decode_delta_op(raw: bytes, path: str) -> DeltaOp:
    if len(raw) < 2:
        raise ParseError("delta_op too short", field_path=path)
    opc = raw[0]
    op_type = _BYTE_TO_OP.get(opc)
    if op_type is None:
        raise ParseError(
            f"Unknown delta opcode {opc}",
            field_path=path,
        )
    nul = raw[1:].find(b"\x00")
    if nul < 0:
        raise ParseError("delta_op missing field_path terminator", field_path=path)
    fp = raw[1 : 1 + nul].decode("utf-8")
    pos = 1 + nul + 1
    if op_type == DeltaOpType.DEL:
        return DeltaOp(op_type=op_type, field_path=fp, type_tag=None, value=None)
    if op_type in (DeltaOpType.SET, DeltaOpType.APP):
        if len(raw) - pos < 5:
            raise ParseError("delta_op SET/APP truncated", field_path=path)
        tt = TypeTag(raw[pos])
        vl = struct.unpack_from("<I", raw, pos + 1)[0]
        pos += 5
        vb = raw[pos : pos + vl]
        if len(vb) != vl:
            raise ParseError("delta_op value truncated", field_path=path)
        val = _decode_delta_value(tt, vb)
        return DeltaOp(
            op_type=op_type,
            field_path=fp,
            type_tag=tt,
            value=val,
        )
    if op_type == DeltaOpType.SPL:
        if len(raw) - pos < 13:
            raise ParseError("delta_op SPL truncated", field_path=path)
        start, end = struct.unpack_from("<II", raw, pos)
        pos += 8
        tt = TypeTag(raw[pos])
        vl = struct.unpack_from("<I", raw, pos + 1)[0]
        pos += 5
        vb = raw[pos : pos + vl]
        if len(vb) != vl:
            raise ParseError("delta_op SPL value truncated", field_path=path)
        val = _decode_delta_value(tt, vb)
        return DeltaOp(
            op_type=op_type,
            field_path=fp,
            type_tag=tt,
            value=val,
            splice_start=start,
            splice_end=end,
        )
    raise ParseError("Unhandled delta op", field_path=path)  # pragma: no cover


def _decode_delta_value(tag: TypeTag, raw: bytes) -> Any:
    sf = SchemaField(
        name="_v",
        type_tag=tag,
        field_id=0,
        required=True,
        sub_fields=[],
        enum_values=[],
        vector_dtype=None,
        vector_dim=None,
        element_type_tag=None,
    )
    return _decode_value(raw, tag, sf, "__delta__")


def _decode_array(raw: bytes, sf: SchemaField, path: str) -> list[Any]:
    if len(raw) < 4:
        raise ParseError("array too short", field_path=path)
    count = struct.unpack_from("<I", raw, 0)[0]
    pos = 4
    out: list[Any] = []
    elem_tag = sf.element_type_tag
    if elem_tag is None:
        raise DecodingError("array missing element_type_tag in schema", field_path=path)
    for i in range(count):
        if len(raw) - pos < FIELD_HEADER_SIZE:
            raise ParseError(f"array element {i} header truncated", field_path=path)
        fid, tag, flen, pos2 = _read_field_header(raw, pos)
        pos = pos2
        if fid != 0:
            raise ParseError(
                "array element field id must be 0",
                details={"got": fid},
            )
        if TypeTag(tag) != elem_tag:
            raise TypeMismatchError(
                f"array element type mismatch at {path}[{i}]",
                field_path=f"{path}[{i}]",
            )
        vb = raw[pos : pos + flen]
        pos += flen
        sub = SchemaField(
            name="_e",
            type_tag=elem_tag,
            field_id=0,
            required=True,
            sub_fields=[],
            enum_values=sf.enum_values,
            vector_dtype=sf.vector_dtype,
            vector_dim=sf.vector_dim,
            element_type_tag=None,
        )
        out.append(_decode_value(vb, TypeTag(tag), sub, f"{path}[{i}]"))
    if pos != len(raw):
        raise ParseError("trailing bytes in array", field_path=path)
    return out


def _decode_object(raw: bytes, sf: SchemaField, path: str) -> list[RelayField]:
    by_name: dict[str, RelayField] = {}
    pos = 0
    while pos < len(raw):
        fid, tag, flen, pos2 = _read_field_header(raw, pos)
        pos = pos2
        vb = raw[pos : pos + flen]
        pos += flen
        sub = sf.sub_field_by_id(fid)
        if sub is None:
            raise TypeMismatchError(
                f"Unknown nested field id {fid} under {path}",
                field_path=path,
            )
        if int(tag) != int(sub.type_tag):
            raise TypeMismatchError(
                f"Nested type mismatch for {sub.name}",
                field_path=f"{path}.{sub.name}",
            )
        val = _decode_value(vb, TypeTag(tag), sub, f"{path}.{sub.name}")
        if sub.name in by_name:
            raise ParseError(
                "Duplicate nested field",
                details={"name": sub.name},
            )
        by_name[sub.name] = RelayField(fid, sub.name, TypeTag(tag), val)
    return [by_name[s.name] for s in sorted(sf.sub_fields, key=lambda x: x.field_id)]


__all__ = ["RelayStreamDecoder", "decode", "decode_stream"]
