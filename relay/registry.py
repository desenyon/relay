"""
Local schema registry — file-backed and in-memory.

The registry stores :class:`~relay.schema.RelaySchema` objects keyed by
``"name:hash"`` strings.  Schemas are persisted as individual JSON files in a
directory (default: ``~/.relay/registry/``).  An in-memory index is maintained
for fast lookups without re-reading disk on every access.

A module-level :data:`default_registry` instance is provided so callers can
use the registry without explicit instantiation:

>>> from relay.registry import default_registry
>>> # default_registry.register(schema)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from relay.errors import RegistryError, SchemaNotFoundError
from relay.schema import RelaySchema, SchemaField

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class SchemaRegistry:
    """File-backed schema registry for Relay schemas.

    Schemas are stored one-per-file in *registry_dir*.  The filename is
    ``<name>__<hash>.json``.  An in-memory dict provides O(1) lookup without
    re-reading disk on repeated access.

    Parameters
    ----------
    registry_dir : Path, optional
        Directory to use for persistent storage.  Created on first write if it
        does not exist.  Defaults to ``~/.relay/registry``.

    Examples
    --------
    >>> import tempfile, pathlib
    >>> tmp = pathlib.Path(tempfile.mkdtemp())
    >>> reg = SchemaRegistry(registry_dir=tmp)
    >>> from relay.schema import RelaySchema
    >>> s = RelaySchema("ping", 1, [], {})
    >>> key = reg.register(s)
    >>> key.startswith("ping:")
    True
    >>> reg.exists("ping", s.hash())
    True
    """

    def __init__(
        self,
        registry_dir: Path | None = None,
    ) -> None:
        if registry_dir is None:
            registry_dir = Path.home() / ".relay" / "registry"
        self._dir: Path = registry_dir
        # In-memory index: "name:hash" -> RelaySchema
        self._cache: dict[str, RelaySchema] = {}
        self._loaded: bool = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register(self, schema: RelaySchema) -> str:
        """Register a schema and persist it to disk.

        If the exact same schema (by name + hash) is already registered,
        this is a no-op and returns the existing key.

        Parameters
        ----------
        schema : RelaySchema
            The schema to store.

        Returns
        -------
        str
            Registry key in the form ``"name:hash"``.

        Raises
        ------
        RegistryError
            If the registry directory cannot be created or the file cannot be
            written.

        Examples
        --------
        >>> import tempfile, pathlib
        >>> reg = SchemaRegistry(pathlib.Path(tempfile.mkdtemp()))
        >>> from relay.schema import RelaySchema
        >>> s = RelaySchema("ex", 1, [], {})
        >>> reg.register(s)
        'ex:...'
        """
        self._ensure_loaded()
        key = f"{schema.name}:{schema.hash()}"
        if key in self._cache:
            return key

        self._cache[key] = schema
        self._save_schema(schema)
        return key

    def get(self, name: str, hash_hex: str) -> RelaySchema:
        """Retrieve a schema by name and hash.

        Parameters
        ----------
        name : str
            Schema name (e.g. ``"agent_tool_call"``).
        hash_hex : str
            8-character hex string (4 bytes) of the schema hash.

        Returns
        -------
        RelaySchema

        Raises
        ------
        SchemaNotFoundError
            If no matching schema is found.

        Examples
        --------
        >>> import tempfile, pathlib
        >>> reg = SchemaRegistry(pathlib.Path(tempfile.mkdtemp()))
        >>> from relay.schema import RelaySchema
        >>> s = RelaySchema("ex", 1, [], {})
        >>> _ = reg.register(s)
        >>> reg.get("ex", s.hash()).name
        'ex'
        """
        self._ensure_loaded()
        key = f"{name}:{hash_hex}"
        if key in self._cache:
            return self._cache[key]

        # Try loading from disk if not yet cached
        schema = self._load_schema_file(name, hash_hex)
        if schema is None:
            raise SchemaNotFoundError(
                f"Schema '{name}:{hash_hex}' not found in registry",
                details={"name": name, "hash": hash_hex, "registry_dir": str(self._dir)},
            )
        self._cache[key] = schema
        return schema

    def list(self) -> list[dict[str, Any]]:
        """Return metadata for all registered schemas.

        Returns
        -------
        list of dict
            Each dict contains ``name`` (str), ``hash`` (str), ``version`` (int),
            and ``field_count`` (int).

        Examples
        --------
        >>> import tempfile, pathlib
        >>> reg = SchemaRegistry(pathlib.Path(tempfile.mkdtemp()))
        >>> from relay.schema import RelaySchema
        >>> _ = reg.register(RelaySchema("a", 1, [], {}))
        >>> entries = reg.list()
        >>> entries[0]["name"]
        'a'
        """
        self._ensure_loaded()
        result: list[dict[str, Any]] = []
        for key, schema in self._cache.items():
            result.append(
                {
                    "name": schema.name,
                    "hash": schema.hash(),
                    "version": schema.version,
                    "field_count": len(schema.fields),
                    "key": key,
                }
            )
        return sorted(result, key=lambda x: (x["name"], x["hash"]))

    def delete(self, name: str, hash_hex: str) -> None:
        """Remove a schema from the registry and from disk.

        Parameters
        ----------
        name : str
            Schema name.
        hash_hex : str
            8-character hex hash string.

        Raises
        ------
        SchemaNotFoundError
            If the schema does not exist.
        RegistryError
            If the file cannot be deleted.

        Examples
        --------
        >>> import tempfile, pathlib
        >>> reg = SchemaRegistry(pathlib.Path(tempfile.mkdtemp()))
        >>> from relay.schema import RelaySchema
        >>> s = RelaySchema("del_me", 1, [], {})
        >>> _ = reg.register(s)
        >>> reg.delete("del_me", s.hash())
        >>> reg.exists("del_me", s.hash())
        False
        """
        self._ensure_loaded()
        key = f"{name}:{hash_hex}"
        if key not in self._cache:
            raise SchemaNotFoundError(
                f"Schema '{key}' not found; cannot delete",
                details={"name": name, "hash": hash_hex},
            )
        del self._cache[key]
        file_path = self._schema_file_path(name, hash_hex)
        if file_path.exists():
            try:
                file_path.unlink()
            except OSError as exc:
                raise RegistryError(
                    f"Failed to delete schema file: {file_path}",
                    details={"path": str(file_path), "error": str(exc)},
                ) from exc

    def get_by_hash(self, hash_hex: str) -> RelaySchema:
        """Return the unique schema whose 4-byte hash matches *hash_hex*.

        Parameters
        ----------
        hash_hex : str
            Lowercase 8-character hex string (4 bytes).

        Returns
        -------
        RelaySchema

        Raises
        ------
        SchemaNotFoundError
            If zero or more than one registered schema matches the hash.
        """
        self._ensure_loaded()
        hx = hash_hex.lower().strip()
        matches = [s for s in self._cache.values() if s.hash() == hx]
        if len(matches) == 0:
            raise SchemaNotFoundError(
                f"No schema with hash {hx!r} is registered",
                details={"hash": hx},
            )
        if len(matches) > 1:
            names = [m.name for m in matches]
            raise SchemaNotFoundError(
                f"Multiple schemas share hash {hx!r}: {names!r}",
                details={"hash": hx, "names": names},
            )
        return matches[0]

    def exists(self, name: str, hash_hex: str) -> bool:
        """Return ``True`` if a schema with *name* and *hash_hex* is registered.

        Parameters
        ----------
        name : str
            Schema name.
        hash_hex : str
            8-character hex hash string.

        Returns
        -------
        bool

        Examples
        --------
        >>> import tempfile, pathlib
        >>> reg = SchemaRegistry(pathlib.Path(tempfile.mkdtemp()))
        >>> from relay.schema import RelaySchema
        >>> s = RelaySchema("x", 1, [], {})
        >>> reg.exists("x", s.hash())
        False
        >>> _ = reg.register(s)
        >>> reg.exists("x", s.hash())
        True
        """
        self._ensure_loaded()
        return f"{name}:{hash_hex}" in self._cache

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_loaded(self) -> None:
        """Load all schemas from disk into the in-memory cache on first call.

        Raises
        ------
        RegistryError
            If the registry directory exists but cannot be read.
        """
        if self._loaded:
            return
        if not self._dir.exists():
            self._loaded = True
            return
        try:
            for json_file in self._dir.glob("*.json"):
                try:
                    schema = self._read_schema_file(json_file)
                    key = f"{schema.name}:{schema.hash()}"
                    self._cache[key] = schema
                except Exception:
                    # Corrupt or unrelated file — skip silently
                    pass
        except OSError as exc:
            raise RegistryError(
                f"Cannot read registry directory: {self._dir}",
                details={"path": str(self._dir), "error": str(exc)},
            ) from exc
        self._loaded = True

    def _schema_file_path(self, name: str, hash_hex: str) -> Path:
        """Return the file path for a schema given its name and hash.

        Parameters
        ----------
        name : str
        hash_hex : str

        Returns
        -------
        Path
        """
        # Sanitise the name so it's safe as a filename component
        safe_name = re.sub(r"[^\w\-]", "_", name)
        return self._dir / f"{safe_name}__{hash_hex}.json"

    def _save_schema(self, schema: RelaySchema) -> None:
        """Persist a single schema to disk.

        Parameters
        ----------
        schema : RelaySchema

        Raises
        ------
        RegistryError
            If the directory cannot be created or the file cannot be written.
        """
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise RegistryError(
                f"Cannot create registry directory: {self._dir}",
                details={"path": str(self._dir), "error": str(exc)},
            ) from exc

        file_path = self._schema_file_path(schema.name, schema.hash())
        doc = _schema_to_storage_dict(schema)
        try:
            file_path.write_text(
                json.dumps(doc, separators=(",", ":"), sort_keys=True),
                encoding="utf-8",
            )
        except OSError as exc:
            raise RegistryError(
                f"Cannot write schema file: {file_path}",
                details={"path": str(file_path), "error": str(exc)},
            ) from exc

    def _load_schema_file(self, name: str, hash_hex: str) -> RelaySchema | None:
        """Attempt to load a single schema file from disk.

        Parameters
        ----------
        name : str
        hash_hex : str

        Returns
        -------
        RelaySchema or None
        """
        file_path = self._schema_file_path(name, hash_hex)
        if not file_path.exists():
            return None
        try:
            return self._read_schema_file(file_path)
        except Exception:
            return None

    @staticmethod
    def _read_schema_file(path: Path) -> RelaySchema:
        """Read and deserialise a schema from a JSON file.

        Parameters
        ----------
        path : Path

        Returns
        -------
        RelaySchema

        Raises
        ------
        RegistryError
            If the file cannot be read or decoded.
        """
        try:
            raw = path.read_text(encoding="utf-8")
            doc = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            raise RegistryError(
                f"Cannot read or parse schema file: {path}",
                details={"path": str(path), "error": str(exc)},
            ) from exc
        return _schema_from_storage_dict(doc)


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------


import re  # noqa: E402 (placed after class for readability)


def _field_to_storage(sf: SchemaField) -> dict[str, Any]:
    """Serialise a ``SchemaField`` to a storage dict.

    Parameters
    ----------
    sf : SchemaField

    Returns
    -------
    dict
    """
    d: dict[str, Any] = {
        "name": sf.name,
        "required": sf.required,
        "type": sf.type_name,
    }
    if sf.nested_fields:
        d["fields"] = [_field_to_storage(child) for child in sf.nested_fields]
    return d


def _field_from_storage(d: dict[str, Any]) -> SchemaField:
    """Deserialise a ``SchemaField`` from a storage dict.

    Parameters
    ----------
    d : dict

    Returns
    -------
    SchemaField
    """
    nested = [_field_from_storage(c) for c in d.get("fields", [])]
    return SchemaField(
        name=d["name"],
        type_name=d["type"],
        required=d.get("required", True),
        nested_fields=nested,
    )


def _schema_to_storage_dict(schema: RelaySchema) -> dict[str, Any]:
    """Convert a ``RelaySchema`` to a JSON-serialisable dict for disk storage.

    Parameters
    ----------
    schema : RelaySchema

    Returns
    -------
    dict
    """
    return {
        "enums": schema.enums,
        "fields": [_field_to_storage(f) for f in schema.fields],
        "name": schema.name,
        "raw_text": schema.raw_text,
        "version": schema.version,
    }


def _schema_from_storage_dict(d: dict[str, Any]) -> RelaySchema:
    """Reconstruct a ``RelaySchema`` from a storage dict.

    Parameters
    ----------
    d : dict

    Returns
    -------
    RelaySchema
    """
    fields = [_field_from_storage(fd) for fd in d.get("fields", [])]
    return RelaySchema(
        name=d["name"],
        version=d.get("version", 1),
        fields=fields,
        enums=d.get("enums", {}),
        raw_text=d.get("raw_text", ""),
    )


# ---------------------------------------------------------------------------
# Module-level default registry instance
# ---------------------------------------------------------------------------

#: Default registry instance backed by ``~/.relay/registry``.
default_registry: SchemaRegistry = SchemaRegistry()


def get_default_registry() -> SchemaRegistry:
    """Return the current :data:`default_registry` (resolved at call time).

    Callers that need the process-wide default registry should use this instead
    of importing ``default_registry`` directly, so tests (or hosts) can
    replace ``relay.registry.default_registry`` and have decoding pick it up.
    The :mod:`relay` package also exposes a ``registry`` attribute that may
    shadow this submodule when using ``import relay.registry``; always load
    the submodule via ``importlib.import_module("relay.registry")`` or this
    helper when replacing the default instance.
    """
    import importlib

    return importlib.import_module("relay.registry").default_registry


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

__all__ = [
    "SchemaRegistry",
    "default_registry",
    "get_default_registry",
]
