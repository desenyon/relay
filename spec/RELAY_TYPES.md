# Relay Semantic Type Definitions

**Version**: 1.0
**Status**: Authoritative
**Authors**: Naitik Gupta / Saerin Research
**Last Updated**: 2026-04-01

---

## 1. Overview

This document specifies all 25 Relay type tags, their binary encoding, Python and TypeScript representations, validation rules, and error conditions. Each type is identified by a 1-byte type tag used in field frames (see `RELAY_SPEC.md`).

Types are organized into three categories:

1. **Primitive types** (0x01–0x0E): Basic scalar and raw binary types.
2. **Structural types** (0x0F–0x10): Arrays and nested objects.
3. **Semantic types** (0x11–0x19): Domain-specific types with validation and compact binary encodings.

---

## 2. Type Tag Summary

| Tag    | Name             | Python Type             | TS Type                 | Fixed Size |
|--------|------------------|-------------------------|-------------------------|------------|
| `0x01` | `null`           | `None`                  | `null`                  | 0          |
| `0x02` | `bool`           | `bool`                  | `boolean`               | 1          |
| `0x03` | `int8`           | `int`                   | `number`                | 1          |
| `0x04` | `int16`          | `int`                   | `number`                | 2          |
| `0x05` | `int32`          | `int`                   | `number`                | 4          |
| `0x06` | `int64`          | `int`                   | `bigint`                | 8          |
| `0x07` | `uint8`          | `int`                   | `number`                | 1          |
| `0x08` | `uint16`         | `int`                   | `number`                | 2          |
| `0x09` | `uint32`         | `int`                   | `number`                | 4          |
| `0x0A` | `uint64`         | `int`                   | `bigint`                | 8          |
| `0x0B` | `float32`        | `float`                 | `number`                | 4          |
| `0x0C` | `float64`        | `float`                 | `number`                | 8          |
| `0x0D` | `string`         | `str`                   | `string`                | variable   |
| `0x0E` | `bytes`          | `bytes`                 | `Uint8Array`            | variable   |
| `0x0F` | `array`          | `list`                  | `Array<T>`              | variable   |
| `0x10` | `object`         | `dict`                  | `Record<string, T>`     | variable   |
| `0x11` | `uuid`           | `uuid.UUID`             | `string`                | 16         |
| `0x12` | `datetime`       | `datetime.datetime`     | `Date`                  | 8          |
| `0x13` | `uri`            | `str`                   | `string`                | variable   |
| `0x14` | `vector`         | `numpy.ndarray`         | `Float32Array` etc.     | variable   |
| `0x15` | `enum`           | `int`                   | `number`                | 4          |
| `0x16` | `code_block`     | `CodeBlock`             | `CodeBlock`             | variable   |
| `0x17` | `markdown_block` | `str`                   | `string`                | variable   |
| `0x18` | `ref`            | `RelayRef`              | `RelayRef`              | variable   |
| `0x19` | `delta_op`       | `DeltaOp`               | `DeltaOp`               | variable   |

---

## 3. Primitive Types

### 3.1 `null` — Tag `0x01`

**Purpose**: Represents the absence of a value.

**Binary encoding**: Zero bytes. The field frame has `field_length = 0` and no value bytes follow.

**Validation rules**:
- The field length must be exactly 0. Any non-zero length raises `ParseError` (E001).
- A `null` value may only be used in a field declared as `optional` or as a nullable type in the schema. Encoding a `null` for a `required` field raises `ValidationError` (E006).

**Python**: `None`
**TypeScript**: `null`

**Example (text format)**:
```
error_detail: null
```

---

### 3.2 `bool` — Tag `0x02`

**Purpose**: Boolean true/false.

**Binary encoding**: 1 byte.
- `0x00` = `false`
- `0x01` = `true`
- Any other byte value raises `ParseError` (E001).

**Validation rules**: Field length must be exactly 1.

**Python**: `bool`
**TypeScript**: `boolean`

**Text format values**: `true`, `false` (unquoted lowercase keywords).

---

### 3.3 Integer Types — Tags `0x03`–`0x0A`

Eight integer types covering the full signed/unsigned range:

