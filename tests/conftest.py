"""
Shared pytest fixtures for the Relay test suite.

All fixtures are designed to be reusable across every test module.  Schemas
are constructed via ``RelaySchema.from_dict`` so the test suite does not
depend on any specific ``.rschema`` file being present on disk.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

# ---------------------------------------------------------------------------
# Schema fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def simple_schema():
    """A minimal schema with basic scalar fields used for type-level tests.

    Returns
    -------
    RelaySchema
        Schema named ``"simple"`` with fields: name (string, required),
        count (int32, required), flag (bool, optional), score (float64,
        optional), note (string, optional).
    """
    from relay.schema import RelaySchema

    return RelaySchema.from_dict(
        {
            "name": "simple",
            "version": 1,
            "fields": [
                {"name": "name", "type": "string", "required": True},
                {"name": "count", "type": "int32", "required": True},
                {"name": "flag", "type": "bool", "required": False},
                {"name": "score", "type": "float64", "required": False},
                {"name": "note", "type": "string", "required": False},
            ],
            "enums": {},
        }
    )


@pytest.fixture(scope="session")
def tool_call_schema():
    """Schema that mirrors the agent_tool_call fixture used in spec examples.

    Returns
    -------
    RelaySchema
        Schema with role (enum<MessageRole>, required), content
        (markdown_block, optional), tool_call (object, optional),
        result (object, optional).
    """
    from relay.schema import RelaySchema

    return RelaySchema.from_dict(
        {
            "name": "agent_tool_call",
            "version": 1,
            "fields": [
                {
                    "name": "role",
                    "type": "enum<MessageRole>",
                    "required": True,
                },
                {
                    "name": "content",
                    "type": "markdown_block",
                    "required": False,
                },
                {
                    "name": "tool_call",
                    "type": "object",
                    "required": False,
                    "fields": [
                        {"name": "id", "type": "uuid", "required": True},
                        {"name": "name", "type": "string", "required": True},
                        {
                            "name": "arguments",
                            "type": "object",
                            "required": True,
                            "fields": [
                                {
                                    "name": "discount_rate",
                                    "type": "float64",
                                    "required": False,
                                },
                                {
                                    "name": "cash_flows",
                                    "type": "array<float64>",
                                    "required": False,
                                },
                            ],
                        },
                    ],
                },
                {
                    "name": "result",
                    "type": "object",
                    "required": False,
                    "fields": [
                        {"name": "output", "type": "string", "required": True},
                        {"name": "error", "type": "string", "required": False},
                    ],
                },
            ],
            "enums": {
                "MessageRole": ["system", "user", "assistant", "tool"],
            },
        }
    )


@pytest.fixture(scope="session")
def openai_tool_call_schema():
    """Schema for wrapping an OpenAI tool-call response as a Relay message.

    Returns
    -------
    RelaySchema
        Schema named ``"openai_tool_call"`` with id, type, function fields.
    """
    from relay.schema import RelaySchema

    return RelaySchema.from_dict(
        {
            "name": "openai_tool_call",
            "version": 1,
            "fields": [
                {"name": "id", "type": "string", "required": True},
                {"name": "type", "type": "string", "required": True},
                {
                    "name": "function",
                    "type": "object",
                    "required": True,
                    "fields": [
                        {"name": "name", "type": "string", "required": True},
                        {"name": "arguments", "type": "string", "required": True},
                    ],
                },
            ],
            "enums": {},
        }
    )


@pytest.fixture(scope="session")
def anthropic_tool_use_schema():
    """Schema for wrapping an Anthropic tool-use block as a Relay message.

    Returns
    -------
    RelaySchema
        Schema named ``"anthropic_tool_use"`` with id, type, name, input fields.
    """
    from relay.schema import RelaySchema

    return RelaySchema.from_dict(
        {
            "name": "anthropic_tool_use",
            "version": 1,
            "fields": [
                {"name": "id", "type": "string", "required": True},
                {"name": "type", "type": "string", "required": True},
                {"name": "name", "type": "string", "required": True},
                {
                    "name": "input",
                    "type": "object",
                    "required": True,
                    "fields": [
                        {"name": "query", "type": "string", "required": False},
                        {"name": "limit", "type": "int32", "required": False},
                        {"name": "verbose", "type": "bool", "required": False},
                    ],
                },
            ],
            "enums": {},
        }
    )


@pytest.fixture(scope="session")
def sample_schema(simple_schema):
    """Alias for ``simple_schema`` for tests that need a generic schema.

    Returns
    -------
    RelaySchema
    """
    return simple_schema


# ---------------------------------------------------------------------------
# Sample message dict fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def simple_message_dict() -> dict[str, Any]:
    """A valid Python dict conforming to ``simple_schema``.

    Returns
    -------
    dict
    """
    return {
        "name": "relay-test",
        "count": 42,
        "flag": True,
        "score": 3.14,
        "note": "hello world",
    }


@pytest.fixture(scope="session")
def tool_call_message_dict() -> dict[str, Any]:
    """A Python dict conforming to ``tool_call_schema``.

    Returns
    -------
    dict
    """
    from relay.types import EnumValue, MarkdownBlock

    return {
        "role": EnumValue(name="assistant", index=2),
        "content": MarkdownBlock(content="Here is the result."),
        "tool_call": {
            "id": UUID("550e8400-e29b-41d4-a716-446655440000"),
            "name": "calculate_npv",
            "arguments": {
                "discount_rate": 0.08,
                "cash_flows": [100.0, 200.0, 300.0],
            },
        },
    }


@pytest.fixture(scope="session")
def openai_tool_call_dict() -> dict[str, Any]:
    """A realistic OpenAI gpt-4o tool call dict.

    Returns
    -------
    dict
    """
    return {
        "id": "call_abc123xyz",
        "type": "function",
        "function": {
            "name": "get_weather",
            "arguments": '{"location": "San Francisco, CA", "unit": "celsius"}',
        },
    }


@pytest.fixture(scope="session")
def anthropic_tool_use_dict() -> dict[str, Any]:
    """A realistic Anthropic claude-sonnet-4-20250514 tool use block dict.

    Returns
    -------
    dict
    """
    return {
        "id": "toolu_01XFDUDYJgAACTU45D4GV1t3",
        "type": "tool_use",
        "name": "search_web",
        "input": {
            "query": "latest news on agentic AI",
            "limit": 5,
            "verbose": False,
        },
    }


# ---------------------------------------------------------------------------
# Registry / filesystem fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_registry_dir(tmp_path: Path) -> Path:
    """A temporary directory suitable for use as a schema registry root.

    Parameters
    ----------
    tmp_path : Path
        Pytest-provided temporary directory (unique per test).

    Returns
    -------
    Path
        The registry directory path (guaranteed to exist).
    """
    registry = tmp_path / "registry"
    registry.mkdir()
    return registry


@pytest.fixture
def tmp_schema_file(tmp_path: Path, simple_schema) -> Path:
    """Write ``simple_schema`` to a temporary ``.rschema`` file.

    Parameters
    ----------
    tmp_path : Path
        Pytest-provided temporary directory.
    simple_schema : RelaySchema
        The schema object to serialise.

    Returns
    -------
    Path
        Absolute path to the written ``.rschema`` file.
    """
    import json

    schema_path = tmp_path / "simple.rschema"
    # Write a minimal rschema JSON representation that RelaySchema.from_file can parse.
    schema_path.write_text(
        json.dumps(
            {
                "name": "simple",
                "version": 1,
                "fields": {
                    "name": {"type": "string", "required": True},
                    "count": {"type": "int32", "required": True},
                    "flag": {"type": "bool", "required": False},
                    "score": {"type": "float64", "required": False},
                    "note": {"type": "string", "required": False},
                },
            }
        ),
        encoding="utf-8",
    )
    return schema_path


# ---------------------------------------------------------------------------
# Encoded binary fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def simple_binary(simple_schema, simple_message_dict) -> bytes:
    """Return binary-encoded Relay bytes for ``simple_message_dict``.

    Parameters
    ----------
    simple_schema : RelaySchema
    simple_message_dict : dict

    Returns
    -------
    bytes
    """
    from relay.encoder import encode

    return encode(simple_message_dict, simple_schema)


@pytest.fixture
def tool_call_binary(tool_call_schema, tool_call_message_dict) -> bytes:
    """Return binary-encoded Relay bytes for ``tool_call_message_dict``.

    Parameters
    ----------
    tool_call_schema : RelaySchema
    tool_call_message_dict : dict

    Returns
    -------
    bytes
    """
    from relay.encoder import encode

    return encode(tool_call_message_dict, tool_call_schema)
