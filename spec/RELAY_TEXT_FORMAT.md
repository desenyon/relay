# Relay Text Format Specification

**Version**: 1.0
**Status**: Authoritative
**Authors**: Naitik Gupta / Saerin Research
**Last Updated**: 2026-04-01

---

## 1. Overview

The Relay text format is the canonical human-readable and LLM-emittable encoding of Relay messages. It is stored in `.relay` files. The binary wire format (`.relayb`) and the text format are semantically identical — any valid Relay message can be round-tripped between the two representations without loss of information.

**Primary uses:**
- Authoring Relay messages by hand or by LLM
- Debug inspection and human review
- Version control (diff-friendly)
- Documentation and specification examples

The text format is not a streaming format. Binary is preferred on the wire. The text format is preferred for authoring, debugging, and storage in version control.

---

## 2. File Structure

A `.relay` file consists of three sections:

1. **Preamble**: Three mandatory header lines declaring the format version, schema, and message type.
2. **DELTA base** (DELTA messages only): An optional fourth header line declaring the base reference.
3. **Body**: Field declarations, one per logical field, with indentation for nested structures.

```
@relay 1.0
@schema <schema_name>:<4-byte-hash-hex>
@type <message_type>
[@base <ref_expression>]

<field_declarations>
```

---

## 3. Preamble

### 3.1 `@relay` Line

The first line of every `.relay` file must be:

```
@relay 1.0
```

- `@relay` is a literal keyword.
- `1.0` is the text format version (distinct from the binary wire format version).
- No trailing content is permitted on this line.
- Parsers must raise `ParseError` (E001) if this line is missing or malformed.

### 3.2 `@schema` Line

The second line declares the schema:

```
@schema <name>:<hash>
```

- `<name>` is the schema name as registered in the registry (alphanumeric, underscores, hyphens; no spaces).
- `<hash>` is the 4-byte schema hash expressed as 8 lowercase hexadecimal characters.
- The colon `:` is a mandatory separator.
- Example: `@schema agent_tool_call:a3f2bc01`

The schema must be resolvable in the local registry. If not found, parsers raise `SchemaNotFoundError` (E003).

### 3.3 `@type` Line

The third line declares the message type:

```
@type FULL
@type DELTA
@type REF_ONLY
@type SCHEMA_DEF
@type ERROR
```

Only these five values are valid. Any other value raises `ParseError` (E001).

### 3.4 `@base` Line (DELTA messages only)

For DELTA messages, the fourth line declares the base message reference:

```
@base $ref session:<uuid>.call[<index>]
```

- `$ref` is a literal keyword.
- `session:<uuid>` identifies the session by its UUID (standard hyphenated form).
- `.call[<index>]` is the 0-based call index of the base FULL message.
- Example: `@base $ref session:550e8400-e29b-41d4-a716-446655440000.call[2]`

### 3.5 Blank Line After Preamble

A single blank line must separate the preamble from the body. This blank line is mandatory and must not contain whitespace characters.

---

## 4. Field Declarations

### 4.1 Basic Syntax

Each field is declared on one line:

```
<name>: <type> <value>
```

- `<name>` is the field name as declared in the schema.
- `: ` (colon + space) is the separator.
- `<type>` is the type annotation (see Section 5).
- `<value>` is the inline value (see Section 6).

Example:

```
discount_rate: float64 0.08
```

### 4.2 Nested Objects

Object fields are declared by writing the field name and type on one line, then indenting child fields by exactly 2 spaces:

```
tool_call: object
  id: uuid "550e8400-e29b-41d4-a716-446655440000"
  name: string "calculate_npv"
  arguments: object
    discount_rate: float64 0.08
    periods: int32 5
```

Indentation is always a multiple of 2 spaces. Tabs are not permitted. The parser determines nesting depth by indentation level.

### 4.3 Array Fields

Array fields are declared as:

```
<name>: array[<element_type>]
  - <value>
  - <value>
  ...
```

Each element is prefixed with `- ` (hyphen + space) at the child indentation level. All elements must have the same type.

Example:

```
cash_flows: array[float64]
  - 100.0
  - 200.0
  - 300.0
  - 400.0
  - 500.0
```

For arrays of objects:

```
messages: array[object]
  - object
      role: enum<MessageRole> assistant
      content: string "Hello"
  - object
      role: enum<MessageRole> user
      content: string "World"
```

### 4.4 Field Ordering

