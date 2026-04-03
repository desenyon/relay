"""
Relay schema definition, hashing, and registry client.

A ``RelaySchema`` carries the complete structural description of a Relay
message: field names, types, required/optional status, nested structures, and
enum definitions.  It is the single source of truth for encoding, decoding, and
validation.

Every schema has a stable 4-byte hash derived from the SHA-256 of its canonical
JSON representation.  This hash appears in every Relay frame header and is used
to look up the schema in the local registry at parse time.

Typical usage
-------------
>>> schema = RelaySchema.from_dict({
...     "name": "example",
...     "version": 1,
...     "fields": [
...         {"name": "role", "type": "enum<MessageRole>", "required": True},
...     ],
...     "enums": {"MessageRole": ["system", "user", "assistant", "tool"]},
... })
>>> schema.hash()
'...'
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from relay.errors import ParseError, SchemaNotFoundError, ValidationError


# ---------------------------------------------------------------------------
# Schema field definition
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class SchemaField:
    """Definition of a single field within a :class:`RelaySchema`.

    Parameters
    ----------
    name : str
        Field name as it appears in the text encoding and registry.
    type_name : str
        Relay type string, e.g. ``"string"``, ``"float64"``,
        ``"enum<MessageRole>"``, ``"vector<float32, 512>"``, ``"object"``.
    required : bool
        Whether the field must be present in every FULL message that uses
        this schema.  Defaults to ``True``.
    nested_fields : list of SchemaField
        Child fields for ``object`` typed fields.  Empty for scalar fields.
    enum_name : str or None
        The enum definition name referenced when *type_name* is ``"enum<…>"``.
        Populated automatically from the type_name on construction.

    Examples
    --------
    >>> sf = SchemaField(name="rate", type_name="float64", required=True)
    >>> sf.name
    'rate'
    >>> sf.enum_name is None
    True
    """

    name: str
    type_name: str
    required: bool = True
    nested_fields: list[SchemaField] = field(default_factory=list)
    enum_name: str | None = None

    def __post_init__(self) -> None:
        if self.enum_name is None:
            match = re.match(r"enum<(\w+)>", self.type_name)
            if match:
                self.enum_name = match.group(1)

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict for canonical JSON construction.

        Returns
        -------
        dict
        """
        d: dict[str, Any] = {
            "name": self.name,
            "required": self.required,
            "type": self.type_name,
        }
        if self.nested_fields:
            d["fields"] = [f.to_dict() for f in self.nested_fields]
        return d


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