| Tag    | Name     | Bytes | Range |
|--------|----------|-------|-------|
| `0x03` | `int8`   | 1     | -128 to 127 |
| `0x04` | `int16`  | 2     | -32,768 to 32,767 |
| `0x05` | `int32`  | 4     | -2,147,483,648 to 2,147,483,647 |
| `0x06` | `int64`  | 8     | -9,223,372,036,854,775,808 to 9,223,372,036,854,775,807 |
| `0x07` | `uint8`  | 1     | 0 to 255 |
| `0x08` | `uint16` | 2     | 0 to 65,535 |
| `0x09` | `uint32` | 4     | 0 to 4,294,967,295 |
| `0x0A` | `uint64` | 8     | 0 to 18,446,744,073,709,551,615 |

**Binary encoding**: Little-endian two's complement for signed types; little-endian unsigned for unsigned types.

**Validation rules**:
- Field length must exactly match the byte count for the type.
- During encoding, the Python `int` value must fit in the declared range. Values out of range raise `TypeMismatchError` (E002) with the field path and the out-of-range value in the error context.
- Python `float` values passed to integer fields raise `TypeMismatchError` (E002). No implicit coercion.
- Python `bool` values passed to integer fields raise `TypeMismatchError` (E002). Bools are not ints in Relay.

**Python**: `int`
**TypeScript**: `number` for 8/16/32-bit types; `bigint` for 64-bit types (since JavaScript `number` cannot represent all 64-bit integers).

---

### 3.4 `float32` — Tag `0x0B`

**Purpose**: 32-bit IEEE 754 floating-point number.

**Binary encoding**: 4 bytes, IEEE 754 single-precision, little-endian byte order.

**Validation rules**:
- Field length must be exactly 4.
- Python `int` values passed to `float32` fields raise `TypeMismatchError` (E002). No implicit int-to-float coercion unless the schema declares `numeric` mode (reserved for future use).
- `NaN`, `Inf`, and `-Inf` are valid float32 values. They encode as their standard IEEE 754 bit patterns.
- Precision: Python `float` (float64) values are narrowed to float32 precision. Values that overflow float32 (absolute value > 3.4028235e+38) raise `ValidationError` (E006).

**Python**: `float`
**TypeScript**: `number`

---

### 3.5 `float64` — Tag `0x0C`

**Purpose**: 64-bit IEEE 754 floating-point number.

**Binary encoding**: 8 bytes, IEEE 754 double-precision, little-endian byte order.

**Validation rules**:
- Field length must be exactly 8.
- Same int-coercion rules as `float32`.
- `NaN`, `Inf`, and `-Inf` are valid.

**Python**: `float`
**TypeScript**: `number`

---

### 3.6 `string` — Tag `0x0D`

**Purpose**: UTF-8 text string of arbitrary length.

