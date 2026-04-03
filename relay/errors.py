"""
Relay error hierarchy with machine-readable error codes.

Every error in the Relay system is a typed ``RelayError`` subclass that carries
a stable, machine-readable ``code`` string, an optional ``field_path`` that
locates the offending field inside a Relay message, and a free-form ``details``
dict for supplemental context.  No Relay operation should raise a bare Python
exception; all failure modes must surface as one of the concrete subclasses
defined here.
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


class RelayError(Exception):
    """Base class for all Relay errors.

    Parameters
    ----------
    message : str
        Human-readable description of the error.
    code : str
        Machine-readable error code of the form ``E0NN``.
    field_path : str or None, optional
        Dot-separated path to the field that triggered the error, e.g.
        ``"tool_call.arguments.discount_rate"``.  ``None`` when the error
        is not associated with a specific field.
    details : dict, optional
        Arbitrary supplemental data.  Keys and values must be JSON-serialisable.

    Raises
    ------
    TypeError
        If *details* is not a ``dict``.

    Examples
    --------
    >>> err = RelayError("something went wrong", code="E000")
    >>> err.code
    'E000'
    >>> err.to_dict()["code"]
    'E000'
    """

    def __init__(
        self,
        message: str,
        *,
        code: str = "E000",
        field_path: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message: str = message
        self.code: str = code
        self.field_path: str | None = field_path
        self.details: dict[str, Any] = details or {}

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialise the error to a plain dictionary.

        Returns
        -------
        dict
            A JSON-serialisable representation containing at minimum
            ``code``, ``message``, ``field_path``, and ``details``.

        Examples
        --------
        >>> err = RelayError("bad", code="E001", field_path="foo.bar")
        >>> d = err.to_dict()
        >>> d["field_path"]
        'foo.bar'
        """
        return {
            "code": self.code,
            "error_type": type(self).__name__,
            "message": self.message,
            "field_path": self.field_path,
            "details": self.details,
        }

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"{type(self).__name__}(code={self.code!r}, "
            f"message={self.message!r}, field_path={self.field_path!r})"
        )


# ---------------------------------------------------------------------------
# Concrete error subclasses
# ---------------------------------------------------------------------------


class ParseError(RelayError):
    """Raised when raw bytes or text cannot be parsed as a valid Relay frame.

    Error code: ``E001``.

    Parameters
    ----------
    message : str
        Human-readable description of the parse failure.
    field_path : str or None, optional
        Location in the frame where parsing failed, if known.
    details : dict, optional
        Additional context such as ``offset``, ``expected``, ``got``.

    Examples
    --------
    >>> raise ParseError("unexpected magic byte", details={"got": 0xFF})
    Traceback (most recent call last):
        ...
    relay.errors.ParseError: unexpected magic byte
    """

    def __init__(
        self,
        message: str,
        *,
        field_path: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code="E001", field_path=field_path, details=details)


class TypeMismatchError(RelayError):
    """Raised when a field value does not match the declared schema type.

    Error code: ``E002``.

    Parameters
    ----------
    message : str
        Human-readable description.
    field_path : str or None, optional
        Dot-separated path to the offending field.
    details : dict, optional
        Should include ``expected`` and ``got`` type names.

    Examples
    --------
    >>> raise TypeMismatchError(
    ...     "expected float32, got str",
    ...     field_path="arguments.rate",
    ...     details={"expected": "float32", "got": "str"},
    ... )
    Traceback (most recent call last):
        ...
    relay.errors.TypeMismatchError: expected float32, got str
    """

    def __init__(
        self,
        message: str,
        *,
        field_path: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code="E002", field_path=field_path, details=details)


class SchemaNotFoundError(RelayError):
    """Raised when a referenced schema cannot be located in the registry.

    Also raised when a required field is absent from a message (the schema
    contract has been violated).

    Error code: ``E003``.

    Parameters
    ----------
    message : str
        Human-readable description.
    field_path : str or None, optional
        Field that was missing or the schema identifier that was not found.
    details : dict, optional
        May include ``name`` and ``hash`` of the missing schema.

    Examples
    --------
    >>> raise SchemaNotFoundError("schema 'agent_tool_call:a3f2bc01' not found")
    Traceback (most recent call last):
        ...
    relay.errors.SchemaNotFoundError: schema 'agent_tool_call:a3f2bc01' not found
    """

    def __init__(
        self,
        message: str,
        *,
        field_path: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code="E003", field_path=field_path, details=details)


class RelayReferenceError(RelayError):
    """Raised when a ``$ref`` cannot be resolved within the session context.

    Named ``RelayReferenceError`` to avoid shadowing the Python built-in
    ``ReferenceError``.

    Error code: ``E004``.

    Parameters
    ----------
    message : str
        Human-readable description.
    field_path : str or None, optional
        The ``$ref`` expression that failed to resolve.
    details : dict, optional
        May include ``session_id``, ``call_index``, ``field_path_expr``.

    Examples
    --------
    >>> raise RelayReferenceError(
    ...     "call index 99 does not exist in session",
    ...     details={"call_index": 99},
    ... )
    Traceback (most recent call last):
        ...
    relay.errors.RelayReferenceError: call index 99 does not exist in session
    """

    def __init__(
        self,
        message: str,
        *,
        field_path: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code="E004", field_path=field_path, details=details)


