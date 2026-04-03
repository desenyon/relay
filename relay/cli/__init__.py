"""
Relay CLI package.

The ``relay`` command is registered via the ``pyproject.toml`` entry-point::

    [project.scripts]
    relay = "relay.cli.main:cli"

Importing this package makes no side effects; the click group is only
activated when invoked from the command line.
"""
