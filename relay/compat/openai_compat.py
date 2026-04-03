"""
OpenAI tool-call compatibility layer for Relay.

Converts between the OpenAI function-calling wire format and binary Relay
messages using a built-in hardcoded schema.

The ``arguments`` field is stored on the wire as a UTF-8 string containing
JSON (OpenAI's native shape), so the Relay object schema stays fixed while
still round-tripping arbitrary JSON objects.
"""

from __future__ import annotations

import json as _json
from typing import Any

_OPENAI_TOOL_CALL_SCHEMA_DICT: dict[str, Any] = {
    "name": "openai_tool_call",
    "version": 1,
    "fields": [
        {
            "name": "id",
            "type": "string",
            "required": True,
        },
        {
            "name": "type",
            "type": "string",
            "required": True,
        },
        {
            "name": "function_name",
            "type": "string",
            "required": True,
        },
        {
            "name": "arguments",
            "type": "string",
            "required": True,
        },
    ],
    "enums": {},
}


def _get_schema() -> Any:
    from ..schema import RelaySchema

    return RelaySchema.from_dict(_OPENAI_TOOL_CALL_SCHEMA_DICT)


def openai_tool_call_schema() -> Any:
    """Return the built-in ``openai_tool_call`` :class:`~relay.schema.RelaySchema`."""
    return _get_schema()


def from_openai_tool_call(call: dict[str, Any]) -> bytes:
    """Encode an OpenAI tool call dict as a binary Relay message."""
    from ..encoder import encode
    from ..errors import ParseError, TypeMismatchError

    if not isinstance(call, dict):
        raise TypeMismatchError(
            f"OpenAI tool call must be a dict, got {type(call).__name__}",
            field_path="<root>",
            details={"got": type(call).__name__},
        )

    call_id = call.get("id")
    call_type = call.get("type", "function")
    function_block = call.get("function", {})

    if not isinstance(function_block, dict):
        raise TypeMismatchError(
            "OpenAI tool call 'function' field must be a dict",
            field_path="function",
            details={"got": type(function_block).__name__},
        )

    function_name = function_block.get("name", "")
    raw_arguments = function_block.get("arguments", "{}")

    if isinstance(raw_arguments, str):
        try:
            parsed_arguments: dict[str, Any] = _json.loads(raw_arguments)
        except _json.JSONDecodeError as exc:
            raise ParseError(
                f"OpenAI tool call 'function.arguments' is not valid JSON: {exc}",
                field_path="function.arguments",
                details={"raw": raw_arguments[:200]},
            ) from exc
    elif isinstance(raw_arguments, dict):
        parsed_arguments = raw_arguments
    else:
        raise TypeMismatchError(
            "OpenAI tool call 'function.arguments' must be a JSON string or dict",
            field_path="function.arguments",
            details={"got": type(raw_arguments).__name__},
        )

    arguments_json = _json.dumps(parsed_arguments, separators=(",", ":"), sort_keys=True)

    payload: dict[str, Any] = {
        "id": str(call_id) if call_id is not None else "",
        "type": str(call_type),
        "function_name": str(function_name),
        "arguments": arguments_json,
    }

    schema = _get_schema()
    return encode(payload, schema)


def to_openai_tool_call(data: bytes) -> dict[str, Any]:
    """Decode a binary Relay message back to an OpenAI tool call dict."""
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

    call_id = _get_str("id", "")
    call_type = _get_str("type", "function")
    function_name = _get_str("function_name", "")
    arguments_str = _get_str("arguments", "{}")

    try:
        arguments_obj = _json.loads(arguments_str)
    except _json.JSONDecodeError:
        arguments_obj = {}

    return {
        "id": call_id,
        "type": call_type,
        "function": {
            "name": function_name,
            "arguments": _json.dumps(arguments_obj if isinstance(arguments_obj, dict) else {}),
        },
    }


__all__ = [
    "from_openai_tool_call",
    "to_openai_tool_call",
    "openai_tool_call_schema",
]
