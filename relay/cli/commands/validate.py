"""``relay validate`` — decode and schema-check a binary message."""

from __future__ import annotations

import sys
from pathlib import Path

import click
from rich.console import Console

console = Console()


@click.command("validate")
@click.argument("file", type=click.Path(exists=True, dir_okay=False, readable=True))
@click.option(
    "--schema",
    "schema_id",
    required=False,
    default=None,
    metavar="NAME:HASH",
    help="Optional schema override (otherwise the header hash must resolve in the registry).",
)
def validate_cmd(file: str, schema_id: str | None) -> None:
    """Validate a binary Relay file against its schema."""
    from relay.decoder import decode
    from relay.errors import RelayError
    from relay.registry import default_registry

    raw = Path(file).read_bytes()
    override = None
    if schema_id:
        parts = schema_id.split(":", 1)
        if len(parts) == 2:
            override = default_registry.get(parts[0], parts[1])
        else:
            override = default_registry.get_by_hash(parts[0].lower())
    try:
        decode(raw, schema=override, validate=True)
    except RelayError as exc:
        console.print(f"[red]Invalid ({exc.code}):[/red] {exc.message}")
        sys.exit(1)
    console.print("[green]OK[/green] — message is valid.")


__all__ = ["validate_cmd"]
