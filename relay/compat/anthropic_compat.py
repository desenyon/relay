"""
Anthropic tool-use compatibility layer for Relay.

``input`` is stored as a JSON string on the wire so arbitrary tool parameters
round-trip without dynamic Relay object schemas.
"""

from __future__ import annotations

import json as _json
from typing import Any

_ANTHROPIC_TOOL_USE_SCHEMA_DICT: dict[str, Any] = {
    "name": "anthropic_tool_use",
    "version": 1,
    "fields": [
        {"name": "type", "type": "string", "required": True},
        {"name": "id", "type": "string", "required": True},
        {"name": "name", "type": "string", "required": True},
        {"name": "input", "type": "string", "required": True},
    ],
    "enums": {},
}


def _get_schema() -> Any:
    from ..schema import RelaySchema

    return RelaySchema.from_dict(_ANTHROPIC_TOOL_USE_SCHEMA_DICT)


def anthropic_tool_use_schema() -> Any:
    """Return the built-in ``anthropic_tool_use`` schema."""
    return _get_schema()


def from_anthropic_tool_use(block: dict[str, Any]) -> bytes:
    """Encode an Anthropic tool use block as a binary Relay message."""
    from ..encoder import encode
    from ..errors import TypeMismatchError

    if not isinstance(block, dict):
        raise TypeMismatchError(
            f"Anthropic tool use block must be a dict, got {type(block).__name__}",
            field_path="<root>",
        )

    block_type = block.get("type", "tool_use")
    block_id = block.get("id")
    tool_name = block.get("name")
    tool_input = block.get("input", {})

    if block_id is None:
        raise TypeMismatchError(
            "Anthropic tool use block missing required field 'id'",
            field_path="id",
        )

    if tool_name is None:
        raise TypeMismatchError(
            "Anthropic tool use block missing required field 'name'",
            field_path="name",
        )

    if not isinstance(tool_input, dict):
        raise TypeMismatchError(
            "Anthropic tool use block 'input' must be a dict",
            field_path="input",
        )

    input_json = _json.dumps(tool_input, separators=(",", ":"), sort_keys=True)

    payload: dict[str, Any] = {
        "type": str(block_type),
        "id": str(block_id),
        "name": str(tool_name),
        "input": input_json,
    }

    return encode(payload, _get_schema())


def to_anthropic_tool_use(data: bytes) -> dict[str, Any]:
    """Decode a binary Relay message back to an Anthropic tool use block dict."""
    from ..decoder import decode
    from ..errors import TypeMismatchError

    message = decode(data, schema=_get_schema(), validate=True)

    def _get_str(name: str, default: str = "") -> str:
        f = message.get_field(name)
        if f is None:
            return default
        if not isinstance(f.value, str):
            raise TypeMismatchError(
                f"Field {name!r} must be string",
                field_path=name,
            )
        return f.value

    raw_input = _get_str("input", "{}")
    try:
        tool_input = _json.loads(raw_input)
    except _json.JSONDecodeError:
        tool_input = {}

    return {
        "type": _get_str("type", "tool_use"),
        "id": _get_str("id", ""),
        "name": _get_str("name", ""),
        "input": tool_input if isinstance(tool_input, dict) else {},
    }


__all__ = [
    "from_anthropic_tool_use",
    "to_anthropic_tool_use",
    "anthropic_tool_use_schema",
]
