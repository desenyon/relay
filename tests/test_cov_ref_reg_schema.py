"""reference, registry, schema API, validate, types helpers — coverage completion."""

from __future__ import annotations

from pathlib import Path

import pytest

from relay.decoder import decode
from relay.encoder import encode
from relay.errors import (
    ParseError,
    RegistryError,
    RelayReferenceError,
    SchemaNotFoundError,
    TypeMismatchError,
    ValidationError,
)
from relay.reference import resolve_path
from relay.registry import SchemaRegistry, get_default_registry
from relay.schema import RelaySchema as SourceSchema
from relay.schema import SchemaField as SourceField
from relay.schema_compile import compile_schema
from relay.types import (
    MessageType,
    RelayField,
    RelayMessage,
    RelaySchema,
    SchemaField,
    TypeTag,
    VectorDtype,
    VectorValue,
)
from relay.validate import _type_name_to_tag, validate_field, validate_message


def test_resolve_path_bracket_and_dict() -> None:
    sch = SourceSchema(
        "rp",
        1,
        [
            SourceField("items", "array<int32>", True),
            SourceField("meta", "object", False, nested_fields=[]),
        ],
        {},
    )
    raw = encode({"items": [1, 2, 3]}, sch)
    compiled = compile_schema(sch)
    msg = decode(raw, schema=sch, validate=False)
    assert resolve_path(msg, "items[1]") == 2

    msg2 = RelayMessage(
        MessageType.FULL,
        compiled.schema_hash,
        [RelayField(1, "meta", TypeTag.OBJECT, {"x": 1})],
    )
    assert resolve_path(msg2, "meta.x") == 1

    with pytest.raises(RelayReferenceError):
        resolve_path(msg, "items[10]")
    with pytest.raises(RelayReferenceError):
        resolve_path(msg, "items[0].nope")
    with pytest.raises(RelayReferenceError):
        resolve_path(msg, "nope[0]")


def test_resolve_path_malformed_bracket() -> None:
    msg = RelayMessage(MessageType.FULL, b"\x00" * 4, [RelayField(1, "a", TypeTag.STRING, "x")])
    with pytest.raises(RelayReferenceError):
        resolve_path(msg, "a[0")


def test_registry_register_cache_hit(tmp_path: Path) -> None:
    reg = SchemaRegistry(tmp_path / "rg")
    s = SourceSchema("c", 1, [], {})
    k1 = reg.register(s)
    k2 = reg.register(s)
    assert k1 == k2


def test_registry_get_load_disk(tmp_path: Path) -> None:
    reg = SchemaRegistry(tmp_path / "rg2")
    s = SourceSchema("d", 1, [], {})
    reg.register(s)
    reg2 = SchemaRegistry(tmp_path / "rg2")
    s2 = reg2.get("d", s.hash())
    assert s2.name == "d"


def test_registry_delete_missing_and_os_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reg = SchemaRegistry(tmp_path / "rg3")
    with pytest.raises(SchemaNotFoundError):
        reg.delete("x", "deadbeef")

    s = SourceSchema("z", 1, [], {})
    reg.register(s)
    fp = reg._schema_file_path("z", s.hash())

    orig_unlink = Path.unlink

    def selective_unlink(self: Path, *a: object, **k: object) -> None:
        if self == fp:
            raise OSError("sim")
        orig_unlink(self, *a, **k)

    monkeypatch.setattr(Path, "unlink", selective_unlink)
    with pytest.raises(RegistryError):
        reg.delete("z", s.hash())


def test_registry_get_by_hash_multi(tmp_path: Path) -> None:
    reg = SchemaRegistry(tmp_path / "rg4")
    s_a = SourceSchema("a", 1, [], {})
    reg.register(s_a)
    s_b = SourceSchema("b", 1, [], {})
    s_b.hash = lambda: s_a.hash()  # type: ignore[method-assign]
    reg._cache[f"b:{s_a.hash()}"] = s_b
    with pytest.raises(SchemaNotFoundError) as ei:
        reg.get_by_hash(s_a.hash())
    assert "Multiple" in str(ei.value)


