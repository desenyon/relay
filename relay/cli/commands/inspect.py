"""
``relay inspect`` command.

Pretty-prints a binary Relay message file using rich for colour output.

Usage
-----
.. code-block:: console

    relay inspect <file.relay>
    relay inspect <file.relay> --format json
    relay inspect <file.relay> --format text
    relay inspect <file.relay> --schema agent_tool_call:a3f2bc01

Output modes
------------
pretty (default)
    Rich colour-coded tree: field names in cyan, type tags in yellow,
    values in green.  Nested objects become tree children.
json
    Plain JSON representation of all decoded fields written to stdout.
text
    Relay text encoding (``.relay`` format) written to stdout.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.tree import Tree

console = Console()

# ---------------------------------------------------------------------------
# Type-tag display names (kept local to avoid circular imports at load time)
# ---------------------------------------------------------------------------

_TAG_NAMES: dict[int, str] = {
    0x01: "null",
    0x02: "bool",
    0x03: "int8",
    0x04: "int16",
    0x05: "int32",
    0x06: "int64",
    0x07: "uint8",
    0x08: "uint16",
    0x09: "uint32",
    0x0A: "uint64",
    0x0B: "float32",
    0x0C: "float64",
    0x0D: "string",
    0x0E: "bytes",
    0x0F: "array",
    0x10: "object",
    0x11: "uuid",
    0x12: "datetime",
    0x13: "uri",
    0x14: "vector",
    0x15: "enum",
    0x16: "code_block",
    0x17: "markdown_block",
    0x18: "ref",
    0x19: "delta_op",
}

_MSG_TYPE_NAMES: dict[int, str] = {
    0x0001: "FULL",
    0x0002: "DELTA",
    0x0003: "REF_ONLY",
    0x0004: "SCHEMA_DEF",
    0x0005: "ERROR",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tag_name(tag: int) -> str:
    """Return the human-readable name for a type-tag byte.

    Parameters
    ----------
    tag : int
        Type-tag byte value.

    Returns
    -------
    str
        Symbolic name or ``"unknown(0xNN)"``.
    """
    return _TAG_NAMES.get(tag, f"unknown(0x{tag:02X})")


def _value_repr(type_tag: int, value: Any) -> str:
    """Produce a concise string representation of a decoded Relay value.

    Parameters
    ----------
    type_tag : int
        The Relay type-tag byte.
    value : Any
        The decoded Python value.

    Returns
    -------
    str
        A short, human-readable representation suitable for tree display.
    """
    if type_tag == 0x01:
        return "null"
    if type_tag == 0x02:
        return str(value)
    if type_tag in (
        0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0A,
    ):
        return str(int(value))
    if type_tag in (0x0B, 0x0C):
        return str(float(value))
    if type_tag == 0x0D:
        text = str(value)
        return repr(text[:80] + ("…" if len(text) > 80 else ""))
    if type_tag == 0x0E:
        raw = bytes(value) if not isinstance(value, bytes) else value
        return f"<bytes len={len(raw)}>"
    if type_tag == 0x11:
        return str(value)
    if type_tag == 0x12:
        return str(value)
    if type_tag == 0x13:
        return str(value)
    if type_tag == 0x14:
        try:
            elements = list(value)
            preview = elements[:4]
            suffix = ", …" if len(elements) > 4 else ""
            return f"vector[{len(elements)}]({', '.join(str(x) for x in preview)}{suffix})"
        except Exception:
            return str(value)
    if type_tag == 0x15:
        return str(value)
    if type_tag == 0x16:
        if isinstance(value, dict):
            lang = value.get("lang", "")
            code_len = len(value.get("code", ""))
            return f"code_block<{lang}> ({code_len} chars)"
        if hasattr(value, "lang") and hasattr(value, "code"):
            return f"code_block<{getattr(value, 'lang', '')}> ({len(getattr(value, 'code', ''))} chars)"
        return str(value)
    if type_tag == 0x17:
        text = str(value)
        return f"markdown ({len(text)} chars)"
    if type_tag == 0x18:
        return f"$ref {value}"
    if type_tag == 0x19:
        if isinstance(value, dict):
            op = value.get("op", "?")
            path = value.get("field_path", "")
            return f"delta_op {op} {path}"
        return str(value)
    if type_tag == 0x0F:
        n = len(value) if hasattr(value, "__len__") else "?"
        return f"array[{n}]"
    if type_tag == 0x10:
        n = len(value) if hasattr(value, "__len__") else "?"
        return f"object({n} fields)"
    return repr(value)[:80]


def _append_relay_fields(parent: Tree, fields: list[Any]) -> None:
    """Attach :class:`~relay.types.RelayField` nodes (and children) to *parent*."""
    from relay.types import RelayField

    for f in fields:
        if not isinstance(f, RelayField):
            continue
        type_tag = int(f.type_tag)
        value = f.value
        tag_label = _tag_name(type_tag)
        val_repr = _value_repr(type_tag, value)
        label = (
            f"[cyan]{f.name}[/cyan] "
            f"[yellow]({tag_label})[/yellow] "
            f"[green]{val_repr}[/green]"
        )
        child = parent.add(label)

        if type_tag == 0x10 and isinstance(value, list):
            _append_relay_fields(child, value)

        elif type_tag == 0x0F and isinstance(value, list):
            for idx, item in enumerate(value):
                if isinstance(item, RelayField):
                    itag = int(item.type_tag)
                    ival = item.value
                else:
                    itag, ival = 0x0D, item
                item_label = (
                    f"[cyan][{idx}][/cyan] "
                    f"[yellow]({_tag_name(itag)})[/yellow] "
                    f"[green]{_value_repr(itag, ival)}[/green]"
                )
                child.add(item_label)

        elif type_tag == 0x16 and isinstance(value, dict):
            lang = value.get("lang", "")
            code = value.get("code", "")
            child.add(f"[dim]lang:[/dim] [yellow]{lang}[/yellow]")
            for i, line in enumerate(code.splitlines()[:10]):
                child.add(f"[dim]{i+1:>3}[/dim]  {line}")
            if len(code.splitlines()) > 10:
                child.add("[dim]… (truncated)[/dim]")


def _render_pretty(message: Any) -> None:
    """Render a decoded RelayMessage as a colour-coded rich tree.

    Parameters
    ----------
    message : RelayMessage
        Decoded message object.
    """
    msg_type_name = _MSG_TYPE_NAMES.get(
        getattr(message, "message_type", 0), "UNKNOWN"
    )
    schema_hash = getattr(message, "schema_hash", b"\x00\x00\x00\x00")
    if isinstance(schema_hash, bytes):
        hash_hex = schema_hash.hex()
    else:
        hash_hex = str(schema_hash)

    title = (
        f"[bold magenta]Relay Message[/bold magenta] "
        f"[white]type=[/white][yellow]{msg_type_name}[/yellow] "
        f"[white]schema=[/white][blue]{hash_hex}[/blue]"
    )
    tree = Tree(title)
    _append_relay_fields(tree, message.fields)
    console.print(tree)


def _render_json(message: Any) -> None:
    """Render a decoded RelayMessage as indented JSON to stdout.

    Parameters
    ----------
    message : RelayMessage
        Decoded message object.
    """
    import json

    from relay.compat.json_compat import _message_to_json_dict

    data = _message_to_json_dict(message)
    console.print_json(json.dumps(data, indent=2, default=str))


def _render_text(message: Any) -> None:
    """Render a decoded RelayMessage as Relay text encoding.

    Parameters
    ----------
    message : RelayMessage
        Decoded message object.
    """
    from relay.payload import message_to_payload_dict
    from relay.registry import default_registry
    from relay.text_encoder import encode_text

    try:
        schema = default_registry.get_by_hash(message.schema_hash.hex())
    except Exception:
        console.print(
            "[yellow]Cannot load schema for text output; "
            "register the schema or use --schema name:hash[/yellow]"
        )
        raise
    obj = message_to_payload_dict(message)
    text = encode_text(obj, schema, message_type=message.message_type)
    console.print(text)


# ---------------------------------------------------------------------------
# Click command
# ---------------------------------------------------------------------------


@click.command("inspect")
@click.argument("file", type=click.Path(exists=True, dir_okay=False, readable=True))
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["pretty", "json", "text"], case_sensitive=False),
    default="pretty",
    show_default=True,
    help="Output format: 'pretty' renders a colour tree, 'json' emits JSON, 'text' emits Relay text encoding.",
)
@click.option(
    "--schema",
    "schema_id",
    default=None,
    metavar="NAME:HASH",
    help="Override the schema used for display (e.g. 'agent_tool_call:a3f2bc01').  "
    "If omitted the schema embedded in the frame header is used.",
)
def inspect_cmd(file: str, output_format: str, schema_id: str | None) -> None:
    """Inspect and pretty-print a binary Relay message file.

    Reads the binary ``.relay`` file at FILE, decodes it, and renders the
    contents according to the chosen output format.

    Parameters
    ----------
    file : str
        Path to a binary Relay file.
    output_format : str
        One of ``pretty``, ``json``, or ``text``.
    schema_id : str or None
        Optional schema override in ``name:hash`` format.

    Examples
    --------
    .. code-block:: console

        relay inspect message.relay
        relay inspect message.relay --format json
        relay inspect message.relay --schema agent_tool_call:a3f2bc01
    """
    from relay.errors import RelayError  # type: ignore[import-untyped]

    path = Path(file)

    try:
        raw = path.read_bytes()
    except OSError as exc:
        console.print(f"[bold red]Error:[/bold red] Cannot read file: {exc}")
        sys.exit(1)

    # --- Optionally load a specific schema from the registry ----------------
    override_schema = None
    if schema_id is not None:
        try:
            from relay.registry import default_registry

            parts = schema_id.split(":", 1)
            if len(parts) == 2:
                override_schema = default_registry.get(parts[0], parts[1])
            else:
                override_schema = default_registry.get_by_hash(parts[0].lower())
        except Exception as exc:
            console.print(
                f"[yellow]Warning:[/yellow] Could not load schema '{schema_id}': {exc}"
            )

    # --- Decode --------------------------------------------------------------
    try:
        from relay.decoder import decode  # type: ignore[import-untyped]

        message = decode(raw, schema=override_schema)
    except RelayError as exc:
        console.print(f"[bold red]Relay decode error ({exc.code}):[/bold red] {exc.message}")
        if exc.field_path:
            console.print(f"  [dim]Field path:[/dim] {exc.field_path}")
        if exc.details:
            console.print(f"  [dim]Details:[/dim] {exc.details}")
        sys.exit(1)
    except Exception as exc:
        console.print(f"[bold red]Unexpected error:[/bold red] {exc}")
        sys.exit(1)

    # --- Render --------------------------------------------------------------
    fmt = output_format.lower()
    if fmt == "pretty":
        _render_pretty(message)
    elif fmt == "json":
        _render_json(message)
    elif fmt == "text":
        _render_text(message)
    else:  # pragma: no cover
        console.print(f"[bold red]Unknown format:[/bold red] {output_format}")
        sys.exit(1)


__all__ = ["inspect_cmd"]
