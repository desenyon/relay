"""
Relay CLI entry-point.

Registers all sub-commands and exposes the top-level ``relay`` Click group.
Install via ``pyproject.toml``::

    [project.scripts]
    relay = "relay.cli.main:cli"

Usage
-----
.. code-block:: console

    relay --version
    relay inspect <file.relay>
    relay validate <file.relay> --schema <schema_id>
    relay convert <file> --from json --to relay --schema <schema_id>
    relay schema register <file.rschema>
    relay schema list
    relay schema show <name:hash>
    relay schema hash <file.rschema>
    relay bench --iterations 10000 --payload-size medium --compare both
"""

from __future__ import annotations

import importlib.metadata

import click

from .commands.inspect import inspect_cmd
from .commands.validate import validate_cmd
from .commands.convert import convert_cmd
from .commands.schema import schema_group
from .commands.bench import bench_cmd


def _get_version() -> str:
    """Return the installed relay-format package version.

    Returns
    -------
    str
        Version string, e.g. ``"0.1.0"``, or ``"unknown"`` if the package
        metadata cannot be found (e.g. during development without a full
        install).
    """
    try:
        return importlib.metadata.version("relay-format")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


@click.group(name="relay", context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(
    version=_get_version(),
    prog_name="relay",
    message="%(prog)s %(version)s",
)
def cli() -> None:
    """Relay — production-grade data interchange format for agentic AI runtimes.

    Use ``relay <command> --help`` for detailed help on any sub-command.

    Examples
    --------
    .. code-block:: console

        relay inspect message.relay
        relay validate message.relay --schema agent_tool_call:a3f2bc01
        relay convert payload.json --from json --to relay --schema my_schema:abcd1234
        relay schema list
        relay bench --compare both
    """


# Register all sub-commands and groups.
cli.add_command(inspect_cmd, name="inspect")
cli.add_command(validate_cmd, name="validate")
cli.add_command(convert_cmd, name="convert")
cli.add_command(schema_group, name="schema")
cli.add_command(bench_cmd, name="bench")


__all__ = ["cli"]
