"""
Relay text-format decoder (``.relay`` files) → :class:`~relay.types.RelayMessage`.

Supports ``FULL``, ``DELTA``, and ``REF_ONLY`` text documents.
"""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

import numpy as np

from relay.decoder import decode
from relay.delta import delta
from relay.encoder import encode
from relay.errors import ParseError
from relay.registry import SchemaRegistry, get_default_registry
from relay.schema import RelaySchema as SourceSchema
from relay.schema import SchemaField as SourceField
from relay.types import (
    CodeBlock,
    DeltaOp,
    DeltaOpType,
    EnumValue,
    MarkdownBlock,
    MessageType,
    RelayMessage,
    RelayRef,
    TypeTag,
    VectorDtype,
    VectorValue,
)


def decode_text(text: str, *, registry: SchemaRegistry | None = None) -> RelayMessage:
    """Parse a ``.relay`` text document and return a decoded message.

    Supports ``@type FULL`` (payload fields), ``DELTA`` (``@base`` + op lines),
    and ``REF_ONLY`` (a single ``ref`` field line).

    Parameters
    ----------
    text : str
        Full ``.relay`` source.
    registry : SchemaRegistry, optional
        Resolves ``@schema name:hash``.

    Returns
    -------
    RelayMessage

    Raises
    ------
    ParseError
        If the preamble or body is malformed.
    """
    reg = registry or get_default_registry()
    lines = [ln.rstrip("\r") for ln in text.splitlines()]
    if not lines:
        raise ParseError("Empty document")

    i = 0
    if not lines[i].startswith("@relay "):
        raise ParseError("First line must be @relay <version>")
    i += 1

    if i >= len(lines) or not lines[i].startswith("@schema "):
        raise ParseError("Missing @schema line")
    sm = re.match(r"@schema\s+([\w\-]+):([0-9a-fA-F]{8})\s*$", lines[i].strip())
    if not sm:
        raise ParseError(f"Bad @schema line: {lines[i]!r}")
    s_name, s_hash = sm.group(1), sm.group(2).lower()
    i += 1

    if i >= len(lines) or not lines[i].startswith("@type "):
        raise ParseError("Missing @type line")
    tm = re.match(r"@type\s+(\w+)\s*$", lines[i].strip())
    if not tm:
        raise ParseError(f"Bad @type line: {lines[i]!r}")
    type_name = tm.group(1).upper()
    try:
        msg_type = MessageType[type_name]
    except KeyError as exc:
        raise ParseError(f"Unknown message type {type_name!r}") from exc
    i += 1

    base_ref: RelayRef | None = None
    if msg_type == MessageType.DELTA:
        if i >= len(lines) or not lines[i].strip().startswith("@base "):
            raise ParseError("DELTA requires @base line after @type")
        bm = re.match(r"@base\s+(.+)$", lines[i].strip())
        if not bm:
            raise ParseError(f"Bad @base line: {lines[i]!r}")
        base_ref = _parse_ref_token(bm.group(1).strip())
        i += 1

    if msg_type not in (
        MessageType.FULL,
        MessageType.DELTA,
        MessageType.REF_ONLY,
    ):
        raise ParseError(
            f"decode_text does not support message type {msg_type.name}",
            details={"type": msg_type.name},
        )

    if i >= len(lines) or lines[i].strip() != "":
        raise ParseError("Mandatory blank line must follow the preamble")
    i += 1

    schema = reg.get(s_name, s_hash)
    body_lines = lines[i:]

    if msg_type == MessageType.FULL:
        obj = _parse_full_body(body_lines, schema)
        binary = encode(obj, schema)
        return decode(binary, schema=schema, validate=True)

    if msg_type == MessageType.DELTA:
        if base_ref is None:
            raise ParseError("DELTA missing base ref")
        ops = [_parse_delta_op_line(ln) for ln in body_lines if ln.strip()]
        base = RelayMessage(
            message_type=MessageType.FULL,
            schema_hash=schema.hash_bytes(),
            fields=[],
            delta_base_ref=base_ref,
        )
        binary = delta(base, ops, schema)
        return decode(binary, schema=schema, validate=False)

    # REF_ONLY
    name, ref_val = _parse_ref_only_body(body_lines, schema)
    binary = _encode_ref_only_binary(name, ref_val, schema)
    return decode(binary, schema=schema, validate=False)


def _encode_ref_only_binary(name: str, ref: RelayRef, schema: SourceSchema) -> bytes:
    from relay.encoder import _build_frame, _encode_ref_bytes, _pack_field_frame
    from relay.schema_compile import compile_schema

    compiled = compile_schema(schema)
    sf = compiled.field_by_name(name)
    if sf is None or sf.type_tag != TypeTag.REF:
        raise ParseError(
            f"REF_ONLY requires a top-level ref field named {name!r} in schema",
        )
    body = _encode_ref_bytes(ref)
    payload = _pack_field_frame(sf.field_id, int(TypeTag.REF), body)
    return _build_frame(MessageType.REF_ONLY, compiled.schema_hash, payload)


