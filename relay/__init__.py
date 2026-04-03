"""
Relay — production-grade binary interchange format for agentic AI runtimes.

This package exposes encode/decode APIs, schema tooling, deltas, sessions,
and compatibility shims as specified in the project documentation.
"""

from __future__ import annotations

from relay.compat import (
    from_anthropic_tool_use,
    from_json,
    from_openai_tool_call,
    to_anthropic_tool_use,
    to_json,
    to_openai_tool_call,
)
from relay.decoder import decode, decode_stream
from relay.delta import apply_delta, delta
from relay.encoder import encode
from relay.errors import (
    DeltaConflictError,
    EncodingError,
    ParseError,
    ReferenceError,
    RelayError,
    RelayReferenceError,
    SchemaHashMismatch,
    SchemaNotFoundError,
    TypeMismatchError,
    ValidationError,
)
from relay.registry import default_registry
from relay.schema import RelaySchema
from relay.session import Session
from relay.text_decoder import decode_text
from relay.text_encoder import encode_text


class Schema:
    """Namespace for :class:`RelaySchema` factories (``relay.Schema`` API)."""

    from_dict = staticmethod(RelaySchema.from_dict)
    from_file = staticmethod(RelaySchema.from_file)


registry: object = default_registry

__all__ = [
    "Schema",
    "encode",
    "encode_text",
    "decode",
    "decode_text",
    "decode_stream",
    "RelaySchema",
    "registry",
    "delta",
    "apply_delta",
    "Session",
    "RelayError",
    "SchemaNotFoundError",
    "TypeMismatchError",
    "ReferenceError",
    "RelayReferenceError",
    "DeltaConflictError",
    "ParseError",
    "ValidationError",
    "EncodingError",
    "SchemaHashMismatch",
    "from_json",
    "to_json",
    "from_openai_tool_call",
    "to_openai_tool_call",
    "from_anthropic_tool_use",
    "to_anthropic_tool_use",
]

__version__ = "0.1.0"