@dataclass
class RelaySchema:
    """The complete structural description of a Relay message class.

    Parameters
    ----------
    name : str
        Schema name, e.g. ``"agent_tool_call"``.
    version : int
        Monotonically increasing schema version number.
    fields : list of SchemaField
        Top-level field definitions, in declaration order.
    enums : dict of {str: list of str}
        Enum type definitions.  Keys are enum names; values are ordered lists
        of symbolic value names (index == position in list).
    raw_text : str, optional
        The original ``.rschema`` source text, preserved for registry storage.

    Examples
    --------
    >>> schema = RelaySchema(
    ...     name="ping",
    ...     version=1,
    ...     fields=[SchemaField("msg", "string", required=True)],
    ...     enums={},
    ... )
    >>> len(schema.hash()) == 8  # 4 bytes -> 8 hex chars
    True
    """

    name: str
    version: int
    fields: list[SchemaField] = field(default_factory=list)
    enums: dict[str, list[str]] = field(default_factory=dict)
    raw_text: str = ""

    # ------------------------------------------------------------------
    # Hash
    # ------------------------------------------------------------------

    def to_canonical_json(self) -> str:
        """Return the canonical JSON representation used for hashing.

        The representation is deterministic: keys are sorted alphabetically,
        there is no extra whitespace, and all field lists preserve declaration
        order (enums are sorted by key for stability).

        Returns
        -------
        str
            A compact, sorted-key JSON string.

        Examples
        --------
        >>> schema = RelaySchema("ping", 1, [], {})
        >>> '"name": "ping"' in schema.to_canonical_json()
        True
        """
        doc: dict[str, Any] = {
            "enums": {k: sorted(v) for k, v in sorted(self.enums.items())},
            "fields": [f.to_dict() for f in self.fields],
            "name": self.name,
            "version": self.version,
        }
        # Use separators to eliminate all optional whitespace, sort_keys for
        # fully deterministic ordering.
        return json.dumps(doc, separators=(",", ":"), sort_keys=True)

    def hash(self) -> str:
        """Return the 4-byte schema hash as an 8-character lowercase hex string.

        The hash is the first 4 bytes of the SHA-256 digest of the canonical
        JSON representation (UTF-8 encoded).

        Returns
        -------
        str
            8-character hex string, e.g. ``"a3f2bc01"``.

        Examples
        --------
        >>> schema = RelaySchema("test", 1, [], {})
        >>> h = schema.hash()
        >>> len(h)
        8
        """
        return self.hash_bytes().hex()

    def hash_bytes(self) -> bytes:
        """Return the raw 4-byte schema hash.

        Returns
        -------
        bytes
            4 bytes derived from SHA-256 of the canonical JSON.

        Examples
        --------
        >>> schema = RelaySchema("test", 1, [], {})
        >>> len(schema.hash_bytes())
        4
        """
        canonical = self.to_canonical_json().encode("utf-8")
        digest = hashlib.sha256(canonical).digest()
        return digest[:4]

    # ------------------------------------------------------------------
    # Field / enum accessors
    # ------------------------------------------------------------------

    def get_field(self, name: str) -> SchemaField | None:
        """Look up a top-level field by name.

        Parameters
        ----------
        name : str
            Field name to search for.

        Returns
        -------
        SchemaField or None
            The matching field, or ``None`` if not found.

        Examples
        --------
        >>> schema = RelaySchema("s", 1,
        ...     [SchemaField("role", "string", True)], {})
        >>> schema.get_field("role").name
        'role'
        >>> schema.get_field("missing") is None
        True
        """
        for f in self.fields:
            if f.name == name:
                return f
        return None

    def get_enum_index(self, enum_name: str, value_name: str) -> int:
        """Return the integer index for a named enum value.

        Parameters
        ----------
        enum_name : str
            The enum type name (e.g. ``"MessageRole"``).
        value_name : str
            The symbolic value name (e.g. ``"assistant"``).

        Returns
        -------
        int
            Zero-based index of the value within the enum definition.

        Raises
        ------
        SchemaNotFoundError
            If *enum_name* does not exist in this schema's enum definitions.
        ValidationError
            If *value_name* is not a member of the named enum.

        Examples
        --------
        >>> schema = RelaySchema("s", 1, [],
        ...     {"MessageRole": ["system", "user", "assistant", "tool"]})
        >>> schema.get_enum_index("MessageRole", "assistant")
        2
        """
        if enum_name not in self.enums:
            raise SchemaNotFoundError(
                f"Enum '{enum_name}' is not defined in schema '{self.name}'",
                details={"enum_name": enum_name, "schema": self.name},
            )
        values = self.enums[enum_name]
        if value_name not in values:
            raise ValidationError(
                f"'{value_name}' is not a valid value for enum '{enum_name}'",
                details={"enum_name": enum_name, "value": value_name, "valid": values},
            )
        return values.index(value_name)

    def get_enum_name(self, enum_name: str, index: int) -> str:
        """Return the symbolic name for an enum index.

        Parameters
        ----------
        enum_name : str
            The enum type name.
        index : int
            The numeric index to look up.

        Returns
        -------
        str
            The symbolic name at *index*.

        Raises
        ------
        SchemaNotFoundError
            If *enum_name* does not exist in this schema.
        ValidationError
            If *index* is out of range for the enum.

        Examples
        --------
        >>> schema = RelaySchema("s", 1, [],
        ...     {"MessageRole": ["system", "user", "assistant", "tool"]})
        >>> schema.get_enum_name("MessageRole", 2)
        'assistant'
        """
        if enum_name not in self.enums:
            raise SchemaNotFoundError(
                f"Enum '{enum_name}' is not defined in schema '{self.name}'",
                details={"enum_name": enum_name, "schema": self.name},
            )
        values = self.enums[enum_name]
        if index < 0 or index >= len(values):
            raise ValidationError(
                f"Enum index {index} is out of range for '{enum_name}' "
                f"(valid range 0-{len(values) - 1})",
                details={"enum_name": enum_name, "index": index, "length": len(values)},
            )
        return values[index]

    # ------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RelaySchema:
        """Construct a ``RelaySchema`` from a plain dictionary.

        Parameters
        ----------
        d : dict
            Must contain at least ``name`` (str), ``version`` (int), and
            ``fields`` (list).  Optional key ``enums`` maps enum type names to
            ordered lists of value strings.

        Returns
        -------
        RelaySchema

        Raises
        ------
        ParseError
            If required keys are missing or the value types are wrong.

        Examples
        --------
        >>> schema = RelaySchema.from_dict({
        ...     "name": "ping",
        ...     "version": 1,
        ...     "fields": [{"name": "msg", "type": "string", "required": True}],
        ...     "enums": {},
        ... })
        >>> schema.name
        'ping'
        """
        try:
            name: str = d["name"]
            version: int = int(d["version"])
        except KeyError as exc:
            raise ParseError(
                f"Schema dict is missing required key: {exc}",
                details={"keys_present": list(d.keys())},
            ) from exc

        enums: dict[str, list[str]] = {
            k: list(v) for k, v in d.get("enums", {}).items()
        }
        fields = [
            _parse_field_dict(fd) for fd in d.get("fields", [])
        ]
        return cls(name=name, version=version, fields=fields, enums=enums)

    @classmethod
    def from_file(cls, path: str | Path) -> RelaySchema:
        """Parse a ``.rschema`` file and return a ``RelaySchema``.

        Parameters
        ----------
        path : str or Path
            File system path to a ``.rschema`` source file.

        Returns
        -------
        RelaySchema

        Raises
        ------
        ParseError
            If the file does not exist, cannot be read, or contains a syntax
            error in the ``.rschema`` format.

        Examples
        --------
        >>> import tempfile, pathlib
        >>> src = '''
        ... schema ping {
        ...   version: 1
        ...   fields:
        ...     msg: string required
        ... }
        ... '''
        >>> with tempfile.NamedTemporaryFile(suffix=".rschema", mode="w",
        ...                                  delete=False) as tmp:
        ...     _ = tmp.write(src)
        ...     path = tmp.name
        >>> schema = RelaySchema.from_file(path)
        >>> schema.name
        'ping'
        """
        p = Path(path)
        if not p.exists():
            raise ParseError(
                f"Schema file not found: {path}",
                details={"path": str(path)},
            )
        raw_text = p.read_text(encoding="utf-8")
        schema = _parse_rschema_text(raw_text)
        schema.raw_text = raw_text
        return schema


