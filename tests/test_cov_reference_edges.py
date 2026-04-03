"""Additional resolve_path branches."""

from __future__ import annotations

import pytest

from relay.errors import RelayReferenceError
from relay.reference import resolve_path
from relay.types import MessageType, RelayField, RelayMessage, TypeTag


def test_indexing_non_list_raises() -> None:
    msg = RelayMessage(
        MessageType.FULL,
        b"\x00" * 4,
        [RelayField(1, "items", TypeTag.STRING, "not-a-list")],
    )
    with pytest.raises(RelayReferenceError, match="Not a list"):
        resolve_path(msg, "items[0]")


def test_bracket_then_path_non_relayfield_list_raises() -> None:
    msg = RelayMessage(
        MessageType.FULL,
        b"\x00" * 4,
        [RelayField(1, "items", TypeTag.ARRAY, [[1, 2]])],
    )
    with pytest.raises(RelayReferenceError, match="Cannot traverse"):
        resolve_path(msg, "items[0].x")


def test_cannot_descend_into_scalar() -> None:
    msg = RelayMessage(
        MessageType.FULL,
        b"\x00" * 4,
        [RelayField(1, "n", TypeTag.INT32, 3)],
    )
    with pytest.raises(RelayReferenceError, match="Cannot descend"):
        resolve_path(msg, "n.x")


def test_bracket_then_nested_relayfield_object_path() -> None:
    inner = RelayField(1, "k", TypeTag.STRING, "deep")
    row = [inner]
    msg = RelayMessage(
        MessageType.FULL,
        b"\x00" * 4,
        [RelayField(1, "items", TypeTag.ARRAY, [row])],
    )
    assert resolve_path(msg, "items[0].k") == "deep"


def test_bracket_scalar_then_dot_fails() -> None:
    msg = RelayMessage(
        MessageType.FULL,
        b"\x00" * 4,
        [RelayField(1, "items", TypeTag.ARRAY, [1, 2, 3])],
    )
    with pytest.raises(RelayReferenceError, match="Cannot continue path"):
        resolve_path(msg, "items[0].nope")
