"""
Per-session storage for Relay messages and :class:`~relay.types.RelayRef` resolution.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from relay.errors import RelayReferenceError
from relay.reference import resolve_path
from relay.types import RelayMessage, RelayRef


class Session:
    """Tracks ordered outputs for a single agent session.

    Parameters
    ----------
    session_id : uuid.UUID, optional
        Defaults to a random UUID v4.

    Examples
    --------
    >>> from relay.session import Session
    >>> from relay.types import RelayMessage, MessageType
    >>> s = Session()
    >>> msg = RelayMessage(MessageType.FULL, b"\\x00" * 4, [])
    >>> s.record(msg)
    0
    """

    def __init__(self, session_id: UUID | None = None) -> None:
        self.session_id: UUID = session_id or uuid4()
        self._calls: list[RelayMessage] = []

    def record(self, message: RelayMessage) -> int:
        """Store *message* and return its 0-based call index.

        Parameters
        ----------
        message : RelayMessage
            Typically a FULL message produced by the runtime.

        Returns
        -------
        int
            Call index used in ``$ref`` expressions.
        """
        self._calls.append(message)
        return len(self._calls) - 1

    def resolve_ref(self, ref: RelayRef) -> Any:
        """Resolve *ref* against this session.

        Parameters
        ----------
        ref : RelayRef
            Reference with matching ``session_id``.

        Returns
        -------
        Any
            Value at ``field_path`` in the recorded message.

        Raises
        ------
        RelayReferenceError
            On session mismatch, unknown call index, or bad path.
        """
        if ref.session_id != self.session_id:
            raise RelayReferenceError(
                "Reference session_id does not match this Session",
                details={
                    "expected": str(self.session_id),
                    "got": str(ref.session_id),
                },
            )
        if ref.call_index < 0 or ref.call_index >= len(self._calls):
            raise RelayReferenceError(
                f"call index {ref.call_index} is out of range "
                f"(session has {len(self._calls)} calls)",
                details={"call_index": ref.call_index},
            )
        base = self._calls[ref.call_index]
        return resolve_path(base, ref.field_path)


__all__ = ["Session"]
