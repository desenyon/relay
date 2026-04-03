"""
DELTA message construction and application.

A DELTA frame references a base FULL message and carries a sequence of
mutation operations (SET, DEL, APP, SPL).
"""

from __future__ import annotations

from typing import Any

from relay.decoder import decode
from relay.encoder import (
    _build_frame,
    _encode_delta_op_bytes,
    _encode_ref_bytes,
    _pack_field_frame,
    encode,
)
from relay.errors import DeltaConflictError, EncodingError, ValidationError
from relay.registry import get_default_registry
from relay.schema import RelaySchema as SourceSchema
from relay.schema_compile import compile_schema
from relay.types import (
    DeltaOp,
    DeltaOpType,
    MessageType,
    RelayField,
    RelayMessage,
    TypeTag,
)


def delta(
    base: RelayMessage,
    operations: list[DeltaOp],
    schema: SourceSchema | None = None,
) -> bytes:
    """Encode a DELTA message as binary bytes.

    Parameters
    ----------
    base : RelayMessage
        Provides ``schema_hash`` (unless *schema* is given) and
        ``delta_base_ref`` (the ``__base__`` pointer).
    operations : list of DeltaOp
        Mutations to encode into the frame.
    schema : relay.schema.RelaySchema, optional
        If omitted, *base*\\ `.schema_hash` is resolved via the default registry.

    Returns
    -------
    bytes

    Raises
    ------
    EncodingError
        If ``delta_base_ref`` is missing or the frame cannot be built.
    relay.errors.SchemaNotFoundError
        If *schema* is omitted and the hash is unknown.
    """
    if base.delta_base_ref is None:
        raise EncodingError(
            "RelayMessage.delta_base_ref must be set to encode a DELTA frame",
            details={"hint": "Assign a RelayRef pointing at the base FULL message"},
        )
    src = schema
    if src is None:
        src = get_default_registry().get_by_hash(base.schema_hash.hex())
    compiled = compile_schema(src)
    ref_body = _encode_ref_bytes(base.delta_base_ref)
    parts = [_pack_field_frame(0, int(TypeTag.REF), ref_body)]
    for i, op in enumerate(operations, start=1):
        body = _encode_delta_op_bytes(op)
        parts.append(_pack_field_frame(i, int(TypeTag.DELTA_OP), body))
    payload = b"".join(parts)
    return _build_frame(MessageType.DELTA, compiled.schema_hash, payload)


def apply_delta(
    base: RelayMessage,
    delta_msg: RelayMessage,
    schema: SourceSchema | None = None,
) -> RelayMessage:
    """Apply *delta_msg* on top of *base* and return a new FULL message.

    Parameters
    ----------
    base : RelayMessage
        A decoded FULL message.
    delta_msg : RelayMessage
        A decoded DELTA message whose payload includes ``__base__`` and ops.
    schema : relay.schema.RelaySchema, optional
        Source schema for re-encoding; resolved from registry if omitted.

    Returns
    -------
    RelayMessage
        A decoded FULL message (round-tripped through encode/decode).

    Raises
    ------
    ValidationError
        If message types are wrong.
    DeltaConflictError
        If a SPL/APP operation is inconsistent with the current value.
    """
    if base.message_type != MessageType.FULL:
        raise ValidationError(
            "apply_delta base must be a FULL message",
            details={"got": base.message_type.name},
        )
    if delta_msg.message_type != MessageType.DELTA:
        raise ValidationError(
            "apply_delta expects a DELTA message",
            details={"got": delta_msg.message_type.name},
        )

    plain = _message_to_plain(base)
    ops: list[DeltaOp] = []
    for f in delta_msg.fields:
        if f.name == "__base__" or f.field_id == 0:
            continue
        if f.type_tag == TypeTag.DELTA_OP and isinstance(f.value, DeltaOp):
            ops.append(f.value)

    for op in ops:
        _apply_one_op(plain, op)

    src = schema
    if src is None:
        src = get_default_registry().get_by_hash(base.schema_hash.hex())
    data = encode(plain, src)
    return decode(data, schema=src, validate=True)


def _message_to_plain(msg: RelayMessage) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for f in msg.fields:
        out[f.name] = _field_to_plain(f)
    return out


def _field_to_plain(f: RelayField) -> Any:
    if f.type_tag == TypeTag.OBJECT and isinstance(f.value, list):
        d: dict[str, Any] = {}
        for ch in f.value:
            if isinstance(ch, RelayField):
                d[ch.name] = _field_to_plain(ch)
        return d
    if f.type_tag == TypeTag.ARRAY and isinstance(f.value, list):
        return list(f.value)
    return f.value


def _apply_one_op(plain: dict[str, Any], op: DeltaOp) -> None:
    parts = op.field_path.split(".")
    target = plain
    for p in parts[:-1]:
        if p not in target or not isinstance(target[p], dict):
            raise DeltaConflictError(
                f"Cannot navigate path {op.field_path!r}",
                field_path=op.field_path,
            )
        target = target[p]
    key = parts[-1]

    if op.op_type == DeltaOpType.SET:
        target[key] = op.value
    elif op.op_type == DeltaOpType.DEL:
        if key in target:
            del target[key]
    elif op.op_type == DeltaOpType.APP:
        if key not in target:
            target[key] = []
        if not isinstance(target[key], list):
            raise DeltaConflictError(
                "APP target is not a list",
                field_path=op.field_path,
            )
        target[key].append(op.value)
    elif op.op_type == DeltaOpType.SPL:
        if op.splice_start is None or op.splice_end is None:
            raise DeltaConflictError("SPL missing bounds", field_path=op.field_path)
        if key not in target or not isinstance(target[key], list):
            raise DeltaConflictError(
                "SPL target is not a list",
                field_path=op.field_path,
            )
        arr = target[key]
        start, end = op.splice_start, op.splice_end
        if end < start or start < 0 or end > len(arr):
            raise DeltaConflictError(
                "SPL range invalid",
                field_path=op.field_path,
                details={"start": start, "end": end, "len": len(arr)},
            )
        replacement = [] if op.value is None else [op.value]
        arr[start:end] = replacement
    else:
        raise DeltaConflictError(
            f"Unknown op {op.op_type!r}",
            field_path=op.field_path,
        )


__all__ = ["apply_delta", "delta"]
