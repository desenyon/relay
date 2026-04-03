"""One-off branches in compat decode helpers and inspect error rendering."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from click.testing import CliRunner

from relay.cli.commands.inspect import inspect_cmd
from relay.compat.anthropic_compat import (
    anthropic_tool_use_schema,
    from_anthropic_tool_use,
    to_anthropic_tool_use,
)
from relay.compat.openai_compat import (
    from_openai_tool_call,
    openai_tool_call_schema,
    to_openai_tool_call,
)
from relay.decoder import decode
from relay.errors import RelayError, TypeMismatchError
from relay.types import RelayField, RelayMessage


def test_to_openai_tool_call_string_guard() -> None:
    b = from_openai_tool_call(
        {
            "id": "c1",
            "type": "function",
            "function": {"name": "fn", "arguments": "{}"},
        }
    )
    msg = decode(b, schema=openai_tool_call_schema(), validate=False)
    bad_fields = [
        RelayField(f.field_id, f.name, f.type_tag, (999 if f.name == "id" else f.value))
        for f in msg.fields
    ]
    bad_msg = RelayMessage(msg.message_type, msg.schema_hash, bad_fields)
    with patch("relay.decoder.decode", return_value=bad_msg):
        with pytest.raises(TypeMismatchError, match="must be string"):
            to_openai_tool_call(b"\x00")


def test_to_anthropic_tool_use_string_guard() -> None:
    b = from_anthropic_tool_use(
        {
            "type": "tool_use",
            "id": "u1",
            "name": "tool",
            "input": {},
        }
    )
    msg = decode(b, schema=anthropic_tool_use_schema(), validate=False)
    bad_fields = [
        RelayField(f.field_id, f.name, f.type_tag, (999 if f.name == "id" else f.value))
        for f in msg.fields
    ]
    bad_msg = RelayMessage(msg.message_type, msg.schema_hash, bad_fields)
    with patch("relay.decoder.decode", return_value=bad_msg):
        with pytest.raises(TypeMismatchError, match="must be string"):
            to_anthropic_tool_use(b"\x00")


def test_to_openai_uses_defaults_for_missing_fields() -> None:
    from relay.types import MessageType

    empty = RelayMessage(MessageType.FULL, b"\x00" * 4, [])
    with patch("relay.decoder.decode", return_value=empty):
        d = to_openai_tool_call(b"\x00")
    assert d["id"] == ""
    assert d["type"] == "function"


def test_to_anthropic_uses_defaults_for_missing_fields() -> None:
    from relay.types import MessageType

    empty = RelayMessage(MessageType.FULL, b"\x00" * 4, [])
    with patch("relay.decoder.decode", return_value=empty):
        d = to_anthropic_tool_use(b"\x00")
    assert d["id"] == ""


def test_inspect_relay_error_prints_details(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    p = tmp_path / "x.relay"
    p.write_bytes(b"\x00")

    def fake_decode(_raw: bytes, schema=None):
        raise RelayError(
            "failed",
            code="E_TEST",
            field_path="f",
            details={"k": 1},
        )

    monkeypatch.setattr("relay.decoder.decode", fake_decode)
    runner = CliRunner()
    result = runner.invoke(inspect_cmd, [str(p)])
    assert result.exit_code == 1
    assert "E_TEST" in result.output
    assert "Field path" in result.output
    assert "Details" in result.output