def test_registry_ensure_loaded_oserror(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    d = tmp_path / "rg5"
    d.mkdir()
    reg = SchemaRegistry(d)
    real_glob = Path.glob

    def fake_glob(self: Path, pattern: str):
        if self == d and pattern == "*.json":
            raise OSError("glob")
        return real_glob(self, pattern)

    monkeypatch.setattr(Path, "glob", fake_glob)
    with pytest.raises(RegistryError):
        reg.list()


def test_registry_save_mkdir_fail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sub = tmp_path / "rg6"
    reg = SchemaRegistry(sub)
    s = SourceSchema("w", 1, [], {})
    real_mkdir = Path.mkdir

    def mkdir_fail(self: Path, *a: object, **k: object) -> None:
        if self == sub:
            raise OSError("mkdir")
        real_mkdir(self, *a, **k)

    monkeypatch.setattr(Path, "mkdir", mkdir_fail)
    with pytest.raises(RegistryError):
        reg.register(s)


def test_registry_read_schema_file_errors(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text("{", encoding="utf-8")
    with pytest.raises(RegistryError):
        SchemaRegistry._read_schema_file(p)


def test_get_default_registry() -> None:
    assert get_default_registry() is not None


def test_schema_enum_helpers() -> None:
    s = SourceSchema(
        "e",
        1,
        [],
        {"E": ["p", "q"]},
    )
    with pytest.raises(SchemaNotFoundError):
        s.get_enum_index("X", "p")
    with pytest.raises(ValidationError):
        s.get_enum_index("E", "zzz")
    with pytest.raises(SchemaNotFoundError):
        s.get_enum_name("X", 0)
    with pytest.raises(ValidationError):
        s.get_enum_name("E", 99)


def test_schema_from_dict_keyerror() -> None:
    with pytest.raises(ParseError):
        SourceSchema.from_dict({"version": 1, "fields": [], "enums": {}})


def test_schema_from_file_missing(tmp_path: Path) -> None:
    with pytest.raises(ParseError):
        SourceSchema.from_file(tmp_path / "nope.rschema")


def test_type_name_to_tag() -> None:
    assert _type_name_to_tag("string") == TypeTag.STRING
    assert _type_name_to_tag("enum<X>") == TypeTag.ENUM
    assert _type_name_to_tag("totally_unknown_type_xyz") is None


def test_validate_field_type_mismatch() -> None:
    sch = RelaySchema(
        "v",
        1,
        [SchemaField("x", TypeTag.STRING, 1, True, [], [], None, None, None)],
        b"\x00" * 4,
    )
    bad = RelayField(1, "x", TypeTag.INT32, 1)
    with pytest.raises(TypeMismatchError):
        validate_field(bad, sch.fields[0], sch, path="x")


def test_validate_message_missing_required() -> None:
    sch = RelaySchema(
        "m",
        1,
        [SchemaField("k", TypeTag.STRING, 1, True, [], [], None, None, None)],
        b"\x00" * 4,
    )
    msg = RelayMessage(MessageType.FULL, b"\x00" * 4, [])
    with pytest.raises(ValidationError):
        validate_message(msg, sch)


def test_vector_value_eq() -> None:
    import numpy as np

    a = VectorValue(VectorDtype.FLOAT32, 1, np.array([1.0], dtype=np.float32))
    assert (a == "n") is False
    with pytest.raises(ValueError, match="dim"):
        VectorValue(VectorDtype.FLOAT32, 2, np.array([1.0], dtype=np.float32))


def test_compiled_schema_field_lookups() -> None:
    inner = SchemaField("n", TypeTag.STRING, 2, True, [], [], None, None, None)
    top = SchemaField("o", TypeTag.OBJECT, 1, True, [inner], [], None, None, None)
    s = RelaySchema("s", 1, [top], b"\x00" * 4)
    assert s.field_by_name("missing") is None
    assert s.field_by_id(99) is None
    assert top.sub_field_by_name("missing") is None
    assert top.sub_field_by_id(99) is None
    assert top.sub_field_by_name("n") is inner
    assert top.sub_field_by_id(2) is inner


def test_compiled_schema_hash_hex() -> None:
    s = RelaySchema(
        "h",
        1,
        [SchemaField("x", TypeTag.STRING, 1, True, [], [], None, None, None)],
        b"\x01\x02\x03\x04",
    )
    assert s.hash_hex == "01020304"
