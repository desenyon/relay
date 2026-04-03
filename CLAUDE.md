# CLAUDE.md — Relay

## Project Identity

**Relay** is a production-grade, open-source data interchange format engineered for agentic AI runtimes. It replaces JSON as the wire format between LLM agents, tool executors, orchestrators, and memory systems. Relay is streaming-native, schema-enforced at the wire level, binary-compact, semantically typed, and reference-aware. It is not a prototype. Every component you build must be deployment-ready, tested, documented, and publishable to PyPI and npm.

**Author**: Naitik Gupta / Saerin Research  
**Repository**: `github.com/desenyon/relay`  
**License**: Apache 2.0  
**Target users**: AI engineers building multi-agent pipelines, tool-calling systems, and LLM orchestration frameworks.

---

## Core Design Principles

These are non-negotiable constraints. Every decision must be evaluated against them.

1. **Schema-at-wire**: Every Relay message carries a 4-byte schema hash in its frame header that references a schema in the local registry. Consumers validate type correctness before processing begins, not after.

2. **Streaming-native**: Any Relay message must be incrementally parseable. A consumer must be able to act on field 1 while fields 2-N are still in transit. Frame headers declare field length so consumers can begin dispatching without buffering the full payload.

3. **Semantic primitives**: Relay has first-class types beyond JSON's 6: `uuid`, `datetime`, `uri`, `vector<dtype, dim>`, `enum<name>`, `bytes`, `code_block<lang>`, `markdown_block`. These are encoded compactly and validated at parse time.

4. **Reference semantics**: A Relay message can reference a prior output in the session context using `$ref: <session_id>.<call_index>.<field_path>` syntax. The runtime resolves references without re-transmitting the full value.

5. **Delta messages**: Relay supports a `DELTA` message type as a peer to `FULL`. A delta expresses a mutation over a prior message state using Myers-diff-style operations: `SET`, `DELETE`, `APPEND`, `SPLICE`. This is critical for document-editing agents.

6. **LLM-emittable text fallback**: Relay has a canonical text encoding (`.relay` files) that an LLM can emit directly as structured text, parseable by the Relay runtime. The binary encoding is the wire format; the text encoding is the authoring and debug format. They are semantically identical.

7. **Human-readable debug output**: Every binary Relay message can be round-tripped to a human-readable `.relay` text representation and back. The CLI provides this as `relay inspect <file>`.

8. **Zero silent failures**: Every type mismatch, missing required field, unresolved reference, and schema version conflict raises a typed `RelayError` with a machine-readable error code, not a Python exception with an unstructured string.

---

## Repository Structure

Build this exact structure. Do not deviate.

```
relay/
  CLAUDE.md                     # This file
  README.md                     # Full project documentation
  LICENSE                       # Apache 2.0
  pyproject.toml                # Python package config (Hatchling build backend)
  package.json                  # JS/TS package config
  Makefile                      # Dev workflow: lint, test, build, publish

  spec/
    RELAY_SPEC.md               # Full wire format specification (authoritative)
    RELAY_TEXT_FORMAT.md        # Text encoding specification
    RELAY_SCHEMA_REGISTRY.md    # Schema registry protocol
    RELAY_ERRORS.md             # Complete error code table
    RELAY_TYPES.md              # Semantic type definitions and binary encodings
    RELAY_REFERENCE.md          # Reference semantics specification

  relay/                        # Python package
    __init__.py
    types.py                    # All Relay types as Python dataclasses + validators
    schema.py                   # Schema definition, hashing, registry client
    encoder.py                  # Python object -> binary Relay bytes
    decoder.py                  # Binary Relay bytes -> Python objects (streaming)
    text_encoder.py             # Python object -> .relay text format
    text_decoder.py             # .relay text -> Python objects
    delta.py                    # Delta message construction and application
    reference.py                # Reference resolution within a session context
    session.py                  # Session context: tracks outputs for $ref resolution
    errors.py                   # RelayError hierarchy with error codes
    registry.py                 # Local schema registry (file-backed + in-memory)
    validate.py                 # Schema validation logic
    compat/
      json_compat.py            # relay.compat.from_json(), relay.compat.to_json()
      openai_compat.py          # Convert OpenAI tool call format to/from Relay
      anthropic_compat.py       # Convert Anthropic tool use blocks to/from Relay
    cli/
      __init__.py
      main.py                   # relay CLI entrypoint
      commands/
        inspect.py              # relay inspect <file>: pretty-print binary Relay
        validate.py             # relay validate <file> --schema <schema_id>
        convert.py              # relay convert --from json --to relay <file>
        schema.py               # relay schema register/list/show
        bench.py                # relay bench: encode/decode throughput vs JSON

  relay-js/                     # TypeScript/JavaScript package
    src/
      types.ts
      schema.ts
      encoder.ts
      decoder.ts
      text_encoder.ts
      text_decoder.ts
      delta.ts
      reference.ts
      session.ts
      errors.ts
      registry.ts
      validate.ts
      compat/
        json.ts
        openai.ts
        anthropic.ts
    tests/
    package.json
    tsconfig.json
    rollup.config.js            # Builds ESM + CJS + types

  tests/                        # Python tests
    conftest.py
    test_types.py
    test_encoder.py
    test_decoder.py
    test_text_format.py
    test_delta.py
    test_reference.py
    test_session.py
    test_schema.py
    test_validate.py
    test_compat_json.py
    test_compat_openai.py
    test_compat_anthropic.py
    test_cli.py
    test_bench.py
    fixtures/
      sample_messages/          # Binary and text Relay fixtures for all types
      sample_schemas/           # Schema registry fixtures

  benchmarks/
    bench_encode.py
    bench_decode.py
    bench_vs_json.py
    bench_vs_msgpack.py
    results/
      latest.json               # Updated by CI on every merge to main

  docs/
    index.md
    quickstart.md
    wire_format.md
    text_format.md
    schema_guide.md
    types_reference.md
    delta_guide.md
    reference_guide.md
    compat_guide.md
    cli_reference.md
    faq.md
    CHANGELOG.md

  .github/
    workflows/
      ci.yml                    # lint, test, build on push and PR
      publish-pypi.yml          # publish on tag push
      publish-npm.yml           # publish JS on tag push
      bench.yml                 # run benchmarks on merge to main
```

