"""
JSON compatibility layer for Relay.

Converts between plain JSON-compatible Python dicts and binary Relay messages.
No ``json.dumps`` is used internally; all encoding operates directly on Python
objects via the Relay encoder.

Functions
---------
from_json(data, schema) -> bytes
    Convert a JSON-compatible dict to binary Relay bytes.
to_json(data) -> dict
    Decode binary Relay bytes to a JSON-compatible Python dict.
_relay_to_json_value(type_tag, value) -> Any
    Internal helper — convert a single Relay-typed value to a JSON-safe type.
"""

from __future__ import annotations

import uuid as _uuid_mod
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from ..schema import RelaySchema

# ---------------------------------------------------------------------------
# Type-tag constants (mirrors relay.types.TypeTag enum values)
# Used here to avoid a hard import cycle during early bootstrapping.
# ---------------------------------------------------------------------------

_TAG_NULL = 0x01
_TAG_BOOL = 0x02
_TAG_INT8 = 0x03
_TAG_INT16 = 0x04
_TAG_INT32 = 0x05
_TAG_INT64 = 0x06
_TAG_UINT8 = 0x07
_TAG_UINT16 = 0x08
_TAG_UINT32 = 0x09
_TAG_UINT64 = 0x0A
_TAG_FLOAT32 = 0x0B
_TAG_FLOAT64 = 0x0C
_TAG_STRING = 0x0D
_TAG_BYTES = 0x0E
_TAG_ARRAY = 0x0F
_TAG_OBJECT = 0x10
_TAG_UUID = 0x11
_TAG_DATETIME = 0x12
_TAG_URI = 0x13
_TAG_VECTOR = 0x14
_TAG_ENUM = 0x15
_TAG_CODE_BLOCK = 0x16
_TAG_MARKDOWN_BLOCK = 0x17
_TAG_REF = 0x18
_TAG_DELTA_OP = 0x19

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def from_json(data: dict[str, Any], schema: RelaySchema) -> bytes:
    """Convert a JSON-compatible Python dict to binary Relay bytes.

    Inspects the schema to determine the Relay type for each field and then
    delegates to the Relay encoder.  JSON types are mapped to Relay types as
    follows:

    * ``str``   -> ``string`` (or ``uuid`` / ``uri`` / ``datetime`` when the
                   schema declares those types)
    * ``int``   -> narrowest signed integer type that fits, or ``int64``
    * ``float`` -> ``float64``
    * ``bool``  -> ``bool``
    * ``None``  -> ``null``
    * ``list``  -> ``array``
    * ``dict``  -> ``object``

    No ``json.dumps`` is called at any point.  The conversion operates
    directly on Python objects.

    Parameters
    ----------
    data : dict
        A JSON-compatible Python dict whose structure matches *schema*.
    schema : RelaySchema
        The Relay schema that governs this message.

    Returns
    -------
    bytes
        Binary Relay-encoded message.

    Raises
    ------
    relay.errors.TypeMismatchError
        If a field value cannot be coerced to the schema-declared type.
    relay.errors.SchemaNotFoundError
        If a required field declared in *schema* is absent from *data*.

    Examples
    --------
    >>> from relay.schema import RelaySchema
    >>> schema = RelaySchema.from_dict({"name": "example", "version": 1,
    ...     "fields": {"value": {"type": "int64", "required": True}}})
    >>> binary = from_json({"value": 42}, schema)
    >>> isinstance(binary, bytes)
    True
    """
    # Import here to avoid module-level circular imports.
    from ..encoder import encode

    return encode(data, schema)


def to_json(data: bytes) -> dict[str, Any]:
    """Decode binary Relay bytes into a JSON-compatible Python dict.

    All Relay semantic types are converted to their JSON-safe equivalents:

    * ``uuid``           -> ``str`` (canonical lowercase hyphenated form)
    * ``datetime``       -> ``str`` (ISO 8601, UTC, e.g. ``"2025-04-01T12:00:00Z"``)
    * ``uri``            -> ``str``
    * ``bytes``          -> ``str`` (hex-encoded)
    * ``vector``         -> ``list[float]``
    * ``enum``           -> ``str`` (the symbolic name from the schema)
    * ``code_block``     -> ``dict`` with keys ``"lang"`` and ``"code"``
    * ``markdown_block`` -> ``str``
    * ``ref``            -> ``str`` (the ``$ref`` expression)

    Parameters
    ----------
    data : bytes
        Binary Relay message, starting with the 12-byte frame header.

    Returns
    -------
    dict
        A plain Python dict whose values are JSON-serialisable.

    Raises
    ------
    relay.errors.ParseError
        If *data* is not a valid Relay binary message.
    relay.errors.DecodingError
        If the payload cannot be decoded according to the embedded schema.

    Examples
    --------
    >>> result = to_json(binary_relay_bytes)
    >>> isinstance(result, dict)
    True
    """
    from ..decoder import decode

    message = decode(data)
    return _message_to_json_dict(message)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _message_to_json_dict(message: Any) -> dict[str, Any]:
    """Convert a decoded RelayMessage to a JSON-safe dict.

    Parameters
    ----------
    message : RelayMessage
        Decoded message whose ``fields`` is a list of :class:`~relay.types.RelayField`.

    Returns
    -------
    dict
        Plain Python dict ready for ``json.dumps``.
    """
    from relay.types import RelayField

    result: dict[str, Any] = {}
    for field in message.fields:
        if not isinstance(field, RelayField):
            continue
        result[field.name] = _relay_to_json_value(int(field.type_tag), field.value)
    return result