def _parse_ref_only_body(lines: list[str], schema: SourceSchema) -> tuple[str, RelayRef]:
    nonempty = [ln for ln in lines if ln.strip()]
    if len(nonempty) != 1:
        raise ParseError(
            f"REF_ONLY body must contain exactly one field line, got {len(nonempty)}",
        )
    raw = nonempty[0].strip()
    m = re.match(r"^(\w+):\s+ref\s+(.+)$", raw)
    if not m:
        raise ParseError(f"REF_ONLY expects 'name: ref $ref ...', got {raw!r}")
    fname = m.group(1)
    if schema.get_field(fname) is None:
        raise ParseError(f"Unknown field {fname!r}")
    return fname, _parse_ref_token(m.group(2).strip())


def _parse_delta_op_line(line: str) -> DeltaOp:
    s = line.strip()
    if s.startswith("DEL "):
        return DeltaOp(DeltaOpType.DEL, s[4:].strip(), None, None)
    if s.startswith("SET "):
        path, tname, val_s = _split_delta_set_app(s[4:], "SET")
        tt = _scalar_type_name_to_tag(tname)
        val = _parse_delta_scalar(tname, val_s)
        return DeltaOp(DeltaOpType.SET, path, tt, val)
    if s.startswith("APP "):
        path, tname, val_s = _split_delta_set_app(s[4:], "APP")
        tt = _scalar_type_name_to_tag(tname)
        val = _parse_delta_scalar(tname, val_s)
        return DeltaOp(DeltaOpType.APP, path, tt, val)
    if s.startswith("SPL "):
        return _parse_spl_line(s[4:])
    raise ParseError(f"Unrecognised delta line: {line!r}")


def _split_delta_set_app(rest: str, op: str) -> tuple[str, str, str]:
    tokens = rest.split()
    if len(tokens) < 3:
        raise ParseError(f"Invalid {op} line: {rest!r}")
    for j in range(1, len(tokens)):
        tname = tokens[j]
        if tname in _DELTA_TYPE_NAMES or tname.startswith("enum<"):
            path = " ".join(tokens[:j])
            val_s = " ".join(tokens[j + 1 :])
            return path, tname, val_s
    raise ParseError(f"Cannot find type token in delta line: {rest!r}")


_DELTA_TYPE_NAMES: set[str] = {
    "null",
    "bool",
    "enum",
    "int8",
    "int16",
    "int32",
    "int64",
    "uint8",
    "uint16",
    "uint32",
    "uint64",
    "float32",
    "float64",
    "string",
    "bytes",
    "uuid",
    "uri",
}


def _scalar_type_name_to_tag(tname: str) -> TypeTag:
    if tname.startswith("enum<") or tname == "enum":
        return TypeTag.ENUM
    try:
        return TypeTag[tname.upper()]
    except KeyError as exc:
        raise ParseError(f"Unknown delta value type {tname!r}") from exc


def _parse_delta_scalar(tname: str, val_s: str) -> Any:
    if tname == "null" or val_s == "null":
        return None
    if tname == "bool":
        return val_s.lower() in ("true", "1", "yes")
    if tname in _DELTA_TYPE_NAMES and "int" in tname:
        return int(val_s.split()[0])
    if tname in ("float32", "float64"):
        return float(val_s.split()[0])
    if tname == "string":
        val, _ = _read_quoted_string(val_s.strip(), 0)
        return val
    if tname == "uuid":
        val, _ = _read_quoted_string(val_s.strip(), 0)
        return UUID(val)
    if tname == "enum":
        val, _ = _read_quoted_string(val_s.strip(), 0)
        return EnumValue(name=val, index=0)
    if tname.startswith("enum<"):
        dot = val_s.find(".")
        sym = val_s[dot + 1 :].strip() if dot >= 0 else val_s.strip()
        return EnumValue(name=sym, index=0)
    if tname == "bytes":
        return bytes.fromhex(val_s.strip().strip('"'))
    raise ParseError(f"Unsupported delta scalar type {tname!r}")


def _parse_spl_line(rest: str) -> DeltaOp:
    m = re.match(
        r"^(\S+)\s+(\d+)\s+(\d+)\s+(\S+)\s+(.*)$",
        rest.strip(),
    )
    if not m:
        raise ParseError(f"Invalid SPL line: {rest!r}")
    path, start_s, end_s, tname, val_s = m.groups()
    tt = _scalar_type_name_to_tag(tname)
    val = _parse_delta_scalar(tname, val_s)
    return DeltaOp(
        op_type=DeltaOpType.SPL,
        field_path=path,
        type_tag=tt,
        value=val,
        splice_start=int(start_s),
        splice_end=int(end_s),
    )


