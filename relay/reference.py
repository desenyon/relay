"""
Reference resolution helpers for :class:`~relay.types.RelayRef`.
"""

from __future__ import annotations

from typing import Any

from relay.errors import RelayReferenceError
from relay.types import RelayField, RelayMessage, TypeTag


def resolve_path(message: RelayMessage, field_path: str) -> Any:
    """Return the value at *field_path* inside *message*.

    Parameters
    ----------
    message : RelayMessage
        Decoded FULL (or compatible) message.
    field_path : str
        Dot-separated path; ``\"\"`` means the whole message as a dict.

    Returns
    -------
    Any
        The field value (scalar, list, dict of plain values, etc.).

    Raises
    ------
    RelayReferenceError
        If the path does not exist.
    """
    if not field_path:
        return _message_to_shallow_dict(message)

    parts = field_path.split(".")
    idx = 0
    fields = {f.name: f for f in message.fields}

    while idx < len(parts):
        part = parts[idx]
        bracket = part.find("[")
        if bracket >= 0:
            name = part[:bracket]
            rest = part[bracket:]
            if name not in fields:
                raise RelayReferenceError(
                    f"Unknown field {name!r} in path {field_path!r}",
                    field_path=field_path,
                )
            current = fields[name].value
            # Parse bracket segments attached to this segment, e.g. items[0]
            array_indices: list[int] = []
            s = rest
            while s.startswith("["):
                end = s.find("]")
                if end < 0:
                    raise RelayReferenceError(
                        f"Malformed path segment {part!r}",
                        field_path=field_path,
                    )
                array_indices.append(int(s[1:end]))
                s = s[end + 1 :]
            for ai in array_indices:
                if not isinstance(current, list):
                    raise RelayReferenceError(
                        f"Not a list while indexing {field_path!r}",
                        field_path=field_path,
                    )
                if ai < 0 or ai >= len(current):
                    raise RelayReferenceError(
                        f"Index {ai} out of range in {field_path!r}",
                        field_path=field_path,
                    )
                current = current[ai]
            idx += 1
            if idx >= len(parts):
                return current
            if not isinstance(current, list) or not current:
                raise RelayReferenceError(
                    f"Cannot continue path past {part!r}",
                    field_path=field_path,
                )
            # Remaining path into nested object stored as RelayField list
            if isinstance(current[0], RelayField):
                fields = {cf.name: cf for cf in current}
                continue
            raise RelayReferenceError(
                f"Cannot traverse into {type(current).__name__}",
                field_path=field_path,
            )
        else:
            name = part
            if name not in fields:
                raise RelayReferenceError(
                    f"Unknown field {name!r} in path {field_path!r}",
                    field_path=field_path,
                )
            val = fields[name].value
            idx += 1
            if idx >= len(parts):
                return val
            if isinstance(val, list) and val and isinstance(val[0], RelayField):
                fields = {cf.name: cf for cf in val}
            elif isinstance(val, dict):
                # Plain dict (e.g. after manual construction)
                def _wrap(k: str, v: Any) -> RelayField:
                    return RelayField(0, k, TypeTag.STRING, v)

                fields = {k: _wrap(k, v) for k, v in val.items()}
            else:
                raise RelayReferenceError(
                    f"Cannot descend into field {name!r} for path {field_path!r}",
                    field_path=field_path,
                )
    raise RelayReferenceError(
        f"Unresolved path {field_path!r}",
        field_path=field_path,
    )


def _message_to_shallow_dict(message: RelayMessage) -> dict[str, Any]:
    return {f.name: f.value for f in message.fields}


__all__ = ["resolve_path"]