---

## Wire Format Specification

Implement exactly this binary layout. Full spec lives in `spec/RELAY_SPEC.md`.

### Frame Header (12 bytes, fixed)

```
Offset  Size  Field
0       1     Magic byte: 0xRE (decimal 222)
1       1     Version: uint8, currently 0x01
2       2     Message type: uint16 LE
              0x0001 = FULL
              0x0002 = DELTA
              0x0003 = REF_ONLY (message is entirely a reference to prior output)
              0x0004 = SCHEMA_DEF (message carries a schema definition)
              0x0005 = ERROR
4       4     Schema hash: first 4 bytes of SHA-256 of canonical schema JSON
8       4     Payload length: uint32 LE, length of payload bytes following header
```

### Payload Encoding

The payload is a sequence of field frames. Each field frame:

```
Offset  Size  Field
0       2     Field ID: uint16 LE (maps to field name via schema)
2       1     Type tag: uint8 (see type table below)
3       4     Field length: uint32 LE
7       N     Field value bytes
```

### Type Tags

```
0x01  null
0x02  bool
0x03  int8
0x04  int16
0x05  int32
0x06  int64
0x07  uint8
0x08  uint16
0x09  uint32
0x0A  uint64
0x0B  float32
0x0C  float64
0x0D  string (UTF-8 bytes)
0x0E  bytes (raw binary)
0x0F  array (length-prefixed sequence of field frames)
0x10  object (nested field frame sequence)
0x11  uuid (16 bytes, RFC 4122)
0x12  datetime (8 bytes: int64 LE microseconds since Unix epoch, UTC)
0x13  uri (UTF-8 bytes, validated as RFC 3986)
0x14  vector (4 bytes dtype tag + 4 bytes dim + dim * element bytes)
       dtype tags: 0x01=float16, 0x02=float32, 0x03=float64, 0x04=int8
0x15  enum (4 bytes: uint32 enum value index, validated against schema)
0x16  code_block (2 bytes lang length + lang UTF-8 + 4 bytes code length + code UTF-8)
0x17  markdown_block (4 bytes length + UTF-8 bytes)
0x18  ref (variable: session_id as 16-byte UUID + uint32 call_index + field path as null-terminated UTF-8)
0x19  delta_op (see delta specification)
```

---

## Text Format Specification

The text format is the canonical human-readable and LLM-emittable form. Full spec in `spec/RELAY_TEXT_FORMAT.md`.

```
@relay 1.0
@schema agent_tool_call:a3f2bc01
@type FULL

role: enum<MessageRole>.assistant
content: markdown_block
  """
  Here is the result of the calculation.
  """
tool_call: object
  id: uuid "550e8400-e29b-41d4-a716-446655440000"
  name: string "calculate_npv"
  arguments: object
    cash_flows: vector<float64, 5> [100.0, 200.0, 300.0, 400.0, 500.0]
    discount_rate: float64 0.08
    created_at: datetime "2025-04-01T12:00:00Z"
```

Rules:
- First line is always `@relay <version>`
- Second line is `@schema <name>:<4-byte-hash-hex>`
- Third line is `@type <message_type>`
- Fields are `<name>: <type> <value>`
- Nested objects indent with 2 spaces
- Multiline string values use triple-quoted blocks
- `$ref` syntax: `$ref session:<uuid>.call[3].output.embedding`