Fields may appear in any order in the body. The encoder produces fields in ascending field ID order (canonical form). The decoder accepts fields in any order.

### 4.5 Omitting Optional Fields

Optional fields that are absent from the message are simply omitted from the body. Do not write `null` for absent optional fields unless the schema declares the field type as nullable.

---

## 5. Type Annotations

The type annotation after the colon identifies the encoding of the value that follows.

### 5.1 Primitive Type Annotations

| Annotation   | Binary Tag | Notes |
|--------------|------------|-------|
| `null`       | `0x01`     | No value follows; the whole field is `<name>: null` |
| `bool`       | `0x02`     | Value is `true` or `false` |
| `int8`       | `0x03`     | Integer literal |
| `int16`      | `0x04`     | Integer literal |
| `int32`      | `0x05`     | Integer literal |
| `int64`      | `0x06`     | Integer literal |
| `uint8`      | `0x07`     | Non-negative integer literal |
| `uint16`     | `0x08`     | Non-negative integer literal |
| `uint32`     | `0x09`     | Non-negative integer literal |
| `uint64`     | `0x0A`     | Non-negative integer literal |
| `float32`    | `0x0B`     | Floating-point literal |
| `float64`    | `0x0C`     | Floating-point literal |
| `string`     | `0x0D`     | Quoted string or triple-quoted block |
| `bytes`      | `0x0E`     | Hex-encoded: `0x<hexdigits>` |
| `array`      | `0x0F`     | Followed by `[element_type]`, then child elements |
| `object`     | `0x10`     | No inline value; children follow at next indent level |
| `uuid`       | `0x11`     | Quoted UUID string in standard hyphenated form |
| `datetime`   | `0x12`     | Quoted ISO 8601 UTC datetime string |
| `uri`        | `0x13`     | Quoted URI string |

### 5.2 Parameterized Type Annotations

| Annotation                  | Binary Tag | Notes |
|-----------------------------|------------|-------|
| `vector<float16, N>`        | `0x14`     | N-dimensional float16 array |
| `vector<float32, N>`        | `0x14`     | N-dimensional float32 array |
| `vector<float64, N>`        | `0x14`     | N-dimensional float64 array |
| `vector<int8, N>`           | `0x14`     | N-dimensional int8 array |
| `enum<EnumName>`            | `0x15`     | Enum value by symbolic name |
| `code_block<lang>`          | `0x16`     | Source code with language tag |
| `markdown_block`            | `0x17`     | Markdown text |
| `ref`                       | `0x18`     | Reference to prior session output |
| `delta_op`                  | `0x19`     | Delta operation (DELTA messages only) |

The value of `N` in `vector<dtype, N>` must match the schema-declared dimension. The encoder raises `TypeMismatchError` (E002) if the provided array length does not match `N`.

---

## 6. Value Syntax

### 6.1 Null

```
status: null
```

The keyword `null` is the value. No quotes.

### 6.2 Bool

```
streaming: bool true
is_error: bool false
```

Values are the unquoted keywords `true` and `false`.

### 6.3 Integer Types

```
status_code: int32 200
flags: uint8 3
offset: int64 -9223372036854775808
```

Integer literals: optional leading `-` for signed types, decimal digits only. No `0x` hex notation is permitted for integer field values (use `bytes` type for raw hex data).

### 6.4 Float Types

```
discount_rate: float64 0.08
temperature: float32 0.7
```

Floating-point literals: standard decimal notation or scientific notation (`1.5e-3`). The special values `inf`, `-inf`, and `nan` are written as unquoted literals.

### 6.5 String

**Inline (single line):**

```
name: string "calculate_npv"
```

Strings are enclosed in double quotes. Standard escape sequences apply: `\"`, `\\`, `\n`, `\r`, `\t`, `\uXXXX`, `\UXXXXXXXX`.

**Triple-quoted (multiline):**

```
content: string
  """
  This is the first line.
  This is the second line.
  """
```

Triple-quoted strings begin with `"""` on the line following the field declaration, indented 2 more spaces than the field. They end with `"""` on its own line at the same indentation. Leading/trailing newlines within the delimiters are stripped. Internal indentation relative to the opening `"""` is preserved.

### 6.6 Bytes

```
hash: bytes 0xdeadbeef01234567
```

Raw binary data is expressed as a `0x`-prefixed lowercase hexadecimal string. The number of hex digits must be even (each pair represents one byte). Spaces within the hex string are not permitted.