# ---------------------------------------------------------------------------
# .rschema parser
# ---------------------------------------------------------------------------


def _parse_field_dict(d: dict[str, Any]) -> SchemaField:
    """Convert a raw field dict (from JSON or ``from_dict``) to a ``SchemaField``.

    Parameters
    ----------
    d : dict
        Must contain ``name`` and ``type``; optional ``required`` and ``fields``.

    Returns
    -------
    SchemaField

    Raises
    ------
    ParseError
        If required keys are absent.
    """
    try:
        name = d["name"]
        type_name = d["type"]
    except KeyError as exc:
        raise ParseError(
            f"Field definition missing key: {exc}",
            details={"field_dict": d},
        ) from exc

    required = bool(d.get("required", True))
    nested: list[SchemaField] = [
        _parse_field_dict(fd) for fd in d.get("fields", [])
    ]
    return SchemaField(
        name=name,
        type_name=type_name,
        required=required,
        nested_fields=nested,
    )


def _parse_rschema_text(text: str) -> RelaySchema:  # noqa: C901 (complex but straightforward)
    """Parse the ``.rschema`` text format into a ``RelaySchema``.

    The grammar is:

    .. code-block:: text

        schema <name> {
          version: <int>
          fields:
            <name>: <type> [required|optional] [{ ... }]
          ...
        }

        enum <Name> {
          value1
          value2
          ...
        }

    Parameters
    ----------
    text : str
        Complete ``.rschema`` source.

    Returns
    -------
    RelaySchema

    Raises
    ------
    ParseError
        On any syntax error.
    """
    lines = text.splitlines()
    schema_name: str | None = None
    schema_version: int = 1
    top_fields: list[SchemaField] = []
    enums: dict[str, list[str]] = {}

    i = 0
    n = len(lines)

    def skip_blank() -> None:
        nonlocal i
        while i < n and not lines[i].strip():
            i += 1

    def current_indent(line: str) -> int:
        return len(line) - len(line.lstrip())

    skip_blank()

    while i < n:
        raw = lines[i]
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue

        # --- schema block ---
        m = re.match(r"^schema\s+(\w+)\s*\{", stripped)
        if m:
            schema_name = m.group(1)
            i += 1
            while i < n:
                inner = lines[i]
                inner_stripped = inner.strip()
                if inner_stripped == "}":
                    i += 1
                    break
                if not inner_stripped or inner_stripped.startswith("#"):
                    i += 1
                    continue

                # version line
                mv = re.match(r"version\s*:\s*(\d+)", inner_stripped)
                if mv:
                    schema_version = int(mv.group(1))
                    i += 1
                    continue

                # fields: block
                if inner_stripped == "fields:":
                    i += 1
                    fields_indent: int | None = None
                    while i < n:
                        fline = lines[i]
                        fstripped = fline.strip()
                        if not fstripped or fstripped.startswith("#"):
                            i += 1
                            continue
                        fline_indent = current_indent(fline)
                        if fields_indent is None:
                            fields_indent = fline_indent
                        if fline_indent < fields_indent:
                            break
                        parsed, i = _parse_field_line(lines, i, fline_indent, n)
                        top_fields.append(parsed)
                    continue

                i += 1
            continue

        # --- enum block ---
        em = re.match(r"^enum\s+(\w+)\s*\{", stripped)
        if em:
            enum_name = em.group(1)
            values: list[str] = []
            i += 1
            while i < n:
                ev_line = lines[i].strip()
                if ev_line == "}":
                    i += 1
                    break
                if ev_line and not ev_line.startswith("#"):
                    values.append(ev_line)
                i += 1
            enums[enum_name] = values
            continue

        i += 1

    if schema_name is None:
        raise ParseError(
            "No 'schema <name> { ... }' block found in .rschema source",
        )

    return RelaySchema(
        name=schema_name,
        version=schema_version,
        fields=top_fields,
        enums=enums,
    )


