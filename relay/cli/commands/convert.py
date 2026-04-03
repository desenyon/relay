"""``relay convert`` — translate between JSON, MessagePack, and Relay formats."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click
import msgpack
from rich.console import Console

console = Console()


@click.command("convert")
@click.argument("file", type=click.Path(exists=True, dir_okay=False, readable=True))
@click.option(
    "--from",
    "from_fmt",
    type=click.Choice(["json", "msgpack", "openai", "anthropic"], case_sensitive=False),
    required=True,
)
@click.option(
    "--to",
    "to_fmt",
    type=click.Choice(["relay", "relay-text", "json", "msgpack"], case_sensitive=False),
    required=True,
)
@click.option(
    "--schema",
    "schema_id",
    required=False,
    default=None,
    help="name:hash (required for --from json or msgpack).",
)
def convert_cmd(file: str, from_fmt: str, to_fmt: str, schema_id: str | None) -> None:
    """Convert *file* between supported formats."""
    from relay.compat import (
        anthropic_tool_use_schema,
        from_anthropic_tool_use,
        from_json,
        from_openai_tool_call,
        openai_tool_call_schema,
        to_json,
    )
    from relay.decoder import decode
    from relay.errors import RelayError
    from relay.payload import message_to_payload_dict
    from relay.registry import default_registry
    from relay.schema import RelaySchema
    from relay.text_encoder import encode_text

    raw_bytes = Path(file).read_bytes()

    def load_schema() -> RelaySchema:
        if not schema_id:
            raise click.ClickException("--schema is required when --from is json or msgpack")
        parts = schema_id.split(":", 1)
        if len(parts) == 2:
            return default_registry.get(parts[0], parts[1])
        return default_registry.get_by_hash(parts[0].lower())

    try:
        if from_fmt == "openai":
            relay_bytes = from_openai_tool_call(json.loads(raw_bytes.decode("utf-8")))
            src_schema = openai_tool_call_schema()
        elif from_fmt == "anthropic":
            relay_bytes = from_anthropic_tool_use(json.loads(raw_bytes.decode("utf-8")))
            src_schema = anthropic_tool_use_schema()
        elif from_fmt == "json":
            src_schema = load_schema()
            relay_bytes = from_json(json.loads(raw_bytes.decode("utf-8")), src_schema)
        elif from_fmt == "msgpack":
            src_schema = load_schema()
            root = msgpack.unpackb(raw_bytes, raw=False)
            if not isinstance(root, dict):
                raise click.ClickException("msgpack root must be a map")
            relay_bytes = from_json(root, src_schema)
        else:
            raise click.ClickException(f"Unsupported --from {from_fmt}")

        if to_fmt == "relay":
            sys.stdout.buffer.write(relay_bytes)
            return

        msg = decode(relay_bytes, schema=src_schema, validate=True)

        if to_fmt == "relay-text":
            console.print(encode_text(message_to_payload_dict(msg), src_schema), end="")
        elif to_fmt == "json":
            console.print(json.dumps(to_json(relay_bytes), indent=2))
        elif to_fmt == "msgpack":
            sys.stdout.buffer.write(msgpack.packb(to_json(relay_bytes)))
    except RelayError as exc:
        console.print(f"[red]{exc.code}:[/red] {exc.message}")
        sys.exit(1)


__all__ = ["convert_cmd"]