### 6.7 UUID

```
id: uuid "550e8400-e29b-41d4-a716-446655440000"
```

UUIDs are quoted strings in the standard RFC 4122 hyphenated form: 8-4-4-4-12 hexadecimal digits. Case-insensitive on input; canonical output is lowercase.

### 6.8 Datetime

```
created_at: datetime "2025-04-01T12:00:00Z"
```

Datetimes are quoted ISO 8601 strings. The `Z` suffix or explicit `+00:00` offset is required (UTC only). Microsecond precision is optional: `"2025-04-01T12:00:00.123456Z"`. The parser rejects non-UTC datetimes with `ValidationError` (E006).

### 6.9 URI

```
endpoint: uri "https://api.example.com/v1/tools"
```

URIs are quoted strings conforming to RFC 3986. The parser validates structure; it does not perform DNS resolution.

### 6.10 Vector

**Inline:**

```
embedding: vector<float64, 5> [1.0, 2.0, 3.0, 4.0, 5.0]
```

Values are enclosed in square brackets, comma-separated. No trailing comma. The element count must match the declared dimension `N`.

**Multiline:**

```
embedding: vector<float32, 4>
  [
    0.12345,
    0.67890,
    0.11111,
    0.22222,
  ]
```

Multiline vector notation uses the same bracket delimiters. A trailing comma after the last element is permitted in multiline form only.

### 6.11 Enum

```
role: enum<MessageRole> assistant
```

The enum value is written as its symbolic name (not its integer index). The name must match a value declared in the schema's enum definition. Case-sensitive.

### 6.12 Code Block

```
snippet: code_block<python>
  """
  def hello():
      return "world"
  """
```

The language tag follows the type annotation immediately (e.g., `code_block<python>`). The code content uses the same triple-quoted block syntax as multiline strings.

### 6.13 Markdown Block

```
content: markdown_block
  """
  # Result

  The calculation yielded **42.0**.

  See the [documentation](https://example.com) for details.
  """
```

The `markdown_block` type has no parameter. Content uses triple-quoted blocks.

### 6.14 Reference (`$ref`)

```
prior_result: ref $ref session:550e8400-e29b-41d4-a716-446655440000.call[3].output.embedding
```

References use the `$ref` prefix followed by the reference expression (see `RELAY_REFERENCE.md` for the full reference expression grammar).

---

## 7. Delta Message Body

In DELTA messages, the body contains delta operations instead of field declarations. Each operation is written as:

```
<opcode>  <field_path> <type> <value>
```

Or for DEL:

```
DEL  <field_path>
```

### 7.1 Delta Operations

| Opcode | Syntax | Description |
|--------|--------|-------------|
| `SET`  | `SET <path> <type> <value>` | Replace the field at `<path>` with `<value>` |
| `DEL`  | `DEL <path>` | Remove the field at `<path>` |
| `APP`  | `APP <path> <type> <value>` | Append `<value>` to the array at `<path>` |
| `SPL`  | `SPL <path> <start> <end> <type> <value>` | Splice array at `<path>`, replacing elements `[start, end)` with `<value>` |

The field path uses dot notation (`tool_call.arguments.discount_rate`) and bracket notation for arrays (`messages[2].content`).

### 7.2 Delta Example

```
@relay 1.0
@schema agent_tool_call:a3f2bc01
@type DELTA
@base $ref session:550e8400-e29b-41d4-a716-446655440000.call[2]

SET  tool_call.arguments.discount_rate float64 0.10
SET  tool_call.id uuid "661f9511-f3ac-52e5-b827-557766551111"
DEL  result.error
APP  result.output.tokens string "additional_token"
```

Operations are applied in the order they appear, top to bottom.

---

## 8. Comments

Lines beginning with `#` (after optional leading whitespace) are comments and are ignored by the parser.

```
# This is a comment
role: enum<MessageRole> assistant  # Inline comments are also permitted
```

Comments are not preserved in the binary encoding. A round-trip through binary and back to text will lose comments.

---

## 9. Complete Example

```
@relay 1.0
@schema agent_tool_call:a3f2bc01
@type FULL

role: enum<MessageRole> assistant
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
result: object
  output: float64 1234.56
  error: null
```

---

## 10. Encoding Rules (Text Encoder)

When producing `.relay` text from a Python/JS object, the encoder must:

