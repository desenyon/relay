"""
Compile :mod:`relay.schema` definitions into :mod:`relay.types` wire schemas.

Source schemas use string type names (``"int32"``, ``"enum<Role>"``, …).
Compiled schemas attach concrete :class:`~relay.types.TypeTag` values,
numeric ``field_id`` values, enum member lists, and vector parameters needed by
the binary encoder and decoder.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from relay.errors import ParseError, SchemaNotFoundError
from relay.types import SchemaField as CompiledField
from relay.types import RelaySchema as CompiledSchema
from relay.types import TypeTag, VectorDtype

if TYPE_CHECKING:
    from relay.schema import RelaySchema as SourceSchema
    from relay.schema import SchemaField as SourceField


_VECTOR_RE = re.compile(
    r"^vector<\s*(float16|float32|float64|int8)\s*,\s*(\d+)\s*>$",
    re.IGNORECASE,
)
_ARRAY_RE = re.compile(r"^array(?:<(.+)>)?$", re.IGNORECASE)


def compile_schema(source: SourceSchema) -> CompiledSchema:
    """Compile a source :class:`relay.schema.RelaySchema` for binary I/O.

    Parameters
    ----------
    source : relay.schema.RelaySchema
        Schema parsed from ``.rschema`` or built via ``from_dict``.

    Returns
    -------
    relay.types.RelaySchema
        Compiled schema with ``schema_hash`` populated from *source*.

    Raises
    ------
    ParseError
        If a type string cannot be interpreted.
    SchemaNotFoundError
        If an ``enum<Name>`` references a missing enum definition.
    """
    fields = _compile_fields(source.fields, source.enums)
    return CompiledSchema(
        name=source.name,
        version=source.version,
        fields=fields,
        schema_hash=source.hash_bytes(),
    )


def _compile_fields(
    fields: list[SourceField],
    enums: dict[str, list[str]],
) -> list[CompiledField]:
    out: list[CompiledField] = []
    for i, sf in enumerate(fields, start=1):
        out.append(_compile_field(sf, i, enums))
    return out


def _compile_field(sf: SourceField, field_id: int, enums: dict[str, list[str]]) -> CompiledField:
    tname = sf.type_name.strip()
    type_tag, vec_dtype, vec_dim, enum_vals, elem_tag = _resolve_type(tname, sf, enums)

    sub: list[CompiledField] = []
    if type_tag == TypeTag.OBJECT and sf.nested_fields:
        sub = _compile_fields(sf.nested_fields, enums)

    return CompiledField(
        name=sf.name,
        type_tag=type_tag,
        field_id=field_id,
        required=sf.required,
        sub_fields=sub,
        enum_values=list(enum_vals),
        vector_dtype=vec_dtype,
        vector_dim=vec_dim,
        element_type_tag=elem_tag,
    )


def _resolve_type(
    tname: str,
    sf: SourceField,
    enums: dict[str, list[str]],
) -> tuple[TypeTag, VectorDtype | None, int | None, list[str], TypeTag | None]:
    """Return (type_tag, vector_dtype, vector_dim, enum_values, element_type_tag)."""
    enum_vals: list[str] = []
    vec_dtype: VectorDtype | None = None
    vec_dim: int | None = None
    elem_tag: TypeTag | None = None

    if tname.startswith("enum<") and tname.endswith(">"):
        en = sf.enum_name
        if not en:
            m = re.match(r"enum<(\w+)>", tname)
            en = m.group(1) if m else ""
        if en not in enums:
            raise SchemaNotFoundError(
                f"Enum '{en}' is not defined in schema",
                details={"enum": en, "field": sf.name},
            )
        enum_vals = list(enums[en])
        return TypeTag.ENUM, None, None, enum_vals, None

    vm = _VECTOR_RE.match(tname)
    if vm:
        dtype_name = vm.group(1).lower()
        dim = int(vm.group(2))
        vd = {
            "float16": VectorDtype.FLOAT16,
            "float32": VectorDtype.FLOAT32,
            "float64": VectorDtype.FLOAT64,
            "int8": VectorDtype.INT8,
        }[dtype_name]
        return TypeTag.VECTOR, vd, dim, [], None

    am = _ARRAY_RE.match(tname)
    if am:
        inner = (am.group(1) or "string").strip()
        elem_tag = _simple_type_name_to_tag(inner)
        return TypeTag.ARRAY, None, None, [], elem_tag

    if tname.startswith("code_block"):
        return TypeTag.CODE_BLOCK, None, None, [], None

    if tname in ("markdown_block", "markdown"):
        return TypeTag.MARKDOWN_BLOCK, None, None, [], None

    if tname == "object":
        return TypeTag.OBJECT, None, None, [], None

    if tname == "ref":
        return TypeTag.REF, None, None, [], None

    if tname == "delta_op":
        return TypeTag.DELTA_OP, None, None, [], None

    tag = _simple_type_name_to_tag(tname)
    return tag, None, None, [], None


def _simple_type_name_to_tag(name: str) -> TypeTag:
    n = name.strip().lower()
    mapping: dict[str, TypeTag] = {
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
        "uuid": TypeTag.UUID,
        "datetime": TypeTag.DATETIME,
        "uri": TypeTag.URI,
    }
    if n not in mapping:
        raise ParseError(
            f"Unknown or unsupported schema type: {name!r}",
            details={"type_name": name},
        )
    return mapping[n]


__all__ = ["compile_schema"]