def _parse_full_body(lines: list[str], schema: SourceSchema) -> dict[str, Any]:
    root: dict[str, Any] = {}
    i = 0
    while i < len(lines):
        if not lines[i].strip():
            i += 1
            continue
        indent = len(lines[i]) - len(lines[i].lstrip(" "))
        if indent != 0:
            raise ParseError(f"Top-level field must start at column 0: {lines[i]!r}")
        name, i, value = _parse_field_lines(lines, i, schema, None)
        root[name] = value
    _fix_enum_indices(root, schema)
    return root


def _parse_field_lines(
    lines: list[str],
    i: int,
    schema: SourceSchema,
    parent: SourceField | None,
) -> tuple[str, int, Any]:
    line = lines[i]
    stripped = line.strip()
    m = re.match(r"^(\w+):\s+(.*)$", stripped)
    if not m:
        raise ParseError(f"Bad field line: {stripped!r}")
    name = m.group(1)
    rhs = m.group(2).strip()

    sf: SourceField | None = None
    if parent is None:
        sf = schema.get_field(name)
        if sf is None:
            raise ParseError(f"Unknown field {name!r}")
    else:
        for c in parent.nested_fields:
            if c.name == name:
                sf = c
                break
        if sf is None:
            raise ParseError(f"Unknown nested field {name!r}")

    type_str = sf.type_name

    arr_m = re.match(r"^array<(.+)>$", type_str.strip(), re.IGNORECASE)
    if arr_m:
        inner_type = arr_m.group(1).strip()
        i += 1
        child_indent: int | None = None
        by_index: dict[int, Any] = {}
        while i < len(lines):
            raw = lines[i]
            if not raw.strip():
                i += 1
                continue
            ind = len(raw) - len(raw.lstrip(" "))
            if child_indent is None:
                child_indent = ind
            if ind < child_indent:
                break
            if ind != child_indent:
                raise ParseError(f"Inconsistent array element indent: {raw!r}")
            stripped_c = raw.strip()
            em = re.match(r"^\[(\d+)\]:\s+(\S+)\s+(.+)$", stripped_c)
            if not em:
                raise ParseError(f"Bad array element line: {raw!r}")
            el_idx = int(em.group(1))
            elem_type = em.group(2)
            rhs_tail = em.group(3).strip()
            if elem_type.lower() != inner_type.lower():
                raise ParseError(
                    f"Array element type {elem_type!r} does not match {inner_type!r}",
                )
            val, _ = _parse_inline_value(lines, i, elem_type, f"{elem_type} {rhs_tail}")
            by_index[el_idx] = val
            i += 1
        if not by_index:
            return name, i, []
        out = [by_index[j] for j in range(len(by_index))]
        return name, i, out

    if type_str == "object":
        i += 1
        child_indent: int | None = None
        obj: dict[str, Any] = {}
        while i < len(lines):
            raw = lines[i]
            if not raw.strip():
                i += 1
                continue
            ind = len(raw) - len(raw.lstrip(" "))
            if child_indent is None:
                child_indent = ind
            if ind < child_indent:
                break
            if ind != child_indent:
                raise ParseError(f"Inconsistent nested indent: {raw!r}")
            cn, i, val = _parse_field_lines(lines, i, schema, sf)
            obj[cn] = val
        return name, i, obj

    if type_str.startswith("markdown_block"):
        ni, block = _parse_markdown_block(lines, i + 1)
        return name, ni, block

    if type_str.startswith("code_block"):
        ni, block = _parse_code_block(lines, i + 1, type_str)
        return name, ni, block

    val, ni = _parse_inline_value(lines, i, type_str, rhs)
    return name, ni, val


def _parse_markdown_block(lines: list[str], i: int) -> tuple[int, MarkdownBlock]:
    if i >= len(lines) or '"""' not in lines[i]:
        raise ParseError("markdown_block expects opening triple quotes")
    content: list[str] = []
    i += 1
    while i < len(lines):
        if lines[i].strip() == '"""':
            return i + 1, MarkdownBlock(content="\n".join(content))
        pl = len(lines[i]) - len(lines[i].lstrip(" "))
        content.append(lines[i][pl + 2 :] if pl >= 2 else lines[i])
        i += 1
    raise ParseError("Unterminated markdown_block")


def _parse_code_block(lines: list[str], i: int, type_str: str) -> tuple[int, CodeBlock]:
    lm = re.match(r"code_block<([^>]+)>", type_str)
    lang = lm.group(1) if lm else ""
    if i >= len(lines) or "```" not in lines[i]:
        raise ParseError("code_block expects opening ```")
    code: list[str] = []
    i += 1
    while i < len(lines):
        if lines[i].strip() == "```":
            return i + 1, CodeBlock(lang=lang, code="\n".join(code))
        pl = len(lines[i]) - len(lines[i].lstrip(" "))
        code.append(lines[i][pl + 2 :] if pl >= 2 else lines[i])
        i += 1
    raise ParseError("Unterminated code_block")