---

## Schema Definition Format

Schemas are defined in `.rschema` files, registered to a local file-backed registry, and referenced by 4-byte hash.

```
schema agent_tool_call {
  version: 1
  fields:
    role:       enum<MessageRole> required
    content:    markdown_block    optional
    tool_call:  object            optional {
      id:       uuid              required
      name:     string            required
      arguments: object           required
    }
    result:     object            optional {
      output:   any               required
      error:    string            optional
    }
}

enum MessageRole {
  system
  user
  assistant
  tool
}
```

The schema registry stores schemas keyed by `name:hash`. The CLI provides `relay schema register <file>` and `relay schema list`.

---

## Delta Message Specification

Full spec in `spec/RELAY_REFERENCE.md`. Delta messages reference a prior FULL message by session ID and call index, then express a sequence of operations.

Operations:

```
SET   <field_path> <type> <value>      # Replace field value
DEL   <field_path>                     # Remove field
APP   <field_path> <type> <value>      # Append to array field
SPL   <field_path> <start> <end> <type> <value>  # Splice array range
```

Example text encoding of a DELTA:

```
@relay 1.0
@schema agent_tool_call:a3f2bc01
@type DELTA
@base $ref session:550e8400.call[2]

SET  tool_call.arguments.discount_rate float64 0.10
SET  tool_call.id uuid "661f9511-f3ac-52e5-b827-557766551111"
```

---

## Python Package Requirements

### Dependencies

```toml
[project]
name = "relay-format"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
  "pydantic>=2.0",
  "click>=8.0",
  "rich>=13.0",
  "msgpack>=1.0",
  "numpy>=1.24",
]

[project.optional-dependencies]
dev = [
  "pytest>=7.0",
  "pytest-cov",
  "hypothesis",
  "black",
  "ruff",
  "mypy",
]
```

### Public API Surface

The Python package must expose this exact API at `import relay`:

```python
# Encoding
relay.encode(obj: dict, schema: RelaySchema) -> bytes
relay.encode_text(obj: dict, schema: RelaySchema) -> str

# Decoding
relay.decode(data: bytes) -> RelayMessage
relay.decode_text(text: str) -> RelayMessage
relay.decode_stream(stream: BinaryIO) -> Iterator[RelayMessage]

# Schema
relay.Schema.from_file(path: str) -> RelaySchema
relay.Schema.from_dict(d: dict) -> RelaySchema
relay.registry.register(schema: RelaySchema) -> str  # returns hash
relay.registry.get(name: str, hash: str) -> RelaySchema

# Delta
relay.delta(base: RelayMessage, operations: list[DeltaOp]) -> bytes
relay.apply_delta(base: RelayMessage, delta: RelayMessage) -> RelayMessage

# Session
session = relay.Session()
session.record(message: RelayMessage) -> int  # returns call index
session.resolve_ref(ref: RelayRef) -> Any

# Compat
relay.compat.from_json(data: dict, schema: RelaySchema) -> bytes
relay.compat.to_json(data: bytes) -> dict
relay.compat.from_openai_tool_call(call: dict) -> bytes
relay.compat.from_anthropic_tool_use(block: dict) -> bytes

# Errors
relay.RelayError          # base
relay.SchemaNotFoundError
relay.TypeMismatchError
relay.ReferenceError
relay.DeltaConflictError
relay.ParseError
```

---

## TypeScript Package Requirements

The JS/TS package (`relay-js/`) must mirror the Python API exactly with TypeScript-native idioms. It must build to:
- ESM (`dist/relay.esm.js`)
- CJS (`dist/relay.cjs.js`)
- Type declarations (`dist/relay.d.ts`)

It must work in Node.js 18+ and modern browsers (via ESM). Use `TextEncoder`/`TextDecoder` for string encoding. Use `DataView` for binary frame construction. Do not use any runtime dependencies other than the standard library.

---

## CLI Requirements

The CLI is installed as `relay` on the system PATH via the Python package entrypoint.

```
relay inspect <file.relay>
  --format [pretty|json|text]
  --schema <schema_id>

relay validate <file.relay>
  --schema <schema_id>

relay convert <file>
  --from [json|msgpack|openai|anthropic]
  --to   [relay|relay-text|json|msgpack]
  --schema <schema_id>

relay schema register <file.rschema>
relay schema list
relay schema show <name:hash>
relay schema hash <file.rschema>

relay bench
  --iterations 10000
  --payload-size [small|medium|large]
  --compare [json|msgpack|both]
```

All CLI output uses `rich` for formatting. `relay inspect` renders a color-coded tree of field names, types, and values.

