"""CLI command coverage via Click's CliRunner."""

from __future__ import annotations

import importlib
import json
import tempfile
from pathlib import Path

import pytest
from click.testing import CliRunner

from relay.cli.main import cli
from relay.compat import anthropic_tool_use_schema, openai_tool_call_schema
from relay.encoder import encode
from relay.registry import SchemaRegistry
from relay.schema import RelaySchema


def _registry_module():
    """``import relay.registry`` resolves to ``relay.registry`` *attribute* (CLI
    default registry); tests need the actual ``relay.registry`` submodule."""
    return importlib.import_module("relay.registry")


@pytest.fixture
def simple_schema() -> RelaySchema:
    return RelaySchema.from_dict(
        {
            "name": "cli_ping",
            "version": 1,
            "fields": [{"name": "msg", "type": "string", "required": True}],
            "enums": {},
        }
    )


@pytest.fixture
def schema_file() -> Path:
    p = Path(tempfile.mkdtemp()) / "t.rschema"
    p.write_text(
        "schema cli_ping {\n  version: 1\n  fields:\n    msg: string required\n}\n",
        encoding="utf-8",
    )
    return p


@pytest.fixture
def isolated_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SchemaRegistry:
    reg = SchemaRegistry(registry_dir=tmp_path / "reg")
    monkeypatch.setattr(_registry_module(), "default_registry", reg)
    return reg


def test_cli_version_help() -> None:
    runner = CliRunner()
    assert runner.invoke(cli, ["--help"]).exit_code == 0
    assert runner.invoke(cli, ["--version"]).exit_code == 0


def test_inspect_pretty_json_text(
    simple_schema: RelaySchema,
    tmp_path: Path,
    isolated_registry: SchemaRegistry,
) -> None:
    isolated_registry.register(simple_schema)
    data = encode({"msg": "hi"}, simple_schema)
    f = tmp_path / "m.bin"
    f.write_bytes(data)
    runner = CliRunner()
    for fmt in ("pretty", "json", "text"):
        r = runner.invoke(cli, ["inspect", str(f), "--format", fmt])
        assert r.exit_code == 0, r.output
    r2 = runner.invoke(
        cli,
        ["inspect", str(f), "--schema", f"cli_ping:{simple_schema.hash()}"],
    )
    assert r2.exit_code == 0


def test_inspect_bad_file(tmp_path: Path) -> None:
    runner = CliRunner()
    r = runner.invoke(cli, ["inspect", str(tmp_path / "nope.bin")])
    assert r.exit_code != 0


def test_validate_ok(
    simple_schema: RelaySchema,
    tmp_path: Path,
    isolated_registry: SchemaRegistry,
) -> None:
    isolated_registry.register(simple_schema)
    data = encode({"msg": "x"}, simple_schema)
    f = tmp_path / "v.bin"
    f.write_bytes(data)
    runner = CliRunner()
    assert (
        runner.invoke(
            cli,
            ["validate", str(f), "--schema", f"cli_ping:{simple_schema.hash()}"],
        ).exit_code
        == 0
    )


def test_schema_register_list_show_hash(
    schema_file: Path,
    isolated_registry: SchemaRegistry,
) -> None:
    runner = CliRunner()
    assert runner.invoke(cli, ["schema", "register", str(schema_file)]).exit_code == 0
    assert runner.invoke(cli, ["schema", "list"]).exit_code == 0
    h = runner.invoke(cli, ["schema", "hash", str(schema_file)])
    assert h.exit_code == 0
    hx = h.output.strip()
    assert len(hx) == 8
    assert runner.invoke(cli, ["schema", "show", f"cli_ping:{hx}"]).exit_code == 0


def test_schema_show_bad_key(isolated_registry: SchemaRegistry) -> None:
    runner = CliRunner()
    r = runner.invoke(cli, ["schema", "show", "notakey"])
    assert r.exit_code != 0


def test_schema_list_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reg = SchemaRegistry(registry_dir=tmp_path / "empty")
    monkeypatch.setattr(_registry_module(), "default_registry", reg)
    runner = CliRunner()
    r = runner.invoke(cli, ["schema", "list"])
    assert r.exit_code == 0
    assert "(empty registry)" in r.output


def test_schema_register_error_bad_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bad = tmp_path / "bad.rschema"
    bad.write_text("not a schema {", encoding="utf-8")
    monkeypatch.setattr(_registry_module(), "default_registry", SchemaRegistry(tmp_path / "r"))
    runner = CliRunner()
    assert runner.invoke(cli, ["schema", "register", str(bad)]).exit_code != 0


