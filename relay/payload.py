"""Convert :class:`~relay.types.RelayMessage` ↔ plain Python dict payloads."""

from __future__ import annotations

from typing import Any

from relay.types import RelayField, RelayMessage, TypeTag


def message_to_payload_dict(message: RelayMessage) -> dict[str, Any]:
    """Flatten a decoded FULL-style message to the dict shape :func:`encode_text` expects.

    Parameters
    ----------
    message : RelayMessage
        Typically ``MessageType.FULL``.

    Returns
    -------
    dict
        Top-level keys are field names; nested objects become dicts.
    """
    out: dict[str, Any] = {}
    for f in message.fields:
        out[f.name] = _field_to_plain(f)
    return out


def _field_to_plain(f: RelayField) -> Any:
    if f.type_tag == TypeTag.OBJECT and isinstance(f.value, list):
        d: dict[str, Any] = {}
        for ch in f.value:
            if isinstance(ch, RelayField):
                d[ch.name] = _field_to_plain(ch)
        return d
    if f.type_tag == TypeTag.ARRAY and isinstance(f.value, list):
        return list(f.value)
    return f.value


__all__ = ["message_to_payload_dict"]