**Binary encoding**: Raw UTF-8 bytes. No null terminator. No length prefix (the field frame's `field_length` provides the length).

**Validation rules**:
- The value bytes must be valid UTF-8. Invalid byte sequences raise `ParseError` (E001) with the byte offset of the invalid sequence.
- Empty strings (field_length = 0) are valid.
- No maximum length is enforced at the wire level, but implementations may impose limits.

**Python**: `str`
**TypeScript**: `string`

---

### 3.7 `bytes` — Tag `0x0E`

**Purpose**: Raw binary data with no encoding or interpretation.

**Binary encoding**: The value bytes are the raw binary data verbatim.

**Validation rules**:
- No content validation (any byte sequence is valid).
- Empty bytes (field_length = 0) are valid.

**Python**: `bytes`
**TypeScript**: `Uint8Array`

---

## 4. Structural Types

### 4.1 `array` — Tag `0x0F`

**Purpose**: An ordered, homogeneous sequence of values.

**Binary encoding**:

```
Offset  Size  Field
0       4     count: uint32 LE — number of elements
4       ...   element frames (count repetitions)
```

Each element frame has the structure:

```
[field_id: 0x0000, 2 bytes][type_tag: 1 byte][elem_length: 4 bytes][value: elem_length bytes]
```

The field ID for all array elements is `0x0000`.

**Validation rules**:
- All elements must have the same type tag. Heterogeneous element types raise `TypeMismatchError` (E002).
- The schema declares the element type. The type tag of each element must match. A mismatch raises `TypeMismatchError` (E002).
- A count of 0 is valid (empty array).
- The total bytes consumed by all element frames must equal `field_length - 4` (subtracting the count prefix).

**Python**: `list`
**TypeScript**: `Array<T>`

### 4.2 `object` — Tag `0x10`

**Purpose**: A nested key-value structure.

**Binary encoding**: A sequence of field frames, identical in structure to the top-level payload. The field IDs are resolved against the sub-schema for this field as declared in the parent schema.

**Validation rules**:
- The schema must declare a sub-schema for this field. An object field without a sub-schema declaration raises `ValidationError` (E006) during encoding.
- All required sub-fields must be present.
- Unknown sub-fields (field IDs not in the sub-schema) raise `TypeMismatchError` (E002).
- The total byte count of all nested field frames must equal `field_length`.

**Python**: `dict`
**TypeScript**: `Record<string, unknown>` (typed more precisely by generated types)

---

## 5. Semantic Types

### 5.1 `uuid` — Tag `0x11`

**Purpose**: A Universally Unique Identifier per RFC 4122.

**Binary encoding**: 16 bytes in RFC 4122 binary form (big-endian byte order, as transmitted over networks).

The 16-byte layout corresponds to the standard UUID fields in network byte order:
```
Bytes 0–3:   time_low (big-endian)
Bytes 4–5:   time_mid (big-endian)
Bytes 6–7:   time_hi_and_version (big-endian)
Byte  8:     clock_seq_hi_and_reserved
Byte  9:     clock_seq_low
Bytes 10–15: node
```

**Validation rules**:
- Field length must be exactly 16.
- All 16 bytes are stored as-is. No validation of UUID version or variant bits during decoding (accept any UUID).
- During encoding, a Python `uuid.UUID` object or a standard hyphenated UUID string is accepted. An invalid UUID string raises `ValidationError` (E006).

**Python**: `uuid.UUID`
**TypeScript**: `string` (standard hyphenated form: `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`)

**Text format**: Quoted string in standard hyphenated lowercase form.

```
id: uuid "550e8400-e29b-41d4-a716-446655440000"
```

---

### 5.2 `datetime` — Tag `0x12`

**Purpose**: A UTC timestamp with microsecond precision.

**Binary encoding**: 8 bytes, signed int64 little-endian, representing **microseconds since the Unix epoch** (1970-01-01T00:00:00Z). Negative values represent timestamps before the Unix epoch.

**Range**: -9,223,372,036,854,775,808 to 9,223,372,036,854,775,807 microseconds since epoch, which covers roughly ±292,277 years.

**Validation rules**:
- Field length must be exactly 8.
- During encoding, the `datetime` value must be timezone-aware and in UTC. Naive (tz-unaware) datetimes raise `ValidationError` (E006). Non-UTC datetimes raise `ValidationError` (E006).
- During decoding, the decoded `datetime` is always timezone-aware UTC.

**Python**: `datetime.datetime` (always `tzinfo=datetime.timezone.utc`)
**TypeScript**: `Date`

**Text format**: Quoted ISO 8601 string with `Z` suffix or `+00:00` offset.

```
created_at: datetime "2025-04-01T12:00:00.123456Z"
```

---

### 5.3 `uri` — Tag `0x13`

**Purpose**: A Uniform Resource Identifier per RFC 3986.

**Binary encoding**: Raw UTF-8 bytes (same as `string`). The `field_length` gives the byte count.

**Validation rules**:
- The value must be valid UTF-8.
- The value must be a syntactically valid URI per RFC 3986. Implementations must validate at minimum:
  - The scheme component is present and contains only letters, digits, `+`, `-`, `.`.
  - The authority component (if present) is syntactically valid.
  - Percent-encoded sequences use valid hex digits.
- Invalid URIs raise `ValidationError` (E006) with the offending value in the error context.
- Relative references (URIs without a scheme) are rejected unless the schema field is declared as `uri_reference`.
- DNS resolution is not performed.

**Python**: `str` (stored as a string; validated but not parsed into components)
**TypeScript**: `string`

**Text format**: Quoted string.

```
endpoint: uri "https://api.example.com/v1/tools"
```

---

### 5.4 `vector` — Tag `0x14`

**Purpose**: A typed numeric array (embedding, tensor row, etc.) with declared dtype and dimension.

**Binary encoding**:

```
Offset  Size  Field
0       4     dtype_tag: uint32 LE
4       4     dim: uint32 LE — number of elements
8       N     elements: dim * element_size bytes, each element little-endian
```

**Dtype tags**:

| dtype_tag    | Name      | Element size | NumPy dtype | Notes |
|--------------|-----------|--------------|-------------|-------|
| `0x00000001` | `float16` | 2 bytes      | `float16`   | IEEE 754 half-precision |
| `0x00000002` | `float32` | 4 bytes      | `float32`   | IEEE 754 single-precision |
| `0x00000003` | `float64` | 8 bytes      | `float64`   | IEEE 754 double-precision |
| `0x00000004` | `int8`    | 1 byte       | `int8`      | Signed 8-bit integer |

**Validation rules**:
- Field length must equal `8 + dim * element_size`. Mismatch raises `ParseError` (E001).
- The `dim` in the binary value must match the schema-declared dimension. Mismatch raises `TypeMismatchError` (E002).
- The `dtype_tag` must match the schema-declared dtype. Mismatch raises `TypeMismatchError` (E002).
- An unknown `dtype_tag` raises `ParseError` (E001).
- `NaN` and `Inf` values are valid in float16/float32/float64 vectors.
- `int8` vectors do not support `NaN` or `Inf`; values outside [-128, 127] during encoding raise `ValidationError` (E006).

**Python**: `numpy.ndarray` with matching `dtype` and shape `(dim,)`.
**TypeScript**:
- `float16`: `Uint16Array` (raw IEEE 754 half-precision bits)
- `float32`: `Float32Array`
- `float64`: `Float64Array`
- `int8`: `Int8Array`

**Schema declaration**:
```
embedding: vector<float64, 1536>  required
```

**Text format** (inline for small vectors):
```
embedding: vector<float64, 5> [1.0, 2.0, 3.0, 4.0, 5.0]
```

---

### 5.5 `enum` — Tag `0x15`

**Purpose**: A named enumeration value, encoded as a compact integer index.

**Binary encoding**: 4 bytes, uint32 little-endian, containing the 0-based index of the enum value in the schema's enum declaration.

**Validation rules**:
- Field length must be exactly 4.
- The index must be within the range `[0, len(enum_values) - 1]`. An out-of-range index raises `ValidationError` (E006).
- The enum type name (e.g., `MessageRole`) must be declared in the schema and the field must reference it. Type name mismatches raise `TypeMismatchError` (E002).

**Python**: `int` (the index value); the encoder also accepts a string matching the symbolic name.
**TypeScript**: `number` (the index value); typed enums generated from schema.

**Schema declaration**:
```
enum MessageRole {
  system      # index 0
  user        # index 1
  assistant   # index 2
  tool        # index 3
}
```

**Text format**: Symbolic name (not the integer index).
```
role: enum<MessageRole> assistant
```

The encoder resolves "assistant" to index 2 when writing binary.

---

### 5.6 `code_block` — Tag `0x16`

**Purpose**: Source code with an associated programming language identifier.

**Binary encoding**:

```
Offset  Size    Field
0       2       lang_length: uint16 LE — byte length of language string
2       L       lang: UTF-8 string, L = lang_length bytes
2+L     4       code_length: uint32 LE — byte length of source code
6+L     C       code: UTF-8 string, C = code_length bytes
```

Total field length: `2 + lang_length + 4 + code_length`.

**Validation rules**:
- `lang_length` must be > 0. Empty language strings raise `ValidationError` (E006).
- `lang` must be valid UTF-8.
- `code` must be valid UTF-8. Empty code strings (code_length = 0) are valid.
- The `lang` tag in the schema type (`code_block<python>`) must match the `lang` string in the binary value. Mismatch raises `TypeMismatchError` (E002).
- The total `field_length` must equal `2 + lang_length + 4 + code_length`. Mismatch raises `ParseError` (E001).

**Standard language identifiers** (informative, not exhaustive):

| Identifier     | Language |
|----------------|----------|
| `python`       | Python |
| `javascript`   | JavaScript |
| `typescript`   | TypeScript |
| `rust`         | Rust |
| `go`           | Go |
| `java`         | Java |
| `c`            | C |
| `cpp`          | C++ |
| `sql`          | SQL |
| `bash`         | Bash/Shell |
| `json`         | JSON |
| `yaml`         | YAML |
| `html`         | HTML |
| `css`          | CSS |

Language identifiers are case-insensitive during comparison but are stored and returned in lowercase canonical form.

**Python**:
```python
@dataclass
class CodeBlock:
    lang: str
    code: str
```

**TypeScript**:
```typescript
interface CodeBlock {
  lang: string;
  code: string;
}
```

**Text format**:
```
snippet: code_block<python>
  """
  def hello():
      return "world"
  """
```

---

### 5.7 `markdown_block` — Tag `0x17`

**Purpose**: A block of Markdown-formatted text, semantically distinct from a plain string.

**Binary encoding**: Raw UTF-8 bytes (identical layout to `string`). The distinction from `string` is semantic: consumers know this field contains Markdown and may render it accordingly.

**Validation rules**:
- The value must be valid UTF-8.
- No Markdown syntax validation is performed at the wire level. Any valid UTF-8 string is accepted.
- Empty markdown_block (field_length = 0) is valid.

**Python**: `str`
**TypeScript**: `string`

**Text format**:
```
content: markdown_block
  """
  # Heading

  This is **bold** and *italic*.
  """
```

---

### 5.8 `ref` — Tag `0x18`

**Purpose**: A reference to a field value in a prior session output, enabling cross-message references without retransmitting the value.

**Binary encoding**:

```
Offset  Size   Field
0       16     session_id: UUID in RFC 4122 binary form (big-endian)
16      4      call_index: uint32 LE — 0-based index of the call in the session
20      N+1    field_path: null-terminated UTF-8 string
```

The field path:
- Uses `.` as the separator between field names: `output.embedding`
- Uses `[N]` for array indexing: `messages[2].content`
- May be empty (just the null terminator `\x00`), meaning the entire message output

Total field length: `16 + 4 + len(field_path_utf8) + 1`.

**Validation rules**:
- The 16-byte `session_id` must be a valid RFC 4122 UUID.
- The `field_path` must be valid UTF-8.
- During resolution (not at parse time), the referenced session, call, and field path must exist. Non-existent references raise `ReferenceError` (E004).

**Python**:
```python
@dataclass
class RelayRef:
    session_id: uuid.UUID
    call_index: int
    field_path: str  # empty string means the entire message output
```

**TypeScript**:
```typescript
interface RelayRef {
  sessionId: string;  // standard hyphenated UUID form
  callIndex: number;
  fieldPath: string;
}
```

**Text format**:
```
embedding_ref: ref $ref session:550e8400-e29b-41d4-a716-446655440000.call[3].output.embedding
```

See `RELAY_REFERENCE.md` for reference resolution semantics.

---

### 5.9 `delta_op` — Tag `0x19`

**Purpose**: Encodes a single mutation operation in a DELTA message.

**Binary encoding**:

```
Offset  Size   Field
0       1      opcode: uint8
1       N+1    field_path: null-terminated UTF-8 string
...            opcode-specific payload
```

**Opcodes**:

| Opcode  | Name  | Additional Payload |
|---------|-------|--------------------|
| `0x01`  | `SET` | type_tag (1B) + value_length (4B) + value bytes |
| `0x02`  | `DEL` | (none) |
| `0x03`  | `APP` | type_tag (1B) + value_length (4B) + value bytes |
| `0x04`  | `SPL` | start (4B uint32 LE) + end (4B uint32 LE) + type_tag (1B) + value_length (4B) + value bytes |

Complete `delta_op` layout for `SET`:
```
[opcode=0x01][field_path\x00][type_tag][value_length uint32 LE][value bytes]
```

Complete `delta_op` layout for `SPL`:
```
[opcode=0x04][field_path\x00][start uint32 LE][end uint32 LE][type_tag][value_length uint32 LE][value bytes]
```

**Validation rules**:
- Unknown opcodes raise `ParseError` (E001).
- `DEL` operations on required fields raise `ValidationError` (E006).
- `APP` operations on non-array fields raise `TypeMismatchError` (E002).
- `SPL` with `end < start` raises `ValidationError` (E006).
- `SPL` with `start` or `end` out of array bounds raises `DeltaConflictError` (E005).

**Python**:
```python
@dataclass
class DeltaOp:
    opcode: str  # "SET" | "DEL" | "APP" | "SPL"
    field_path: str
    type_tag: int | None  # None for DEL
    value: Any | None     # None for DEL; (start, end, value) tuple for SPL
```

**TypeScript**:
```typescript
type DeltaOp =
  | { op: "SET"; path: string; typeTag: number; value: unknown }
  | { op: "DEL"; path: string }
  | { op: "APP"; path: string; typeTag: number; value: unknown }
  | { op: "SPL"; path: string; start: number; end: number; typeTag: number; value: unknown };
```

See `RELAY_REFERENCE.md` for delta application semantics.

---

## 6. Type Coercion Rules

Relay does not perform silent type coercion. The following table summarizes what is and is not permitted during encoding:

| Source Python type | Target Relay type | Result |
|-------------------|-------------------|--------|
| `int`             | `int8`–`int64`, `uint8`–`uint64` | OK if in range; `TypeMismatchError` (E002) if out of range |
| `int`             | `float32`, `float64` | `TypeMismatchError` (E002) — no implicit int-to-float |
| `float`           | `int8`–`uint64` | `TypeMismatchError` (E002) — no implicit float-to-int |
| `bool`            | `bool` | OK |
| `bool`            | `int8`–`uint64` | `TypeMismatchError` (E002) — bool is not int in Relay |
| `str`             | `string` | OK |
| `str`             | `uuid` | OK if valid UUID format |
| `str`             | `uri` | OK if valid RFC 3986 |
| `str`             | `datetime` | OK if valid ISO 8601 UTC |
| `str`             | `enum` | OK if matches a declared symbolic name |
| `uuid.UUID`       | `uuid` | OK |
| `datetime`        | `datetime` | OK if tz-aware UTC |
| `numpy.ndarray`   | `vector` | OK if matching dtype and shape |
| `list`            | `vector` | OK if all elements match dtype and length matches dim |
| `None`            | any optional field | OK (encoded as `null` tag or field omitted) |
| `None`            | any required field | `ValidationError` (E006) |

---

## 7. Schema Type Syntax

In `.rschema` files, types are declared using the following syntax:

```
<field_name>: <type_declaration>  [required | optional]
```

Type declarations:

| Declaration          | Maps to type tag |
|----------------------|-----------------|
| `null`               | `0x01` |
| `bool`               | `0x02` |
| `int8` ... `uint64`  | `0x03`–`0x0A` |
| `float32`            | `0x0B` |
| `float64`            | `0x0C` |
| `string`             | `0x0D` |
| `bytes`              | `0x0E` |
| `array[<type>]`      | `0x0F` |
| `object { ... }`     | `0x10` |
| `uuid`               | `0x11` |
| `datetime`           | `0x12` |
| `uri`                | `0x13` |
| `vector<dtype, N>`   | `0x14` |
| `enum<EnumName>`     | `0x15` |
| `code_block<lang>`   | `0x16` |
| `markdown_block`     | `0x17` |
| `ref`                | `0x18` |
| `any`                | (compat layer only; not valid in core schemas) |

---

## 8. Type Validation Checklist

Implementations must validate the following on every encode and decode:

| Check | On Encode | On Decode |
|-------|-----------|-----------|
| Type tag matches schema-declared type | yes | yes |
| Fixed-size types have correct `field_length` | yes | yes |
| Variable-size types have non-negative `field_length` | yes | yes |
| `null` type has `field_length = 0` | yes | yes |
| `bool` value is `0x00` or `0x01` | yes | yes |
| Integer values in declared range | yes | no (decode as-is) |
| `string`/`uri`/`markdown_block` bytes are valid UTF-8 | yes | yes |
| `uuid` field_length = 16 | yes | yes |
| `datetime` field_length = 8 | yes | yes |
| `datetime` is UTC (encode only) | yes | no |
| `uri` is valid RFC 3986 syntax | yes | configurable |
| `vector` field_length = 8 + dim * element_size | yes | yes |
| `vector` dim matches schema-declared dim | yes | yes |
| `vector` dtype matches schema-declared dtype | yes | yes |
| `enum` index in range [0, count-1] | yes | yes |
| `code_block` lang is non-empty | yes | yes |
| `code_block` field_length matches computed size | yes | yes |
| Required fields all present | yes | yes |
| No unknown field IDs | yes | yes |
| No duplicate field IDs | n/a | yes |
