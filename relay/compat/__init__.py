"""
Relay compatibility layer.

Provides converters between Relay binary format and external data formats
used by AI frameworks, including raw JSON dicts, OpenAI tool call responses,
and Anthropic tool use blocks.

Public surface
--------------
from_json(data, schema) -> bytes
to_json(data) -> dict
from_openai_tool_call(call) -> bytes
to_openai_tool_call(data) -> dict
from_anthropic_tool_use(block) -> bytes
to_anthropic_tool_use(data) -> dict
"""

from __future__ import annotations

from .anthropic_compat import (
    anthropic_tool_use_schema,
    from_anthropic_tool_use,
    to_anthropic_tool_use,
)
from .json_compat import from_json, to_json
from .openai_compat import (
    from_openai_tool_call,
    openai_tool_call_schema,
    to_openai_tool_call,
)

__all__ = [
    "anthropic_tool_use_schema",
    "from_anthropic_tool_use",
    "from_json",
    "from_openai_tool_call",
    "openai_tool_call_schema",
    "to_anthropic_tool_use",
    "to_json",
    "to_openai_tool_call",
]