def _parse_inline_value(
    lines: list[str],
    i: int,
    type_str: str,
    rhs: str,
) -> tuple[Any, int]:
    if type_str.startswith("enum<"):
        dot = rhs.find(".")
        if dot < 0:
            raise ParseError(f"enum field needs symbolic suffix: {rhs!r}")
        sym = rhs[dot + 1 :].strip()
        return EnumValue(name=sym, index=0), i + 1

    if rhs.startswith(type_str):
        rest = rhs[len(type_str) :].lstrip()
    else:
        rest = rhs

    if type_str.startswith("vector<"):
        inner = type_str[7 : type_str.rindex(">")]
        parts = [p.strip() for p in inner.split(",")]
        dtype_s = parts[0].lower()
        vm = re.search(r"\[([^\]]*)\]", rest)
        if not vm:
            raise ParseError("vector value must use [..] syntax")
        nums = [float(x.strip()) for x in vm.group(1).split(",") if x.strip()]
        vd = {
            "float16": VectorDtype.FLOAT16,
            "float32": VectorDtype.FLOAT32,
            "float64": VectorDtype.FLOAT64,
            "int8": VectorDtype.INT8,
        }[dtype_s]
        arr = np.array(nums, dtype=_np_dt(vd))
        return VectorValue(dtype=vd, dim=len(nums), data=arr), i + 1

    if type_str in ("string", "uri", "uuid", "datetime"):
        src = rest if rest.startswith('"') else ""
        if not src.startswith('"'):
            raise ParseError(f"Expected quoted value for {type_str}")
        val, _ = _read_quoted_string(src, 0)
        if type_str == "uuid":
            return UUID(val), i + 1
        return val, i + 1

    if type_str == "bool":
        tok = rest.split()[0] if rest else ""
        return tok.lower() in ("true", "1", "yes"), i + 1

    if type_str == "null" or rest == "null":
        return None, i + 1

    if "int" in type_str:
        tok = rest.split()[0] if rest else ""
        return int(tok), i + 1

    if "float" in type_str:
        tok = rest.split()[0] if rest else ""
        return float(tok), i + 1

    if type_str == "ref":
        return _parse_ref_token(rest), i + 1

    if type_str == "bytes":
        hx = rest.strip().strip('"')
        return bytes.fromhex(hx), i + 1

    raise ParseError(f"Unsupported type for inline parse: {type_str!r}")


def _np_dt(vd: VectorDtype) -> type:
    return {
        VectorDtype.FLOAT16: np.float16,
        VectorDtype.FLOAT32: np.float32,
        VectorDtype.FLOAT64: np.float64,
        VectorDtype.INT8: np.int8,
    }[vd]


def _read_quoted_string(s: str, start: int) -> tuple[str, int]:
    if start >= len(s) or s[start] != '"':
        raise ParseError("expected opening quote")
    out: list[str] = []
    i = start + 1
    while i < len(s):
        c = s[i]
        if c == "\\":
            i += 1
            if i < len(s):
                out.append(s[i])
                i += 1
            continue
        if c == '"':
            return "".join(out), i + 1
        out.append(c)
        i += 1
    raise ParseError("unterminated string")


def _parse_ref_token(s: str) -> RelayRef:
    m = re.match(
        r"\$ref\s+session:([0-9a-fA-F\-]+)\.call\[(\d+)\](?:\.(.*))?$",
        s.strip(),
    )
    if not m:
        raise ParseError(f"bad ref: {s!r}")
    return RelayRef(
        session_id=UUID(m.group(1)),
        call_index=int(m.group(2)),
        field_path=m.group(3) or "",
    )


def _fix_enum_indices(obj: dict[str, Any], schema: SourceSchema) -> None:
    for sf in schema.fields:
        if sf.name not in obj:
            continue
        val = obj[sf.name]
        if sf.type_name.startswith("enum<") and isinstance(val, EnumValue):
            en = sf.enum_name or ""
            idx = schema.get_enum_index(en, val.name)
            obj[sf.name] = EnumValue(name=val.name, index=idx)
        elif sf.type_name == "object" and isinstance(val, dict):
            for nf in sf.nested_fields:
                if nf.name not in val:
                    continue
                nv = val[nf.name]
                if nf.type_name.startswith("enum<") and isinstance(nv, EnumValue):
                    en2 = nf.enum_name or ""
                    ix = schema.get_enum_index(en2, nv.name)
                    val[nf.name] = EnumValue(name=nv.name, index=ix)


__all__ = ["decode_text"]
