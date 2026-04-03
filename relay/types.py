"""
All Relay primitive types, message structures, and supporting dataclasses.

This module defines the complete type system used throughout the Relay runtime.
Every value that flows through encoding, decoding, schema validation, delta
application, and reference resolution is represented by one of the types here.

Constants
---------
MAGIC : int
    Frame magic byte (0xDE / 222).
VERSION : int
    Current wire-format version byte (0x01).
FRAME_HEADER_SIZE : int
    Fixed size of the 12-byte frame header.
FIELD_HEADER_SIZE : int
    Fixed size of the 7-byte per-field header.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Any
from uuid import UUID

import numpy as np

# ---------------------------------------------------------------------------
# Wire-format constants
# ---------------------------------------------------------------------------

MAGIC: int = 0xDE  # 222 decimal
VERSION: int = 0x01
FRAME_HEADER_SIZE: int = 12  # magic(1) + version(1) + msg_type(2) + schema_hash(4) + payload_len(4)
FIELD_HEADER_SIZE: int = 7  # field_id(2) + type_tag(1) + field_len(4)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class TypeTag(IntEnum):
    """Wire-level type tag byte values used in Relay field frames.

    Each value corresponds to the ``Type tag`` byte in the field frame header
    as defined in the Relay wire-format specification.

    Examples
    --------
    >>> TypeTag.STRING
    <TypeTag.STRING: 13>
    >>> hex(TypeTag.UUID)
    '0x11'
    """

    NULL = 0x01
    BOOL = 0x02
    INT8 = 0x03
    INT16 = 0x04
    INT32 = 0x05
    INT64 = 0x06
    UINT8 = 0x07
    UINT16 = 0x08
    UINT32 = 0x09
    UINT64 = 0x0A
    FLOAT32 = 0x0B
    FLOAT64 = 0x0C
    STRING = 0x0D
    BYTES = 0x0E
    ARRAY = 0x0F
    OBJECT = 0x10
    UUID = 0x11
    DATETIME = 0x12
    URI = 0x13
    VECTOR = 0x14
    ENUM = 0x15
    CODE_BLOCK = 0x16
    MARKDOWN_BLOCK = 0x17
    REF = 0x18
    DELTA_OP = 0x19


class MessageType(IntEnum):
    """Relay message-type codes stored in bytes 2-3 of the frame header.

    Examples
    --------
    >>> MessageType.FULL
    <MessageType.FULL: 1>
    >>> MessageType(0x0002)
    <MessageType.DELTA: 2>
    """

    FULL = 0x0001
    DELTA = 0x0002
    REF_ONLY = 0x0003
    SCHEMA_DEF = 0x0004
    ERROR = 0x0005


class VectorDtype(IntEnum):
    """Sub-type tag for the ``vector`` semantic type.

    Stored in the first 4 bytes of a vector field value, immediately after the
    ``TypeTag.VECTOR`` byte in the field frame.

    Examples
    --------
    >>> VectorDtype.FLOAT32
    <VectorDtype.FLOAT32: 2>
    """

    FLOAT16 = 0x01
    FLOAT32 = 0x02
    FLOAT64 = 0x03
    INT8 = 0x04


class DeltaOpType(str, Enum):
    """Operation types for Relay DELTA messages.

    Examples
    --------
    >>> DeltaOpType.SET
    <DeltaOpType.SET: 'SET'>
    >>> DeltaOpType("DEL")
    <DeltaOpType.DEL: 'DEL'>
    """

    SET = "SET"
    DEL = "DEL"
    APP = "APP"
    SPL = "SPL"


# ---------------------------------------------------------------------------
# Semantic value types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VectorValue:
    """A typed, fixed-dimension numeric array (Relay ``vector`` semantic type).

    Parameters
    ----------
    dtype : VectorDtype
        Element numeric type.
    dim : int
        Number of elements; must equal ``len(data)``.
    data : numpy.ndarray
        The numeric payload.  Shape must be ``(dim,)``.

    Raises
    ------
    ValueError
        If ``len(data) != dim`` or the array dtype does not match *dtype*.

    Examples
    --------
    >>> import numpy as np
    >>> v = VectorValue(VectorDtype.FLOAT32, 3, np.array([1.0, 2.0, 3.0], dtype=np.float32))
    >>> v.dim
    3
    """

    dtype: VectorDtype
    dim: int
    data: np.ndarray

    def __post_init__(self) -> None:
        if len(self.data) != self.dim:
            raise ValueError(f"VectorValue: dim={self.dim} but data has {len(self.data)} elements")

    # numpy arrays are not hashable; provide a custom __hash__ so the dataclass
    # frozen=True still works for identity purposes.
    def __hash__(self) -> int:  # type: ignore[override]
        return hash((self.dtype, self.dim, self.data.tobytes()))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, VectorValue):
            return NotImplemented
        return (
            self.dtype == other.dtype
            and self.dim == other.dim
            and np.array_equal(self.data, other.data)
        )


@dataclass(frozen=True, slots=True)
class CodeBlock:
    """A fenced code block with an explicit language tag.

    Parameters
    ----------
    lang : str
        Language identifier, e.g. ``"python"``, ``"json"``.
    code : str
        Source code content.

    Examples
    --------
    >>> cb = CodeBlock(lang="python", code="print('hello')")
    >>> cb.lang
    'python'
    """

    lang: str
    code: str


@dataclass(frozen=True, slots=True)
class MarkdownBlock:
    """A Markdown-formatted text block.

    Parameters
    ----------
    content : str
        Raw Markdown text.

    Examples
    --------
    >>> mb = MarkdownBlock(content="# Hello\\nWorld")
    >>> mb.content
    '# Hello\\nWorld'
    """

    content: str


@dataclass(frozen=True, slots=True)
class EnumValue:
    """A resolved enum value carrying both the symbolic name and its numeric index.

    The index is the authoritative wire representation; the name is resolved
    from the schema and used in text encoding and display.

    Parameters
    ----------
    name : str
        Symbolic enum value name, e.g. ``"assistant"``.
    index : int
        Zero-based position in the enum definition order.

    Examples
    --------
    >>> ev = EnumValue(name="assistant", index=2)
    >>> ev.index
    2
    """

    name: str
    index: int


# ---------------------------------------------------------------------------
# Reference type
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RelayRef:
    """A ``$ref`` expression pointing to a field in a prior session output.

    The reference is resolved by :mod:`relay.reference` and
    :class:`relay.session.Session`.

    Parameters
    ----------
    session_id : UUID
        The session UUID that produced the referenced output.
    call_index : int
        Zero-based index of the call within the session.
    field_path : str
        Dot-separated path into the message, e.g. ``"tool_call.arguments.rate"``.

    Examples
    --------
    >>> from uuid import UUID
    >>> ref = RelayRef(
    ...     session_id=UUID("550e8400-e29b-41d4-a716-446655440000"),
    ...     call_index=2,
    ...     field_path="output.embedding",
    ... )
    >>> ref.field_path
    'output.embedding'
    """

    session_id: UUID
    call_index: int
    field_path: str


# ---------------------------------------------------------------------------
# Delta operation
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class DeltaOp:
    """A single mutation operation within a Relay DELTA message.

    Parameters
    ----------
    op_type : DeltaOpType
        The kind of operation: SET, DEL, APP, or SPL.
    field_path : str
        Dot-separated path to the target field.
    type_tag : TypeTag or None
        The Relay type tag of *value*.  Required for SET, APP, and SPL;
        ``None`` for DEL.
    value : Any
        The new value to write.  ``None`` for DEL.
    splice_start : int or None
        Inclusive start index for SPL operations.  ``None`` otherwise.
    splice_end : int or None
        Exclusive end index for SPL operations.  ``None`` otherwise.

    Examples
    --------
    >>> op = DeltaOp(
    ...     op_type=DeltaOpType.SET,
    ...     field_path="tool_call.arguments.rate",
    ...     type_tag=TypeTag.FLOAT64,
    ...     value=0.10,
    ... )
    >>> op.op_type
    <DeltaOpType.SET: 'SET'>
    """

    op_type: DeltaOpType
    field_path: str
    type_tag: TypeTag | None = None
    value: Any = None
    splice_start: int | None = None
    splice_end: int | None = None


# ---------------------------------------------------------------------------
# Core message structures
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class RelayField:
    """A single decoded field within a Relay message payload.

    Parameters
    ----------
    field_id : int
        Numeric field identifier (uint16) that maps to a name via the schema.
    name : str
        Human-readable field name resolved from the schema.
    type_tag : TypeTag
        The wire type tag for this field.
    value : Any
        The decoded Python value.  For nested objects this is a list of
        ``RelayField``; for arrays it is a list of values; for semantic types
        it is the appropriate dataclass (e.g. ``VectorValue``, ``CodeBlock``).

    Examples
    --------
    >>> f = RelayField(field_id=1, name="role", type_tag=TypeTag.ENUM,
    ...                value=EnumValue(name="assistant", index=2))
    >>> f.name
    'role'
    """

    field_id: int
    name: str
    type_tag: TypeTag
    value: Any


@dataclass(slots=True)
class RelayMessage:
    """A fully decoded Relay message.

    Parameters
    ----------
    message_type : MessageType
        FULL, DELTA, REF_ONLY, SCHEMA_DEF, or ERROR.
    schema_hash : bytes
        The 4-byte schema hash extracted from the frame header.
    fields : list of RelayField
        Ordered sequence of decoded fields.
    raw_bytes : bytes or None, optional
        The original binary frame bytes, preserved for round-trip fidelity.
    delta_base_ref : RelayRef or None, optional
        When building a DELTA frame via :func:`relay.delta`, supplies the
        ``__base__`` reference if not derivable elsewhere.

    Examples
    --------
    >>> msg = RelayMessage(
    ...     message_type=MessageType.FULL,
    ...     schema_hash=bytes.fromhex("a3f2bc01"),
    ...     fields=[],
    ... )
    >>> msg.message_type
    <MessageType.FULL: 1>
    """

    message_type: MessageType
    schema_hash: bytes
    fields: list[RelayField] = field(default_factory=list)
    raw_bytes: bytes | None = None
    delta_base_ref: RelayRef | None = None

    def get_field(self, name: str) -> RelayField | None:
        """Return the first field whose name matches *name*, or ``None``.

        Parameters
        ----------
        name : str
            The field name to look up.

        Returns
        -------
        RelayField or None

        Examples
        --------
        >>> msg = RelayMessage(MessageType.FULL, b"\\x00\\x00\\x00\\x00",
        ...     [RelayField(1, "role", TypeTag.ENUM, EnumValue("assistant", 2))])
        >>> msg.get_field("role").name
        'role'
        >>> msg.get_field("missing") is None
        True
        """
        for f in self.fields:
            if f.name == name:
                return f
        return None

    def to_dict(self) -> dict[str, Any]:
        """Convert the message to a plain nested dictionary for inspection.

        Semantic values (``VectorValue``, ``CodeBlock``, etc.) are represented
        as their dataclass ``__dict__``, with numpy arrays converted to Python
        lists.

        Returns
        -------
        dict
            A JSON-serialisable (after numpy conversion) representation.

        Examples
        --------
        >>> msg = RelayMessage(MessageType.FULL, b"\\x00\\x00\\x00\\x00", [])
        >>> msg.to_dict()["message_type"]
        'FULL'
        """
        return {
            "message_type": self.message_type.name,
            "schema_hash": self.schema_hash.hex(),
            "fields": [_field_to_dict(f) for f in self.fields],
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _field_to_dict(f: RelayField) -> dict[str, Any]:
    """Convert a ``RelayField`` to a plain dict recursively.

    Parameters
    ----------
    f : RelayField
        The field to convert.

    Returns
    -------
    dict
        Plain representation suitable for display or JSON serialisation.
    """
    value = f.value

    match f.type_tag:
        case TypeTag.OBJECT:
            if isinstance(value, list):
                value = [_field_to_dict(child) for child in value]
        case TypeTag.ARRAY:
            if isinstance(value, list):
                value = [
                    _field_to_dict(item) if isinstance(item, RelayField) else item for item in value
                ]
        case TypeTag.VECTOR:
            if isinstance(value, VectorValue):
                value = {
                    "dtype": value.dtype.name,
                    "dim": value.dim,
                    "data": value.data.tolist(),
                }
        case TypeTag.UUID:
            if isinstance(value, UUID):
                value = str(value)
        case TypeTag.DATETIME:
            # stored as microseconds int; keep as-is for dict representation
            pass
        case TypeTag.ENUM:
            if isinstance(value, EnumValue):
                value = {"name": value.name, "index": value.index}
        case TypeTag.CODE_BLOCK:
            if isinstance(value, CodeBlock):
                value = {"lang": value.lang, "code": value.code}
        case TypeTag.MARKDOWN_BLOCK:
            if isinstance(value, MarkdownBlock):
                value = {"content": value.content}
        case TypeTag.REF:
            if isinstance(value, RelayRef):
                value = {
                    "session_id": str(value.session_id),
                    "call_index": value.call_index,
                    "field_path": value.field_path,
                }
        case _:
            pass

    return {
        "field_id": f.field_id,
        "name": f.name,
        "type": f.type_tag.name,
        "value": value,
    }


# ---------------------------------------------------------------------------
# Numpy dtype helpers
# ---------------------------------------------------------------------------

#: Map from ``VectorDtype`` to the numpy dtype string used for array creation.
VECTOR_DTYPE_TO_NUMPY: dict[VectorDtype, str] = {
    VectorDtype.FLOAT16: "float16",
    VectorDtype.FLOAT32: "float32",
    VectorDtype.FLOAT64: "float64",
    VectorDtype.INT8: "int8",
}

#: Map from numpy dtype string to ``VectorDtype``.
NUMPY_TO_VECTOR_DTYPE: dict[str, VectorDtype] = {v: k for k, v in VECTOR_DTYPE_TO_NUMPY.items()}

#: Number of bytes per element for each ``VectorDtype``.
VECTOR_DTYPE_ITEMSIZE: dict[VectorDtype, int] = {
    VectorDtype.FLOAT16: 2,
    VectorDtype.FLOAT32: 4,
    VectorDtype.FLOAT64: 8,
    VectorDtype.INT8: 1,
}


# ---------------------------------------------------------------------------
# Schema structures
# ---------------------------------------------------------------------------


@dataclass
class SchemaField:
    """Descriptor for a single field in a Relay schema.

    Parameters
    ----------
    name : str
        Field name as it appears in messages and text encoding.
    type_tag : TypeTag
        Wire-level type tag for this field.
    field_id : int
        1-based integer identifier used in binary field frames.
    required : bool
        If ``True`` the encoder raises when this field is absent from the
        input dict.  Default is ``True``.
    sub_fields : list[SchemaField]
        For ``OBJECT`` typed fields: the nested field descriptors in order.
        Empty for all other types.
    enum_values : list[str]
        For ``ENUM`` typed fields: the ordered list of symbolic value names.
        The wire index is the 0-based position in this list.
    vector_dtype : VectorDtype or None
        For ``VECTOR`` typed fields: the element dtype tag.
    vector_dim : int or None
        For ``VECTOR`` typed fields: the expected number of elements.
    element_type_tag : TypeTag or None
        For ``ARRAY`` typed fields: the declared element type tag.

    Examples
    --------
    >>> sf = SchemaField("role", TypeTag.ENUM, field_id=1, enum_values=["user", "assistant"])
    >>> sf.field_id
    1
    >>> sf.enum_values
    ['user', 'assistant']
    """

    name: str
    type_tag: TypeTag
    field_id: int
    required: bool = True
    sub_fields: list[SchemaField] = field(default_factory=list)
    enum_values: list[str] = field(default_factory=list)
    vector_dtype: VectorDtype | None = None
    vector_dim: int | None = None
    element_type_tag: TypeTag | None = None

    def sub_field_by_name(self, name: str) -> SchemaField | None:
        """Return the nested ``SchemaField`` matching *name*, or ``None``.

        Parameters
        ----------
        name : str

        Returns
        -------
        SchemaField or None
        """
        for sf in self.sub_fields:
            if sf.name == name:
                return sf
        return None

    def sub_field_by_id(self, field_id: int) -> SchemaField | None:
        """Return the nested ``SchemaField`` matching *field_id*, or ``None``.

        Parameters
        ----------
        field_id : int

        Returns
        -------
        SchemaField or None
        """
        for sf in self.sub_fields:
            if sf.field_id == field_id:
                return sf
        return None


@dataclass
class RelaySchema:
    """A compiled Relay schema used for encoding and decoding.

    Parameters
    ----------
    name : str
        Schema name (e.g. ``"agent_tool_call"``).
    version : int
        Schema version integer, starting at 1.
    fields : list[SchemaField]
        Top-level field descriptors in declaration order.
    schema_hash : bytes
        Four-byte hash (first 4 bytes of SHA-256 of canonical schema JSON).
        Default is ``b'\\x00\\x00\\x00\\x00'`` for unregistered schemas.

    Examples
    --------
    >>> schema = RelaySchema(
    ...     name="ping",
    ...     version=1,
    ...     fields=[SchemaField("id", TypeTag.UUID, field_id=1)],
    ...     schema_hash=b"\\xaa\\xbb\\xcc\\xdd",
    ... )
    >>> schema.field_by_name("id").type_tag
    <TypeTag.UUID: 17>
    """

    name: str
    version: int
    fields: list[SchemaField] = field(default_factory=list)
    schema_hash: bytes = field(default_factory=lambda: b"\x00\x00\x00\x00")

    def field_by_name(self, name: str) -> SchemaField | None:
        """Return the top-level field with the given *name*, or ``None``.

        Parameters
        ----------
        name : str

        Returns
        -------
        SchemaField or None
        """
        for f in self.fields:
            if f.name == name:
                return f
        return None

    def field_by_id(self, field_id: int) -> SchemaField | None:
        """Return the top-level field with the given *field_id*, or ``None``.

        Parameters
        ----------
        field_id : int

        Returns
        -------
        SchemaField or None
        """
        for f in self.fields:
            if f.field_id == field_id:
                return f
        return None

    @property
    def hash_hex(self) -> str:
        """Four-byte schema hash as a lowercase 8-character hex string.

        Returns
        -------
        str
        """
        return self.schema_hash.hex()


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

__all__ = [
    "FIELD_HEADER_SIZE",
    "FRAME_HEADER_SIZE",
    # Constants
    "MAGIC",
    "NUMPY_TO_VECTOR_DTYPE",
    "VECTOR_DTYPE_ITEMSIZE",
    # Helpers
    "VECTOR_DTYPE_TO_NUMPY",
    "VERSION",
    "CodeBlock",
    "DeltaOp",
    "DeltaOpType",
    "EnumValue",
    "MarkdownBlock",
    "MessageType",
    # Message structures
    "RelayField",
    "RelayMessage",
    "RelayRef",
    "RelaySchema",
    # Schema structures
    "SchemaField",
    # Enums
    "TypeTag",
    "VectorDtype",
    # Value types
    "VectorValue",
]