def _relay_to_json_value(type_tag: int, value: Any) -> Any:
    """Convert a single Relay-typed value to a JSON-serialisable Python type.

    Parameters
    ----------
    type_tag : int
        The Relay type-tag byte (e.g. ``0x11`` for ``uuid``).
    value : Any
        The decoded Python value associated with *type_tag*.

    Returns
    -------
    Any
        A JSON-serialisable Python object: ``str``, ``int``, ``float``,
        ``bool``, ``None``, ``list``, or ``dict``.

    Raises
    ------
    relay.errors.DecodingError
        If *type_tag* is unknown or *value* cannot be converted.

    Examples
    --------
    >>> import uuid
    >>> _relay_to_json_value(0x11, uuid.UUID("550e8400-e29b-41d4-a716-446655440000"))
    '550e8400-e29b-41d4-a716-446655440000'
    >>> _relay_to_json_value(0x02, True)
    True
    >>> _relay_to_json_value(0x0E, b"\\xff\\xfe")
    'fffe'
    """
    from ..errors import DecodingError

    if type_tag == _TAG_NULL:
        return None

    if type_tag == _TAG_BOOL:
        return bool(value)

    if type_tag in (
        _TAG_INT8,
        _TAG_INT16,
        _TAG_INT32,
        _TAG_INT64,
        _TAG_UINT8,
        _TAG_UINT16,
        _TAG_UINT32,
        _TAG_UINT64,
    ):
        return int(value)

    if type_tag in (_TAG_FLOAT32, _TAG_FLOAT64):
        return float(value)

    if type_tag == _TAG_STRING:
        return str(value)

    if type_tag == _TAG_BYTES:
        # Hex-encode binary blobs so they survive JSON serialisation.
        if isinstance(value, (bytes, bytearray, memoryview)):
            return bytes(value).hex()
        return str(value)

    if type_tag == _TAG_UUID:
        if isinstance(value, _uuid_mod.UUID):
            return str(value)
        return str(value)

    if type_tag == _TAG_DATETIME:
        if isinstance(value, datetime):
            # Normalise to UTC and emit ISO 8601 with Z suffix.
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        # Value may be raw microseconds since epoch (int).
        if isinstance(value, (int, float)):
            dt = datetime.fromtimestamp(value / 1_000_000, tz=timezone.utc)
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        return str(value)

    if type_tag == _TAG_URI:
        return str(value)

    if type_tag == _TAG_VECTOR:
        # value is expected to be a numpy array or list of numbers.
        try:
            return [float(x) for x in value]
        except TypeError:
            return list(value)

    if type_tag == _TAG_ENUM:
        from relay.types import EnumValue

        if isinstance(value, EnumValue):
            return value.name
        return str(value)

    if type_tag == _TAG_CODE_BLOCK:
        if isinstance(value, dict):
            return {"lang": value.get("lang", ""), "code": value.get("code", "")}
        return str(value)

    if type_tag == _TAG_MARKDOWN_BLOCK:
        return str(value)

    if type_tag == _TAG_REF:
        return str(value)

    if type_tag == _TAG_ARRAY:
        # value is a list of (type_tag, item_value) tuples from the decoder.
        if isinstance(value, list):
            result = []
            for item in value:
                if isinstance(item, tuple) and len(item) == 2:
                    result.append(_relay_to_json_value(item[0], item[1]))
                else:
                    result.append(item)
            return result
        return list(value)

    if type_tag == _TAG_OBJECT:
        from relay.types import RelayField

        if isinstance(value, list):
            merged: dict[str, Any] = {}
            for ch in value:
                if isinstance(ch, RelayField):
                    merged[ch.name] = _relay_to_json_value(int(ch.type_tag), ch.value)
            return merged
        if isinstance(value, dict):
            return {
                k: (_relay_to_json_value(v[0], v[1]) if isinstance(v, tuple) and len(v) == 2 else v)
                for k, v in value.items()
            }
        return value

    if type_tag == _TAG_DELTA_OP:
        # Represent delta ops as a descriptive dict.
        if isinstance(value, dict):
            return value
        return str(value)

    raise DecodingError(
        f"Unknown type_tag 0x{type_tag:02X} encountered during JSON conversion",
        details={"type_tag": hex(type_tag)},
    )


__all__ = [
    "_relay_to_json_value",
    "from_json",
    "to_json",
]