---

## Test Requirements

Every module must have 100% line coverage. Use `pytest` with `pytest-cov`. Use `hypothesis` for property-based testing on the encoder and decoder: any Python dict conforming to a schema must round-trip through binary encode -> decode and text encode -> decode with exact value equality.

Required test cases that must exist and pass:

1. Encode and decode every type tag (0x01 through 0x19) with correct byte layout
2. Round-trip: Python dict -> binary -> Python dict, value equality
3. Round-trip: Python dict -> text -> Python dict, value equality
4. Round-trip: binary -> text -> binary, byte equality
5. Schema hash stability: same schema content always produces same 4-byte hash
6. Schema validation rejects missing required fields with `SchemaNotFoundError`
7. Type mismatch raises `TypeMismatchError` with correct field path in error message
8. Reference resolution: encode a FULL message, record in session, encode a REF_ONLY message pointing to a field, resolve to correct value
9. Delta apply: encode FULL, construct DELTA with SET and DEL ops, apply delta, verify result
10. Streaming decode: split a binary Relay message into 1-byte chunks, feed to `decode_stream`, verify correct reassembly
11. Compat round-trip: OpenAI tool call dict -> Relay -> JSON, value equality
12. Compat round-trip: Anthropic tool use block -> Relay -> JSON, value equality
13. CLI `relay inspect` on a binary fixture produces non-empty rich output without error
14. CLI `relay validate` on a valid fixture exits 0; on an invalid fixture exits 1
15. Benchmark: encode throughput >= 2x JSON encode throughput for a 1KB payload (hypothesis: MessagePack baseline suggests this is achievable)

---

## Documentation Requirements

Every public Python function and class must have a NumPy-style docstring with Parameters, Returns, Raises, and at least one Example. The `docs/` directory must be buildable with MkDocs + Material theme. `docs/quickstart.md` must include a complete working example that goes from raw Python dict to binary Relay bytes to decoded Python dict in under 20 lines of code.

---

## Benchmark Targets

These are minimum acceptable performance targets on a 2023 MacBook Pro M2 with Python 3.11:

| Operation         | Target                          |
|-------------------|---------------------------------|
| Encode 1KB FULL   | >= 2x JSON encode throughput    |
| Decode 1KB FULL   | >= 1.5x JSON decode throughput  |
| Encode 1KB DELTA  | >= 5x full FULL encode (delta is smaller payload)  |
| Schema validation | < 50 microseconds per message   |
| Ref resolution    | < 10 microseconds per lookup    |

Run `relay bench` to measure. Results are written to `benchmarks/results/latest.json` and committed by CI.

---

## Build and Publish Workflow

```makefile
# Makefile targets that must exist and work:

lint:
  ruff check relay/ && mypy relay/ && black --check relay/

test:
  pytest tests/ --cov=relay --cov-report=term-missing --cov-fail-under=100

build:
  python -m build
  cd relay-js && npm run build

publish-pypi:
  twine upload dist/*

publish-npm:
  cd relay-js && npm publish

docs:
  mkdocs build

bench:
  python benchmarks/bench_vs_json.py > benchmarks/results/latest.json
```

CI runs `lint` and `test` on every push and PR. `publish-pypi` and `publish-npm` run on tag push matching `v*.*.*`.

---

## What You Must Not Do

- Do not use JSON as an intermediate representation internally. Relay's binary encoder must operate directly on Python objects.
- Do not use `json.dumps` anywhere in the encoder or decoder stack.
- Do not silently coerce types. A `float32` field receiving a Python `int` raises `TypeMismatchError` unless the schema explicitly marks the field as `numeric` (which accepts both).
- Do not build a schema-optional mode. Every Relay message has a schema. There is no schemaless Relay.
- Do not add a `metadata` catch-all field to any schema. Every field must be explicitly typed.
- Do not use `Any` in the TypeScript package except in the compat layer where the source format is genuinely untyped.
- Do not write a single test that uses `assert result is not None` as the only assertion. Every assertion must check a specific value or structure.

---

## Definition of Done

The project is complete when:

1. `pip install relay-format` installs successfully on Python 3.10, 3.11, 3.12
2. `npm install relay-format` installs successfully on Node 18+
3. All 15 required test cases pass with 100% line coverage
4. All benchmark targets are met and documented in `benchmarks/results/latest.json`
5. `relay inspect`, `relay validate`, `relay convert`, `relay schema`, and `relay bench` all function correctly
6. `mkdocs build` completes without warnings
7. The compat layer correctly round-trips a real OpenAI `gpt-4o` tool call response and a real Anthropic `claude-sonnet-4-20250514` tool use block
8. The GitHub repository has a passing CI badge, a populated README with quickstart, and a published PyPI and npm package