def test_convert_json_relay_roundtrip(
    simple_schema: RelaySchema,
    tmp_path: Path,
    isolated_registry: SchemaRegistry,
) -> None:
    isolated_registry.register(simple_schema)
    jf = tmp_path / "p.json"
    jf.write_text(json.dumps({"msg": "yo"}), encoding="utf-8")
    runner = CliRunner()
    sid = f"cli_ping:{simple_schema.hash()}"
    assert (
        runner.invoke(
            cli,
            ["convert", str(jf), "--from", "json", "--to", "relay", "--schema", sid],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            cli,
            ["convert", str(jf), "--from", "json", "--to", "relay-text", "--schema", sid],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            cli,
            ["convert", str(jf), "--from", "json", "--to", "json", "--schema", sid],
        ).exit_code
        == 0
    )


def test_convert_msgpack(
    isolated_registry: SchemaRegistry, simple_schema: RelaySchema, tmp_path: Path
) -> None:
    import msgpack

    isolated_registry.register(simple_schema)
    mf = tmp_path / "p.mp"
    mf.write_bytes(msgpack.packb({"msg": "m"}))
    runner = CliRunner()
    sid = f"cli_ping:{simple_schema.hash()}"
    assert (
        runner.invoke(
            cli,
            ["convert", str(mf), "--from", "msgpack", "--to", "json", "--schema", sid],
        ).exit_code
        == 0
    )


def test_convert_msgpack_bad_root(
    isolated_registry: SchemaRegistry, simple_schema: RelaySchema, tmp_path: Path
) -> None:
    import msgpack

    isolated_registry.register(simple_schema)
    mf = tmp_path / "p.mp"
    mf.write_bytes(msgpack.packb([1, 2, 3]))
    runner = CliRunner()
    sid = f"cli_ping:{simple_schema.hash()}"
    r = runner.invoke(
        cli,
        ["convert", str(mf), "--from", "msgpack", "--to", "json", "--schema", sid],
    )
    assert r.exit_code != 0


def test_convert_openai_anthropic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reg = SchemaRegistry(registry_dir=tmp_path / "compat_reg")
    reg.register(openai_tool_call_schema())
    reg.register(anthropic_tool_use_schema())
    monkeypatch.setattr(_registry_module(), "default_registry", reg)

    oa = tmp_path / "oa.json"
    oa.write_text(
        json.dumps(
            {
                "id": "c1",
                "type": "function",
                "function": {"name": "f", "arguments": "{}"},
            }
        ),
        encoding="utf-8",
    )
    runner = CliRunner()
    assert (
        runner.invoke(
            cli,
            ["convert", str(oa), "--from", "openai", "--to", "relay"],
        ).exit_code
        == 0
    )
    an = tmp_path / "an.json"
    an.write_text(
        json.dumps(
            {
                "type": "tool_use",
                "id": "t1",
                "name": "g",
                "input": {"a": 1},
            }
        ),
        encoding="utf-8",
    )
    assert (
        runner.invoke(
            cli,
            ["convert", str(an), "--from", "anthropic", "--to", "json"],
        ).exit_code
        == 0
    )


def test_convert_json_missing_schema(tmp_path: Path) -> None:
    jf = tmp_path / "p.json"
    jf.write_text("{}", encoding="utf-8")
    runner = CliRunner()
    r = runner.invoke(cli, ["convert", str(jf), "--from", "json", "--to", "relay"])
    assert r.exit_code != 0


def test_bench_missing_script(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import relay.cli.commands.bench as bench_mod

    root = tmp_path

    class FakePath:
        def __init__(self, *_a: object, **_k: object) -> None:
            pass

        def resolve(self) -> FakePath:
            return self

        @property
        def parents(self) -> object:
            class _P:
                def __getitem__(self, i: int) -> Path:
                    if i == 3:
                        return root
                    return root

            return _P()

    monkeypatch.setattr(bench_mod, "Path", FakePath)
    runner = CliRunner()
    r = runner.invoke(cli, ["bench"])
    assert r.exit_code == 1


def test_bench_runs_subprocess(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import relay.cli.commands.bench as bench_mod

    root = tmp_path
    (root / "benchmarks").mkdir(parents=True)
    (root / "benchmarks" / "bench_vs_json.py").write_text("# stub\n", encoding="utf-8")

    class FakePath:
        def __init__(self, *_a: object, **_k: object) -> None:
            pass

        def resolve(self) -> FakePath:
            return self

        @property
        def parents(self) -> object:
            class _P:
                def __getitem__(self, i: int) -> Path:
                    if i == 3:
                        return root
                    return root

            return _P()

    monkeypatch.setattr(bench_mod, "Path", FakePath)
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def _call(*a: object, **k: object) -> int:
        calls.append((a, k))
        return 0

    monkeypatch.setattr(bench_mod.subprocess, "call", _call)
    runner = CliRunner()
    r = runner.invoke(
        cli, ["bench", "--iterations", "10", "--payload-size", "small", "--compare", "json"]
    )
    assert r.exit_code == 0
    assert calls