class DeltaConflictError(RelayError):
    """Raised when a delta operation cannot be applied cleanly to its base.

    Error code: ``E005``.

    Parameters
    ----------
    message : str
        Human-readable description.
    field_path : str or None, optional
        Field path where the conflict occurred.
    details : dict, optional
        May include ``op_type``, ``base_value``, ``delta_value``.

    Examples
    --------
    >>> raise DeltaConflictError(
    ...     "SPL out of range",
    ...     field_path="content.items",
    ...     details={"splice_start": 10, "array_length": 3},
    ... )
    Traceback (most recent call last):
        ...
    relay.errors.DeltaConflictError: SPL out of range
    """

    def __init__(
        self,
        message: str,
        *,
        field_path: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code="E005", field_path=field_path, details=details)


class ValidationError(RelayError):
    """Raised when a message fails schema validation for reasons other than type mismatch.

    This covers missing required fields, invalid enum values, and constraint
    violations that are distinct from a simple type mismatch.

    Error code: ``E006``.

    Parameters
    ----------
    message : str
        Human-readable description.
    field_path : str or None, optional
        Field that failed validation.
    details : dict, optional
        May include ``constraint``, ``value``.

    Examples
    --------
    >>> raise ValidationError(
    ...     "required field 'role' is missing",
    ...     field_path="role",
    ... )
    Traceback (most recent call last):
        ...
    relay.errors.ValidationError: required field 'role' is missing
    """

    def __init__(
        self,
        message: str,
        *,
        field_path: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code="E006", field_path=field_path, details=details)


class EncodingError(RelayError):
    """Raised when a Python object cannot be encoded into a Relay binary frame.

    Error code: ``E007``.

    Parameters
    ----------
    message : str
        Human-readable description.
    field_path : str or None, optional
        Field being encoded when the error occurred.
    details : dict, optional
        May include ``type_tag``, ``value_repr``.

    Examples
    --------
    >>> raise EncodingError(
    ...     "value out of range for int8",
    ...     field_path="count",
    ...     details={"value": 300},
    ... )
    Traceback (most recent call last):
        ...
    relay.errors.EncodingError: value out of range for int8
    """

    def __init__(
        self,
        message: str,
        *,
        field_path: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code="E007", field_path=field_path, details=details)


class DecodingError(RelayError):
    """Raised when binary Relay bytes cannot be decoded into a Python object.

    Error code: ``E008``.

    Parameters
    ----------
    message : str
        Human-readable description.
    field_path : str or None, optional
        Field being decoded when the error occurred.
    details : dict, optional
        May include ``offset``, ``type_tag``, ``bytes_remaining``.

    Examples
    --------
    >>> raise DecodingError(
    ...     "unexpected end of stream while reading field value",
    ...     details={"offset": 42},
    ... )
    Traceback (most recent call last):
        ...
    relay.errors.DecodingError: unexpected end of stream while reading field value
    """

    def __init__(
        self,
        message: str,
        *,
        field_path: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code="E008", field_path=field_path, details=details)


class RegistryError(RelayError):
    """Raised when the schema registry encounters a storage or consistency error.

    Error code: ``E009``.

    Parameters
    ----------
    message : str
        Human-readable description.
    field_path : str or None, optional
        Not typically set for registry errors; included for API uniformity.
    details : dict, optional
        May include ``registry_path``, ``schema_key``.

    Examples
    --------
    >>> raise RegistryError(
    ...     "registry directory is not writable",
    ...     details={"path": "/home/user/.relay/registry"},
    ... )
    Traceback (most recent call last):
        ...
    relay.errors.RegistryError: registry directory is not writable
    """

    def __init__(
        self,
        message: str,
        *,
        field_path: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code="E009", field_path=field_path, details=details)


class SchemaHashMismatch(RelayError):
    """Raised when the 4-byte schema hash in a frame header does not match any registered schema.

    Error code: ``E010``.

    Parameters
    ----------
    message : str
        Human-readable description.
    field_path : str or None, optional
        Not typically set; included for API uniformity.
    details : dict, optional
        Should include ``expected_hash`` and ``actual_hash`` as hex strings.

    Examples
    --------
    >>> raise SchemaHashMismatch(
    ...     "schema hash a3f2bc01 not found in registry",
    ...     details={"hash": "a3f2bc01"},
    ... )
    Traceback (most recent call last):
        ...
    relay.errors.SchemaHashMismatch: schema hash a3f2bc01 not found in registry
    """

    def __init__(
        self,
        message: str,
        *,
        field_path: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code="E010", field_path=field_path, details=details)


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

# Public API name (CLAUDE.md); avoid clashing with builtins on star-imports.
ReferenceError = RelayReferenceError  # noqa: A001

__all__ = [
    "RelayError",
    "ParseError",
    "TypeMismatchError",
    "SchemaNotFoundError",
    "RelayReferenceError",
    "ReferenceError",
    "DeltaConflictError",
    "ValidationError",
    "EncodingError",
    "DecodingError",
    "RegistryError",
    "SchemaHashMismatch",
]
