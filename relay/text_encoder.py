"""
Relay text-format encoder.

Converts Python objects and :class:`~relay.types.RelayMessage` instances to the
canonical ``.relay`` text encoding — the human-readable, LLM-emittable
representation of a Relay message.

The text encoding is semantically identical to the binary wire format and can
be round-tripped through :mod:`relay.text_decoder` without any data loss.

Public API
----------
encode_text(obj, schema, message_type=MessageType.FULL) -> str
    Module-level convenience function.

RelayTextEncoder
    Stateful encoder class.

Examples
--------
>>> from relay.schema import RelaySchema
>>> from relay.text_encoder import encode_text
>>> schema = RelaySchema.from_dict({
...     "name": "ping", "version": 1,
...     "fields": [{"name": "msg", "type": "string", "required": True}],
...     "enums": {},
... })
>>> text = encode_text({"msg": "hello"}, schema)
>>> text.startswith("@relay 1.0")
True
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from .errors import EncodingError, TypeMismatchError
from .schema import RelaySchema, SchemaField
from .types import (
    VECTOR_DTYPE_TO_NUMPY,
    CodeBlock,
    DeltaOp,
    DeltaOpType,
    EnumValue,
    MarkdownBlock,
    MessageType,
    RelayRef,
    TypeTag,
    VectorValue,
)

# ---------------------------------------------------------------------------
# Type-name → TypeTag mapping (for field-type-string interpretation)
# ---------------------------------------------------------------------------

_SIMPLE_TYPE_MAP: dict[str, TypeTag] = {
    "null": TypeTag.NULL,
    "bool": TypeTag.BOOL,
    "int8": TypeTag.INT8,
    "int16": TypeTag.INT16,
    "int32": TypeTag.INT32,
    "int64": TypeTag.INT64,
    "uint8": TypeTag.UINT8,
    "uint16": TypeTag.UINT16,
    "uint32": TypeTag.UINT32,
    "uint64": TypeTag.UINT64,
    "float32": TypeTag.FLOAT32,
    "float64": TypeTag.FLOAT64,
    "string": TypeTag.STRING,
    "bytes": TypeTag.BYTES,
    "array": TypeTag.ARRAY,
    "object": TypeTag.OBJECT,
    "uuid": TypeTag.UUID,
    "datetime": TypeTag.DATETIME,
    "uri": TypeTag.URI,
    "vector": TypeTag.VECTOR,
    "enum": TypeTag.ENUM,
    "code_block": TypeTag.CODE_BLOCK,
    "markdown_block": TypeTag.MARKDOWN_BLOCK,
    "ref": TypeTag.REF,
}


def _type_name_to_tag(type_name: str) -> TypeTag:
    """Resolve a schema type name string to a ``TypeTag``.

    Parameters
    ----------
    type_name : str
        Raw type string from the schema, e.g. ``"string"``, ``"float64"``,
        ``"enum<MessageRole>"``, ``"vector<float64, 5>"``, ``"object"``.

    Returns
    -------
    TypeTag

    Raises
    ------
    EncodingError
        If the type name cannot be resolved.
    """
    if type_name in _SIMPLE_TYPE_MAP:
        return _SIMPLE_TYPE_MAP[type_name]
    if type_name.startswith("enum<"):
        return TypeTag.ENUM
    if type_name.startswith("vector<"):
        return TypeTag.VECTOR
    if type_name.startswith("code_block<"):
        return TypeTag.CODE_BLOCK
    raise EncodingError(
        f"Unknown schema type name: {type_name!r}",
        details={"type_name": type_name},
    )


# ---------------------------------------------------------------------------
# RelayTextEncoder
# ---------------------------------------------------------------------------


class RelayTextEncoder:
    """Encodes Python dicts and :class:`~relay.types.RelayMessage` objects to
    the ``.relay`` text format.

    Parameters
    ----------
    schema : RelaySchema
        The schema describing field names and types.

    Examples
    --------
    >>> from relay.schema import RelaySchema
    >>> from relay.text_encoder import RelayTextEncoder
    >>> schema = RelaySchema.from_dict({
    ...     "name": "ping", "version": 1,
    ...     "fields": [{"name": "msg", "type": "string", "required": True}],
    ...     "enums": {},
    ... })
    >>> enc = RelayTextEncoder(schema)
    >>> text = enc.encode_text({"msg": "hello"})
    >>> "@relay 1.0" in text
    True
    >>> 'msg: string "hello"' in text
    True
    """

    def __init__(self, schema: RelaySchema) -> None:
        self._schema = schema

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    def encode_text(
        self,
        obj: dict[str, Any],
        message_type: MessageType = MessageType.FULL,
    ) -> str:
        """Encode a Python dict to the ``.relay`` text format.

        Parameters
        ----------
        obj : dict
            The message payload.  Keys must correspond to field names defined
            in the schema.
        message_type : MessageType, optional
            The message type tag to emit.  Defaults to ``FULL``.

        Returns
        -------
        str
            A complete ``.relay`` text representation, including the
            ``@relay``, ``@schema``, and ``@type`` header lines.

        Raises
        ------
        EncodingError
            If a field value cannot be converted to text.
        TypeMismatchError
            If a field value does not match the schema-declared type.

        Examples
        --------
        >>> from relay.schema import RelaySchema
        >>> schema = RelaySchema.from_dict({
        ...     "name": "ex", "version": 1,
        ...     "fields": [{"name": "x", "type": "int32", "required": True}],
        ...     "enums": {},
        ... })
        >>> from relay.text_encoder import RelayTextEncoder
        >>> enc = RelayTextEncoder(schema)
        >>> "@type FULL" in enc.encode_text({"x": 42})
        True
        """
        lines: list[str] = []
        lines.append("@relay 1.0")
        lines.append(f"@schema {self._schema.name}:{self._schema.hash()}")
        lines.append(f"@type {message_type.name}")
        lines.append("")

        for schema_field in self._schema.fields:
            name = schema_field.name
            if name not in obj:
                if schema_field.required:
                    raise EncodingError(
                        f"Required field '{name}' is missing from the input dict",
                        field_path=name,
                        details={"field": name},
                    )
                continue
            value = obj[name]
            field_lines = self._encode_field_text(
                name, schema_field.type_name, value, schema_field, indent=0
            )
            lines.extend(field_lines)

        return "\n".join(lines) + "\n"

    def encode_delta_text(
        self,
        ops: list[DeltaOp],
        base_ref: RelayRef,
    ) -> str:
        """Encode a list of delta operations to the ``.relay`` DELTA text format.

        Parameters
        ----------
        ops : list of DeltaOp
            The ordered mutation operations.
        base_ref : RelayRef
            Reference to the base message this delta applies over.

        Returns
        -------
        str
            A complete ``.relay`` DELTA text representation.

        Raises
        ------
        EncodingError
            If an operation value cannot be encoded to text.

        Examples
        --------
        >>> from relay.types import DeltaOp, DeltaOpType, TypeTag, RelayRef
        >>> from relay.schema import RelaySchema
        >>> from uuid import UUID
        >>> schema = RelaySchema.from_dict({"name": "x", "version": 1,
        ...     "fields": [], "enums": {}})
        >>> from relay.text_encoder import RelayTextEncoder
        >>> enc = RelayTextEncoder(schema)
        >>> ref = RelayRef(UUID("550e8400-e29b-41d4-a716-446655440000"), 2, "")
        >>> ops = [DeltaOp(DeltaOpType.SET, "rate", TypeTag.FLOAT64, 0.10)]
        >>> text = enc.encode_delta_text(ops, ref)
        >>> "@type DELTA" in text
        True
        """
        lines: list[str] = []
        lines.append("@relay 1.0")
        lines.append(f"@schema {self._schema.name}:{self._schema.hash()}")
        lines.append("@type DELTA")
        # Format base ref
        sid = str(base_ref.session_id)
        lines.append(f"@base $ref session:{sid}.call[{base_ref.call_index}]")
        lines.append("")

        for op in ops:
            lines.extend(self._encode_delta_op_text(op))

        return "\n".join(lines) + "\n"

    # ------------------------------------------------------------------
    # Field encoding
    # ------------------------------------------------------------------

    def _encode_field_text(
        self,
        name: str,
        type_name: str,
        value: Any,
        schema_field: SchemaField | None,
        indent: int,
    ) -> list[str]:
        """Encode a single field to a list of text lines.

        Parameters
        ----------
        name : str
            Field name.
        type_name : str
            Schema type string for this field.
        value : Any
            Python value to encode.
        schema_field : SchemaField or None
            Schema field definition (provides nested field info).
        indent : int
            Number of 2-space indentation levels.

        Returns
        -------
        list of str
            Lines representing this field (no trailing newline per line).

        Raises
        ------
        EncodingError
            On unrecognised types or encoding failures.
        TypeMismatchError
            On type mismatches.
        """
        pad = "  " * indent

        # -- null --
        if type_name == "null" or value is None:
            return [f"{pad}{name}: null"]

        # -- bool --
        if type_name == "bool":
            if not isinstance(value, bool):
                raise TypeMismatchError(
                    f"Field '{name}' expects bool, got {type(value).__name__}",
                    field_path=name,
                    details={"expected": "bool", "got": type(value).__name__},
                )
            return [f"{pad}{name}: bool {'true' if value else 'false'}"]

        # -- integer types --
        if type_name in ("int8", "int16", "int32", "int64",
                         "uint8", "uint16", "uint32", "uint64"):
            if not isinstance(value, int) or isinstance(value, bool):
                raise TypeMismatchError(
                    f"Field '{name}' expects {type_name}, got {type(value).__name__}",
                    field_path=name,
                    details={"expected": type_name, "got": type(value).__name__},
                )
            return [f"{pad}{name}: {type_name} {value}"]

        # -- float types --
        if type_name in ("float32", "float64"):
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise TypeMismatchError(
                    f"Field '{name}' expects {type_name}, got {type(value).__name__}",
                    field_path=name,
                    details={"expected": type_name, "got": type(value).__name__},
                )
            return [f"{pad}{name}: {type_name} {_format_float(value)}"]

        # -- string --
        if type_name == "string":
            if not isinstance(value, str):
                raise TypeMismatchError(
                    f"Field '{name}' expects string, got {type(value).__name__}",
                    field_path=name,
                    details={"expected": "string", "got": type(value).__name__},
                )
            return [f'{pad}{name}: string {_quote_string(value)}']

        # -- bytes --
        if type_name == "bytes":
            if isinstance(value, (bytes, bytearray)):
                hex_str = value.hex()
            elif isinstance(value, str):
                hex_str = value  # assume already hex
            else:
                raise TypeMismatchError(
                    f"Field '{name}' expects bytes, got {type(value).__name__}",
                    field_path=name,
                    details={"expected": "bytes", "got": type(value).__name__},
                )
            return [f"{pad}{name}: bytes 0x{hex_str}"]

        # -- uuid --
        if type_name == "uuid":
            if isinstance(value, UUID):
                uuid_str = str(value)
            elif isinstance(value, str):
                uuid_str = value
            else:
                raise TypeMismatchError(
                    f"Field '{name}' expects uuid, got {type(value).__name__}",
                    field_path=name,
                    details={"expected": "uuid", "got": type(value).__name__},
                )
            return [f'{pad}{name}: uuid "{uuid_str}"']

        # -- datetime --
        if type_name == "datetime":
            if isinstance(value, datetime):
                iso = value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            elif isinstance(value, (int, float)):
                # Stored as microseconds since epoch
                dt = datetime.fromtimestamp(value / 1_000_000, tz=timezone.utc)
                iso = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            elif isinstance(value, str):
                iso = value
            else:
                raise TypeMismatchError(
                    f"Field '{name}' expects datetime, got {type(value).__name__}",
                    field_path=name,
                    details={"expected": "datetime", "got": type(value).__name__},
                )
            return [f'{pad}{name}: datetime "{iso}"']

        # -- uri --
        if type_name == "uri":
            if not isinstance(value, str):
                raise TypeMismatchError(
                    f"Field '{name}' expects uri (string), got {type(value).__name__}",
                    field_path=name,
                    details={"expected": "uri", "got": type(value).__name__},
                )
            return [f'{pad}{name}: uri "{value}"']

        # -- enum<Name> --
        if type_name.startswith("enum<") and type_name.endswith(">"):
            enum_name = type_name[5:-1]
            if isinstance(value, EnumValue):
                val_name = value.name
            elif isinstance(value, str):
                val_name = value
            elif isinstance(value, int):
                # Resolve index → name via schema
                val_name = self._schema.get_enum_name(enum_name, value)
            else:
                raise TypeMismatchError(
                    f"Field '{name}' expects enum<{enum_name}>, got {type(value).__name__}",
                    field_path=name,
                    details={"expected": f"enum<{enum_name}>", "got": type(value).__name__},
                )
            return [f"{pad}{name}: enum<{enum_name}>.{val_name}"]

        # -- vector<dtype, dim> --
        if type_name.startswith("vector<") and type_name.endswith(">"):
            inner = type_name[7:-1]
            parts = [p.strip() for p in inner.split(",")]
            dtype_str = parts[0] if parts else "float64"
            if isinstance(value, VectorValue):
                nums = value.data.tolist()
                dtype_str = VECTOR_DTYPE_TO_NUMPY.get(value.dtype, dtype_str)
                dim = value.dim
            elif isinstance(value, (list, tuple)):
                nums = list(value)
                dim = len(nums)
            else:
                raise TypeMismatchError(
                    f"Field '{name}' expects vector, got {type(value).__name__}",
                    field_path=name,
                    details={"expected": type_name, "got": type(value).__name__},
                )
            nums_str = "[" + ", ".join(_format_float(n) for n in nums) + "]"
            return [f"{pad}{name}: vector<{dtype_str}, {dim}> {nums_str}"]

        # -- code_block or code_block<lang> --
        if type_name == "code_block" or type_name.startswith("code_block<"):
            if isinstance(value, CodeBlock):
                lang, code = value.lang, value.code
            elif isinstance(value, dict):
                lang = value.get("lang", "")
                code = value.get("code", "")
            else:
                raise TypeMismatchError(
                    f"Field '{name}' expects code_block, got {type(value).__name__}",
                    field_path=name,
                    details={"expected": "code_block", "got": type(value).__name__},
                )
            result = [f"{pad}{name}: code_block<{lang}>"]
            result.append(f"{pad}  ```")
            for code_line in code.splitlines():
                result.append(f"{pad}  {code_line}")
            result.append(f"{pad}  ```")
            return result

        # -- markdown_block --
        if type_name == "markdown_block":
            if isinstance(value, MarkdownBlock):
                text_content = value.content
            elif isinstance(value, str):
                text_content = value
            else:
                raise TypeMismatchError(
                    f"Field '{name}' expects markdown_block, got {type(value).__name__}",
                    field_path=name,
                    details={"expected": "markdown_block", "got": type(value).__name__},
                )
            result = [f"{pad}{name}: markdown_block"]
            result.append(f'{pad}  """')
            for md_line in text_content.splitlines():
                result.append(f"{pad}  {md_line}")
            result.append(f'{pad}  """')
            return result

        # -- object --
        if type_name == "object":
            if not isinstance(value, (dict, list)):
                raise TypeMismatchError(
                    f"Field '{name}' expects object (dict), got {type(value).__name__}",
                    field_path=name,
                    details={"expected": "object", "got": type(value).__name__},
                )
            # If the value is a list of RelayField, convert to dict first
            if isinstance(value, list):
                value_dict = {f.name: f.value for f in value if hasattr(f, "name")}
            else:
                value_dict = value

            result = [f"{pad}{name}: object"]
            nested_schema_fields: dict[str, SchemaField] = {}
            if schema_field is not None:
                for nf in schema_field.nested_fields:
                    nested_schema_fields[nf.name] = nf

            for child_name, child_val in value_dict.items():
                child_schema_field = nested_schema_fields.get(child_name)
                child_type = (
                    child_schema_field.type_name if child_schema_field else _infer_type(child_val)
                )
                child_lines = self._encode_field_text(
                    child_name, child_type, child_val,
                    child_schema_field, indent + 1
                )
                result.extend(child_lines)
            return result

        # -- array<inner> (homogeneous; matches schema_compile array<T> syntax) --
        am = re.match(r"^array<(.+)>$", type_name.strip(), re.IGNORECASE)
        if am:
            inner = am.group(1).strip()
            if not isinstance(value, (list, tuple)):
                raise TypeMismatchError(
                    f"Field '{name}' expects array (list), got {type(value).__name__}",
                    field_path=name,
                    details={"expected": f"array<{inner}>", "got": type(value).__name__},
                )
            result = [f"{pad}{name}: array<{inner}>"]
            for idx, item in enumerate(value):
                child_lines = self._encode_field_text(
                    f"[{idx}]",
                    inner,
                    item,
                    None,
                    indent + 1,
                )
                result.extend(child_lines)
            return result

        # -- array (heterogeneous via _infer_type per element) --
        if type_name == "array":
            if not isinstance(value, (list, tuple)):
                raise TypeMismatchError(
                    f"Field '{name}' expects array (list), got {type(value).__name__}",
                    field_path=name,
                    details={"expected": "array", "got": type(value).__name__},
                )
            result = [f"{pad}{name}: array"]
            for idx, item in enumerate(value):
                item_type = _infer_type(item)
                child_lines = self._encode_field_text(
                    f"[{idx}]", item_type, item, None, indent + 1
                )
                result.extend(child_lines)
            return result

        # -- ref --
        if type_name == "ref":
            if isinstance(value, RelayRef):
                sid = str(value.session_id)
                path_part = f".{value.field_path}" if value.field_path else ""
                ref_str = f"$ref session:{sid}.call[{value.call_index}]{path_part}"
            elif isinstance(value, str):
                ref_str = value
            else:
                raise TypeMismatchError(
                    f"Field '{name}' expects ref, got {type(value).__name__}",
                    field_path=name,
                    details={"expected": "ref", "got": type(value).__name__},
                )
            return [f"{pad}{name}: ref {ref_str}"]

        raise EncodingError(
            f"Cannot encode field '{name}' with unrecognised type '{type_name}'",
            field_path=name,
            details={"type_name": type_name},
        )

    # ------------------------------------------------------------------
    # Delta operation encoding
    # ------------------------------------------------------------------

    def _encode_delta_op_text(self, op: DeltaOp) -> list[str]:
        """Encode a single ``DeltaOp`` to a list of text lines.

        Parameters
        ----------
        op : DeltaOp
            The delta operation to encode.

        Returns
        -------
        list of str

        Raises
        ------
        EncodingError
            If the operation value cannot be encoded.
        """
        if op.op_type == DeltaOpType.DEL:
            return [f"DEL  {op.field_path}"]

        type_name = _type_tag_to_name(op.type_tag) if op.type_tag else "string"
        value_str = _encode_value_inline(type_name, op.value)

        if op.op_type == DeltaOpType.SET:
            return [f"SET  {op.field_path} {type_name} {value_str}"]
        if op.op_type == DeltaOpType.APP:
            return [f"APP  {op.field_path} {type_name} {value_str}"]
        if op.op_type == DeltaOpType.SPL:
            start = op.splice_start if op.splice_start is not None else 0
            end = op.splice_end if op.splice_end is not None else 0
            return [f"SPL  {op.field_path} {start} {end} {type_name} {value_str}"]

        raise EncodingError(
            f"Unknown delta op type: {op.op_type!r}",
            details={"op_type": str(op.op_type)},
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _format_float(value: float | int) -> str:
    """Format a numeric value for text output.

    Always emits at least one decimal place so the type is unambiguous.

    Parameters
    ----------
    value : float or int

    Returns
    -------
    str

    Examples
    --------
    >>> _format_float(0.08)
    '0.08'
    >>> _format_float(1)
    '1.0'
    """
    f = float(value)
    s = repr(f)
    # Ensure a decimal point is present
    if "." not in s and "e" not in s:
        s = s + ".0"
    return s


def _quote_string(s: str) -> str:
    """Wrap a string in double quotes, escaping internal double quotes and backslashes.

    Parameters
    ----------
    s : str

    Returns
    -------
    str

    Examples
    --------
    >>> _quote_string('hello "world"')
    '"hello \\\\"world\\\\""'
    """
    escaped = s.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _infer_type(value: Any) -> str:
    """Best-effort inference of a Relay type name from a Python value.

    Parameters
    ----------
    value : Any

    Returns
    -------
    str
        A Relay type name string.
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int64"
    if isinstance(value, float):
        return "float64"
    if isinstance(value, str):
        return "string"
    if isinstance(value, bytes):
        return "bytes"
    if isinstance(value, UUID):
        return "uuid"
    if isinstance(value, datetime):
        return "datetime"
    if isinstance(value, VectorValue):
        dtype_name = VECTOR_DTYPE_TO_NUMPY.get(value.dtype, "float64")
        return f"vector<{dtype_name}, {value.dim}>"
    if isinstance(value, CodeBlock):
        return f"code_block<{value.lang}>"
    if isinstance(value, MarkdownBlock):
        return "markdown_block"
    if isinstance(value, EnumValue):
        return "enum"
    if isinstance(value, RelayRef):
        return "ref"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, (list, tuple)):
        return "array"
    return "string"


def _type_tag_to_name(tag: TypeTag) -> str:
    """Convert a ``TypeTag`` enum member to its text-format name string.

    Parameters
    ----------
    tag : TypeTag

    Returns
    -------
    str

    Examples
    --------
    >>> _type_tag_to_name(TypeTag.FLOAT64)
    'float64'
    """
    return tag.name.lower()


def _encode_value_inline(type_name: str, value: Any) -> str:
    """Encode a scalar value as a single inline text token.

    Parameters
    ----------
    type_name : str
        Relay type name.
    value : Any
        Python value.

    Returns
    -------
    str

    Examples
    --------
    >>> _encode_value_inline("float64", 0.10)
    '0.1'
    >>> _encode_value_inline("string", "hello")
    '"hello"'
    """
    if value is None:
        return "null"
    if type_name == "bool":
        return "true" if value else "false"
    if type_name in ("int8", "int16", "int32", "int64",
                     "uint8", "uint16", "uint32", "uint64"):
        return str(int(value))
    if type_name in ("float32", "float64"):
        return _format_float(value)
    if type_name == "string":
        return _quote_string(str(value))
    if type_name == "uuid":
        return f'"{value}"'
    if type_name == "datetime":
        if isinstance(value, datetime):
            return f'"{value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}"'
        return f'"{value}"'
    if type_name == "uri":
        return f'"{value}"'
    if type_name.startswith("enum<"):
        if isinstance(value, EnumValue):
            return f"enum<{value.name}>.{value.name}"
        return str(value)
    if type_name.startswith("vector<"):
        if isinstance(value, VectorValue):
            nums = value.data.tolist()
        else:
            nums = list(value)
        return "[" + ", ".join(_format_float(n) for n in nums) + "]"
    return _quote_string(str(value))


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------


def encode_text(
    obj: dict[str, Any],
    schema: RelaySchema,
    message_type: MessageType = MessageType.FULL,
) -> str:
    """Encode a Python dict to the Relay text format.

    Parameters
    ----------
    obj : dict
        The message payload.  Keys must correspond to field names declared in
        *schema*.
    schema : RelaySchema
        The schema governing field names and types.
    message_type : MessageType, optional
        The message type to emit.  Defaults to ``MessageType.FULL``.

    Returns
    -------
    str
        The complete ``.relay`` text representation.

    Raises
    ------
    EncodingError
        If any field value cannot be converted.
    TypeMismatchError
        If a value does not match the schema-declared type.

    Examples
    --------
    >>> from relay.schema import RelaySchema
    >>> schema = RelaySchema.from_dict({
    ...     "name": "ex", "version": 1,
    ...     "fields": [{"name": "n", "type": "int32", "required": True}],
    ...     "enums": {},
    ... })
    >>> text = encode_text({"n": 7}, schema)
    >>> "n: int32 7" in text
    True
    """
    encoder = RelayTextEncoder(schema)
    return encoder.encode_text(obj, message_type=message_type)


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

__all__ = [
    "RelayTextEncoder",
    "encode_text",
]