1. Write the preamble lines in order (`@relay`, `@schema`, `@type`, `@base` if DELTA).
2. Write a single blank line.
3. Iterate fields in ascending field ID order (canonical order).
4. For each field, write `<name>: <type> <value>` using the value syntax defined in Section 6.
5. For object fields, recursively write child fields at the next indentation level.
6. For array fields, write the `array[<type>]` annotation and then each element prefixed with `- `.
7. Use 2-space indentation. No tabs.
8. Use triple-quoted blocks for multiline strings, markdown blocks, and code blocks that contain newlines.
9. Use inline bracket syntax for vectors with 8 or fewer elements; use multiline bracket syntax for longer vectors.

---

## 11. Parsing Rules (Text Decoder)

The text decoder must:

1. Reject files where the first non-blank line is not `@relay 1.0`.
2. Parse the `@schema` line and resolve the schema from the registry.
3. Parse the `@type` line and validate the message type.
4. For DELTA messages, parse the `@base` line and resolve the reference.
5. Skip blank lines and comment lines anywhere in the body.
6. Determine field nesting by counting leading space characters (must be a multiple of 2; otherwise raise `ParseError` E001).
7. Parse each field declaration and validate type and value against the schema.
8. Resolve enum symbolic names to their integer indices.
9. Validate UUIDs, datetimes, and URIs per their respective standards.
10. Raise `TypeMismatchError` (E002) for any type annotation that does not match the schema-declared type for that field.

---

## 12. Round-Trip Guarantees

The following round-trips are guaranteed to produce semantically equivalent results:

- **Binary → Text → Binary**: The final binary encoding equals the original binary encoding (canonical form).
- **Text → Binary → Text**: The final text encoding is semantically identical to the original (field values and types are preserved). Comments, non-canonical whitespace, and field ordering differences are not preserved.
- **Python dict → Binary → Python dict**: Value equality for all supported types.
- **Python dict → Text → Python dict**: Value equality for all supported types.

---

## 13. BNF Grammar

```bnf
relay-text      ::= preamble blank-line body
preamble        ::= relay-line schema-line type-line [base-line]
relay-line      ::= "@relay 1.0" CRLF
schema-line     ::= "@schema " schema-name ":" schema-hash CRLF
type-line       ::= "@type " message-type CRLF
base-line       ::= "@base " ref-expr CRLF
message-type    ::= "FULL" | "DELTA" | "REF_ONLY" | "SCHEMA_DEF" | "ERROR"
schema-name     ::= 1*(ALPHA / DIGIT / "_" / "-")
schema-hash     ::= 8HEXDIG
blank-line      ::= CRLF
body            ::= *(field-line / comment-line / blank-line)
comment-line    ::= *SP "#" *VCHAR CRLF
field-line      ::= indent field-name ": " type-annotation SP field-value CRLF
              /   indent field-name ": " "object" CRLF
              /   indent field-name ": " "null" CRLF
              /   indent field-name ": " "markdown_block" CRLF
              /   indent field-name ": " "code_block<" lang ">" CRLF
              /   indent field-name ": " "array[" elem-type "]" CRLF
indent          ::= *(2SP)
field-name      ::= 1*(ALPHA / DIGIT / "_")
type-annotation ::= primitive-type / parameterized-type
primitive-type  ::= "bool" / "int8" / "int16" / "int32" / "int64"
              /   "uint8" / "uint16" / "uint32" / "uint64"
              /   "float32" / "float64" / "string" / "bytes"
              /   "uuid" / "datetime" / "uri" / "markdown_block"
              /   "ref"
parameterized-type ::= "vector<" dtype "," SP 1*DIGIT ">"
              /   "enum<" enum-name ">"
              /   "code_block<" lang ">"
dtype           ::= "float16" / "float32" / "float64" / "int8"
triple-block    ::= (2SP) '"""' CRLF *triple-content (2SP) '"""' CRLF
triple-content  ::= *(SP) *VCHAR CRLF
ref-expr        ::= "$ref session:" UUID ".call[" 1*DIGIT "]" ["." field-path]
field-path      ::= field-name *("." field-name / "[" 1*DIGIT "]")
```

---

## Appendix A: Whitespace Normalization

The text decoder normalizes:
- `\r\n` and `\n` line endings are both accepted.
- Trailing whitespace on any line is ignored.
- The blank line separating preamble from body may contain only whitespace (it is treated as blank).

The text encoder always outputs `\n` line endings.
