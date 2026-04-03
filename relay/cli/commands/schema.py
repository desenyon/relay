"""``relay schema`` — register and inspect the local schema registry."""

from __future__ import annotations

import sys

import click
from rich.console import Console
from rich.table import Table

console = Console()


@click.group("schema")
def schema_group() -> None:
    """Manage the file-backed schema registry."""


@schema_group.command("register")
@click.argument("path", type=click.Path(exists=True, dir_okay=False))
def schema_register(path: str) -> None:
    """Register a ``.rschema`` file in the default registry."""
    from relay.errors import RelayError
    from relay.registry import default_registry
    from relay.schema import RelaySchema

    try:
        s = RelaySchema.from_file(path)
        key = default_registry.register(s)
    except RelayError as exc:
        console.print(f"[red]{exc.code}:[/red] {exc.message}")
        sys.exit(1)
    console.print(f"[green]Registered[/green] {key}")


@schema_group.command("list")
def schema_list() -> None:
    """List registered schemas."""
    from relay.registry import default_registry

    rows = default_registry.list()
    if not rows:
        console.print("(empty registry)")
        return
    table = Table(title="Relay schemas")
    table.add_column("Key")
    table.add_column("Version")
    table.add_column("Fields")
    for r in rows:
        table.add_row(r["key"], str(r["version"]), str(r["field_count"]))
    console.print(table)


@schema_group.command("show")
@click.argument("name_hash", metavar="NAME:HASH")
def schema_show(name_hash: str) -> None:
    """Pretty-print a registered schema."""
    from relay.errors import RelayError
    from relay.registry import default_registry

    parts = name_hash.split(":", 1)
    if len(parts) != 2:
        console.print("[red]Expected name:hash[/red]")
        sys.exit(1)
    try:
        s = default_registry.get(parts[0], parts[1])
    except RelayError as exc:
        console.print(f"[red]{exc.code}:[/red] {exc.message}")
        sys.exit(1)
    console.print(f"[bold]{s.name}[/bold] v{s.version} hash={s.hash()}")
    for f in s.fields:
        req = "req" if f.required else "opt"
        console.print(f"  • [cyan]{f.name}[/cyan] : {f.type_name} ({req})")


@schema_group.command("hash")
@click.argument("path", type=click.Path(exists=True, dir_okay=False))
def schema_hash(path: str) -> None:
    """Print the 4-byte schema hash for a ``.rschema`` file."""
    from relay.schema import RelaySchema

    s = RelaySchema.from_file(path)
    console.print(s.hash())


__all__ = ["schema_group"]