def _parse_field_line(
    lines: list[str],
    i: int,
    base_indent: int,
    n: int,
) -> tuple[SchemaField, int]:
    """Parse a single field declaration line (and optional nested block).

    Parameters
    ----------
    lines : list of str
        All source lines.
    i : int
        Index of the current line.
    base_indent : int
        Indentation level of this field.
    n : int
        Total number of lines.

    Returns
    -------
    tuple of (SchemaField, int)
        The parsed field and the next line index.

    Raises
    ------
    ParseError
        On syntax errors.
    """
    raw = lines[i]
    stripped = raw.strip()

    # Pattern: name: type [required|optional]
    m = re.match(r"^(\w+)\s*:\s*(\S+(?:<[^>]+>)?(?:\[\S+\])?)\s*(required|optional)?", stripped)
    if not m:
        raise ParseError(
            f"Cannot parse field declaration: {stripped!r}",
            details={"line": i + 1, "content": stripped},
        )

    field_name = m.group(1)
    type_name = m.group(2)
    req_str = (m.group(3) or "required").lower()
    required = req_str == "required"

    i += 1
    nested_fields: list[SchemaField] = []

    # Check for nested block on next lines (indented deeper)
    while i < n:
        next_raw = lines[i]
        next_stripped = next_raw.strip()
        if not next_stripped or next_stripped.startswith("#"):
            i += 1
            continue
        next_indent = len(next_raw) - len(next_raw.lstrip())
        if next_indent <= base_indent:
            break
        # Nested field
        child, i = _parse_field_line(lines, i, next_indent, n)
        nested_fields.append(child)

    return SchemaField(
        name=field_name,
        type_name=type_name,
        required=required,
        nested_fields=nested_fields,
    ), i


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

__all__ = [
    "SchemaField",
    "RelaySchema",
]
