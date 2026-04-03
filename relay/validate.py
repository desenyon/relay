"""
Schema validation logic for Relay messages.

Validation is the final gate before a message is accepted or rejected.  It
runs *after* decoding (or before encoding when the input dict is checked
against the schema) and verifies:

* Every required field is present.
* Every field's decoded type tag matches the schema declaration.
* Enum values are within the declared value set.
* Nested objects are validated recursively with accurate field paths.

All failures raise a typed :class:`~relay.errors.RelayError` subclass — there
are no silent coercions, no ``None`` returns, and no bare Python exceptions.

Typical usage
-------------
>>> from relay.validate import validate_message
>>> # validate_message(message, schema)  # raises on failure, returns None on success
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from relay.errors import TypeMismatchError, ValidationError
from relay.types import (
    EnumValue,
    RelayField,
    RelayMessage,
    TypeTag,
    VectorValue,
)

if TYPE_CHECKING:
    # Import the binary-encoder-oriented schema types from types.py
    from relay.types import RelaySchema, SchemaField


# ---------------------------------------------------------------------------
# TYPE_NAME_TO_TAG — mapping from schema type strings to TypeTag values
# ---------------------------------------------------------------------------

#: Maps schema type name strings (as used in ``.rschema`` and ``schema.py``)
#: to their wire-level :class:`~relay.types.TypeTag`.  Parameterised types
#: (``enum<…>``, ``vector<…>``) are matched by prefix in validation logic.
TYPE_NAME_TO_TAG: dict[str, TypeTag] = {
    "null": TypeTag.NULL,
    "bool": TypeTag.BOOL,
    "boolean": TypeTag.BOOL,
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
    "str": TypeTag.STRING,
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
    "delta_op": TypeTag.DELTA_OP,
    # Aliases occasionally used in text format
    "markdown": TypeTag.MARKDOWN_BLOCK,
    "code": TypeTag.CODE_BLOCK,
}


def _type_name_to_tag(type_name: str) -> TypeTag | None:
    """Resolve a schema type name string to a ``TypeTag``.

    Handles parameterised types like ``enum<MessageRole>`` and
    ``vector<float32, 512>`` by stripping the parameter suffix.

    Parameters
    ----------
    type_name : str
        The type name from a schema field definition.

    Returns
    -------
    TypeTag or None
        ``None`` if the type name is not recognised.
    """
    # Direct lookup first
    if type_name in TYPE_NAME_TO_TAG:
        return TYPE_NAME_TO_TAG[type_name]

    # Strip generic parameters: enum<…>, vector<…, …>, code_block<…>
    base = type_name.split("<")[0].strip().lower()
    return TYPE_NAME_TO_TAG.get(base)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def validate_message(message: RelayMessage, schema: RelaySchema) -> None:
    """Validate a decoded ``RelayMessage`` against a compiled ``RelaySchema``.

    Checks that:

    * Every required schema field is present in the message.
    * Every present field's type tag matches the schema declaration.
    * Enum values are within range for their declared enum.
    * Nested objects are recursively validated.

    Parameters
    ----------
    message : RelayMessage
        The decoded message to validate.
    schema : RelaySchema
        The compiled schema to validate against.  Must be the ``RelaySchema``
        from :mod:`relay.types` (i.e., the encoder/decoder representation with
        ``type_tag`` and ``field_id`` on each field).

    Returns
    -------
    None
        Returns ``None`` on success.

    Raises
    ------
    ValidationError
        If a required field is absent or an enum value is out of range.
    TypeMismatchError
        If a field's type tag does not match the schema declaration.

    Examples
    --------
    >>> from relay.types import (
    ...     RelayMessage, RelayField, MessageType, TypeTag, SchemaField, RelaySchema
    ... )
    >>> schema = RelaySchema(
    ...     name="ping",
    ...     version=1,
    ...     fields=[SchemaField("msg", TypeTag.STRING, field_id=1, required=True)],
    ...     schema_hash=b"\\x00\\x00\\x00\\x00",
    ... )
    >>> msg = RelayMessage(
    ...     message_type=MessageType.FULL,
    ...     schema_hash=b"\\x00\\x00\\x00\\x00",
    ...     fields=[RelayField(field_id=1, name="msg", type_tag=TypeTag.STRING, value="hello")],
    ... )
    >>> validate_message(msg, schema)  # no exception
    """
    # Build a name-keyed index of the decoded message's fields for O(1) lookup.
    field_index: dict[str, RelayField] = {f.name: f for f in message.fields}

    for schema_field in schema.fields:
        present = schema_field.name in field_index

        if schema_field.required and not present:
            raise ValidationError(
                f"Required field '{schema_field.name}' is missing from message",
                field_path=schema_field.name,
                details={"field": schema_field.name, "schema": schema.name},
            )

        if present:
            relay_field = field_index[schema_field.name]
            validate_field(
                relay_field,
                schema_field,
                schema,
                path=schema_field.name,
            )


def validate_field(
    field: RelayField,
    schema_field: SchemaField,
    schema: RelaySchema,
    path: str,
) -> None:
    """Validate a single ``RelayField`` against its ``SchemaField`` descriptor.

    Parameters
    ----------
    field : RelayField
        The decoded field to validate.
    schema_field : SchemaField
        The schema descriptor from :mod:`relay.types`.
    schema : RelaySchema
        The parent schema (needed for enum validation on nested objects).
    path : str
        Dot-separated path to this field for error messages, e.g.
        ``"tool_call.arguments.rate"``.

    Returns
    -------
    None

    Raises
    ------
    TypeMismatchError
        If the field's type tag does not match the schema's declared type tag.
    ValidationError
        If an enum value index is out of range, or a required nested field is
        absent.

    Examples
    --------
    >>> from relay.types import RelayField, TypeTag, SchemaField, RelaySchema
    >>> sf = SchemaField("score", TypeTag.FLOAT64, field_id=1)
    >>> f = RelayField(field_id=1, name="score", type_tag=TypeTag.FLOAT64, value=0.95)
    >>> schema = RelaySchema("s", 1, [sf], b"\\x00\\x00\\x00\\x00")
    >>> validate_field(f, sf, schema, path="score")  # no exception
    """
    # --- Type tag check ---
    if field.type_tag != schema_field.type_tag:
        raise TypeMismatchError(
            f"Field '{path}' has type {field.type_tag.name!r} but schema "
            f"declares {schema_field.type_tag.name!r}",
            field_path=path,
            details={
                "expected": schema_field.type_tag.name,
                "got": field.type_tag.name,
            },
        )

    # --- Type-specific validation ---
    match schema_field.type_tag:
        case TypeTag.ENUM:
            _validate_enum(field, schema_field, path)

        case TypeTag.OBJECT:
            _validate_object(field, schema_field, schema, path)

        case TypeTag.ARRAY:
            _validate_array(field, schema_field, schema, path)

        case TypeTag.VECTOR:
            _validate_vector(field, schema_field, path)

        case _:
            # All scalar types are fully validated by the type-tag check above.
            pass


# ---------------------------------------------------------------------------
# Type-specific validators
# ---------------------------------------------------------------------------


def _validate_enum(
    field: RelayField,
    schema_field: SchemaField,
    path: str,
) -> None:
    """Validate that an enum field value is in range.

    Parameters
    ----------
    field : RelayField
        The decoded enum field.  ``field.value`` should be an
        :class:`~relay.types.EnumValue` or a plain ``int``.
    schema_field : SchemaField
        Schema descriptor with ``enum_values`` populated.
    path : str
        Dot-separated field path for error messages.

    Raises
    ------
    ValidationError
        If the enum index is out of range or the symbolic name does not match
        the schema's declared value list.
    TypeMismatchError
        If ``field.value`` is not an ``EnumValue`` or ``int``.
    """
    value = field.value

    if isinstance(value, EnumValue):
        index = value.index
        name = value.name
    elif isinstance(value, int):
        index = value
        name = None
    else:
        raise TypeMismatchError(
            f"Field '{path}' is declared as ENUM but value has Python type "
            f"{type(value).__name__!r}",
            field_path=path,
            details={"got_python_type": type(value).__name__},
        )

    enum_values = schema_field.enum_values
    if not enum_values:
        # No enum value list in schema — skip range check
        return

    if index < 0 or index >= len(enum_values):
        raise ValidationError(
            f"Enum value index {index} is out of range for field '{path}' "
            f"(valid range 0-{len(enum_values) - 1})",
            field_path=path,
            details={
                "index": index,
                "valid_range": [0, len(enum_values) - 1],
                "enum_values": enum_values,
            },
        )

    if name is not None and name != enum_values[index]:
        raise ValidationError(
            f"Enum symbolic name '{name}' does not match schema value "
            f"'{enum_values[index]}' at index {index} for field '{path}'",
            field_path=path,
            details={
                "name": name,
                "expected_name": enum_values[index],
                "index": index,
            },
        )


def _validate_object(
    field: RelayField,
    schema_field: SchemaField,
    schema: RelaySchema,
    path: str,
) -> None:
    """Recursively validate the sub-fields of an OBJECT field.

    Parameters
    ----------
    field : RelayField
        The decoded object field.  ``field.value`` should be a list of
        :class:`~relay.types.RelayField`.
    schema_field : SchemaField
        Schema descriptor with ``sub_fields`` populated.
    schema : RelaySchema
        The parent schema (passed through for enum resolution).
    path : str
        Dot-separated path to this field.

    Raises
    ------
    TypeMismatchError
        If ``field.value`` is not a list.
    ValidationError
        If a required sub-field is missing.
    """
    if not isinstance(field.value, list):
        raise TypeMismatchError(
            f"Field '{path}' is declared as OBJECT but value is not a list "
            f"(got {type(field.value).__name__!r})",
            field_path=path,
            details={"got_python_type": type(field.value).__name__},
        )

    if not schema_field.sub_fields:
        # Object schema has no sub-field definitions — accept any content.
        return

    # Build name index of present sub-fields
    present: dict[str, RelayField] = {}
    for sub in field.value:
        if isinstance(sub, RelayField):
            present[sub.name] = sub

    for sub_schema in schema_field.sub_fields:
        sub_path = f"{path}.{sub_schema.name}"
        if sub_schema.required and sub_schema.name not in present:
            raise ValidationError(
                f"Required sub-field '{sub_path}' is missing from object",
                field_path=sub_path,
                details={"field": sub_schema.name, "parent": path},
            )
        if sub_schema.name in present:
            validate_field(present[sub_schema.name], sub_schema, schema, sub_path)


def _validate_array(
    field: RelayField,
    schema_field: SchemaField,
    schema: RelaySchema,
    path: str,
) -> None:
    """Validate that each element in an ARRAY field matches the declared element type.

    Parameters
    ----------
    field : RelayField
        The decoded array field.  ``field.value`` should be a list.
    schema_field : SchemaField
        Schema descriptor.  ``schema_field.element_type_tag`` carries the
        declared element type (may be ``None`` if unconstrained).
    schema : RelaySchema
        The parent schema.
    path : str
        Dot-separated path to this field.

    Raises
    ------
    TypeMismatchError
        If ``field.value`` is not a list, or an element's type does not match
        the declared element type.
    """
    if not isinstance(field.value, list):
        raise TypeMismatchError(
            f"Field '{path}' is declared as ARRAY but value is not a list "
            f"(got {type(field.value).__name__!r})",
            field_path=path,
            details={"got_python_type": type(field.value).__name__},
        )

    element_tag = schema_field.element_type_tag
    if element_tag is None:
        # No element type constraint — accept any element types.
        return

    for idx, element in enumerate(field.value):
        elem_path = f"{path}[{idx}]"
        if isinstance(element, RelayField):
            if element.type_tag != element_tag:
                raise TypeMismatchError(
                    f"Array element at '{elem_path}' has type "
                    f"{element.type_tag.name!r} but schema declares "
                    f"{element_tag.name!r}",
                    field_path=elem_path,
                    details={
                        "expected": element_tag.name,
                        "got": element.type_tag.name,
                        "index": idx,
                    },
                )
        # Bare values (not wrapped in RelayField) are accepted when the
        # array element is a scalar; type enforcement at decode time is
        # sufficient for these.


def _validate_vector(
    field: RelayField,
    schema_field: SchemaField,
    path: str,
) -> None:
    """Validate a VECTOR field's dtype and dimension against the schema.

    Parameters
    ----------
    field : RelayField
        The decoded vector field.  ``field.value`` should be a
        :class:`~relay.types.VectorValue`.
    schema_field : SchemaField
        Schema descriptor with ``vector_dtype`` and ``vector_dim`` populated.
    path : str
        Dot-separated path to this field.

    Raises
    ------
    TypeMismatchError
        If ``field.value`` is not a ``VectorValue``, or its dtype/dim do not
        match the schema constraints.
    """
    if not isinstance(field.value, VectorValue):
        raise TypeMismatchError(
            f"Field '{path}' is declared as VECTOR but value has Python type "
            f"{type(field.value).__name__!r}",
            field_path=path,
            details={"got_python_type": type(field.value).__name__},
        )

    vec: VectorValue = field.value

    if schema_field.vector_dtype is not None and vec.dtype != schema_field.vector_dtype:
        raise TypeMismatchError(
            f"Vector field '{path}' has dtype {vec.dtype.name!r} but schema "
            f"declares {schema_field.vector_dtype.name!r}",
            field_path=path,
            details={
                "expected_dtype": schema_field.vector_dtype.name,
                "got_dtype": vec.dtype.name,
            },
        )

    if schema_field.vector_dim is not None and vec.dim != schema_field.vector_dim:
        raise TypeMismatchError(
            f"Vector field '{path}' has dimension {vec.dim} but schema "
            f"declares {schema_field.vector_dim}",
            field_path=path,
            details={
                "expected_dim": schema_field.vector_dim,
                "got_dim": vec.dim,
            },
        )


# ---------------------------------------------------------------------------
# Dict-level validation (pre-encoding)
# ---------------------------------------------------------------------------


def validate_dict(
    data: dict[str, Any],
    schema: RelaySchema,
    *,
    path: str = "",
) -> None:
    """Validate a raw Python dict against a compiled ``RelaySchema`` before encoding.

    This is a lightweight structural check that verifies required fields are
    present and basic type compatibility.  It operates on the pre-encoded dict
    representation, not on decoded :class:`~relay.types.RelayField` objects.

    Parameters
    ----------
    data : dict
        The Python dictionary to validate.
    schema : RelaySchema
        The schema to validate against.
    path : str, optional
        Dot-separated path prefix for nested error messages.  Usually left
        empty by callers; set automatically on recursive calls.

    Returns
    -------
    None

    Raises
    ------
    ValidationError
        If a required field is absent from *data*.
    TypeMismatchError
        If a field value's Python type is incompatible with the schema type.

    Examples
    --------
    >>> from relay.types import TypeTag, SchemaField, RelaySchema
    >>> schema = RelaySchema(
    ...     name="s",
    ...     version=1,
    ...     fields=[SchemaField("msg", TypeTag.STRING, field_id=1, required=True)],
    ...     schema_hash=b"\\x00\\x00\\x00\\x00",
    ... )
    >>> validate_dict({"msg": "hello"}, schema)  # no exception
    >>> validate_dict({}, schema)  # raises ValidationError
    Traceback (most recent call last):
        ...
    relay.errors.ValidationError: Required field 'msg' is missing from data
    """
    for schema_field in schema.fields:
        field_path = f"{path}.{schema_field.name}" if path else schema_field.name

        if schema_field.name not in data:
            if schema_field.required:
                raise ValidationError(
                    f"Required field '{schema_field.name}' is missing from data",
                    field_path=field_path,
                    details={"field": schema_field.name},
                )
            continue

        value = data[schema_field.name]
        _check_python_type_compatibility(value, schema_field, field_path)


def _check_python_type_compatibility(
    value: Any,
    schema_field: SchemaField,
    path: str,
) -> None:
    """Perform lightweight Python-type vs. schema-type compatibility checks.

    Does not enforce exact types — that is the encoder's job.  This function
    catches obviously wrong types (e.g., passing a ``str`` where an ``int64``
    is expected) while allowing valid implicit cases (e.g., Python ``int``
    for ``int64``).

    Parameters
    ----------
    value : Any
        The Python value from the input dict.
    schema_field : SchemaField
        The schema descriptor to check against.
    path : str
        Field path for error messages.

    Raises
    ------
    TypeMismatchError
        If the Python value is clearly incompatible with the declared type.
    """
    tag = schema_field.type_tag

    # These checks use match statements to stay readable without being
    # exhaustive — the encoder will catch finer-grained errors.
    match tag:
        case TypeTag.BOOL:
            if not isinstance(value, bool):
                raise TypeMismatchError(
                    f"Field '{path}' expects bool, got {type(value).__name__}",
                    field_path=path,
                    details={"expected": "bool", "got": type(value).__name__},
                )

        case (
            TypeTag.INT8
            | TypeTag.INT16
            | TypeTag.INT32
            | TypeTag.INT64
            | TypeTag.UINT8
            | TypeTag.UINT16
            | TypeTag.UINT32
            | TypeTag.UINT64
        ):
            # bool is a subclass of int in Python — reject it for integer fields
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeMismatchError(
                    f"Field '{path}' expects an integer type, " f"got {type(value).__name__}",
                    field_path=path,
                    details={"expected": tag.name, "got": type(value).__name__},
                )

        case TypeTag.FLOAT32 | TypeTag.FLOAT64:
            if isinstance(value, bool) or not isinstance(value, float):
                raise TypeMismatchError(
                    f"Field '{path}' expects Python float for {tag.name} "
                    f"(no implicit int→float), got {type(value).__name__}",
                    field_path=path,
                    details={"expected": tag.name, "got": type(value).__name__},
                )

        case TypeTag.STRING | TypeTag.URI:
            if not isinstance(value, str):
                raise TypeMismatchError(
                    f"Field '{path}' expects str, got {type(value).__name__}",
                    field_path=path,
                    details={"expected": tag.name, "got": type(value).__name__},
                )

        case TypeTag.CODE_BLOCK:
            from relay.types import CodeBlock

            if not isinstance(value, (dict, CodeBlock)):
                raise TypeMismatchError(
                    f"Field '{path}' expects dict or CodeBlock, got {type(value).__name__}",
                    field_path=path,
                )

        case TypeTag.MARKDOWN_BLOCK:
            from relay.types import MarkdownBlock

            if not isinstance(value, (str, MarkdownBlock)):
                raise TypeMismatchError(
                    f"Field '{path}' expects str or MarkdownBlock, got {type(value).__name__}",
                    field_path=path,
                )

        case TypeTag.BYTES:
            if not isinstance(value, (bytes, bytearray)):
                raise TypeMismatchError(
                    f"Field '{path}' expects bytes, got {type(value).__name__}",
                    field_path=path,
                    details={"expected": "bytes", "got": type(value).__name__},
                )

        case TypeTag.ARRAY:
            if not isinstance(value, (list, tuple)):
                raise TypeMismatchError(
                    f"Field '{path}' expects a list/tuple, " f"got {type(value).__name__}",
                    field_path=path,
                    details={"expected": "array", "got": type(value).__name__},
                )

        case TypeTag.OBJECT:
            if not isinstance(value, dict):
                raise TypeMismatchError(
                    f"Field '{path}' expects dict, got {type(value).__name__}",
                    field_path=path,
                    details={"expected": "object", "got": type(value).__name__},
                )

        case _:
            # NULL, UUID, DATETIME, VECTOR, ENUM, CODE_BLOCK, REF, DELTA_OP —
            # accept any value here and let the encoder validate precisely.
            pass


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

__all__ = [
    "TYPE_NAME_TO_TAG",
    "validate_dict",
    "validate_field",
    "validate_message",
]
