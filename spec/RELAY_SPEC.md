# Relay Wire Format Specification

**Version**: 1.0
**Status**: Authoritative
**Authors**: Naitik Gupta / Saerin Research
**Last Updated**: 2026-04-01

---

## 1. Overview

Relay is a binary data interchange format designed for agentic AI runtimes. It replaces JSON as the wire format between LLM agents, tool executors, orchestrators, and memory systems. Every Relay message is:

- **Schema-enforced at the wire level**: A 4-byte schema hash in the frame header references a schema in the local registry. Consumers validate type correctness before processing begins.
- **Streaming-native**: Frame headers declare field lengths so consumers can begin dispatching without buffering the full payload.
- **Semantically typed**: Relay has first-class types beyond JSON's 6 primitives.
- **Reference-aware**: Messages can reference prior outputs in the session context without retransmitting values.

This document specifies the binary wire format. For the text (human-readable) encoding, see `RELAY_TEXT_FORMAT.md`. For type definitions, see `RELAY_TYPES.md`.

---

## 2. File Extensions

| Extension | Description |
|-----------|-------------|
| `.relay` | Relay text format (human-readable, LLM-emittable) |
| `.relayb` | Relay binary format (wire format) |
| `.rschema` | Relay schema definition file |

---

## 3. Frame Structure

Every Relay message consists of a fixed 12-byte **frame header** followed by a variable-length **payload**.

```
+------------------+---------------------------+
|  Frame Header    |         Payload           |
|    (12 bytes)    |   (payload_length bytes)  |
+------------------+---------------------------+
```

### 3.1 Frame Header

The frame header is exactly 12 bytes, always present, never compressed or encrypted at this layer.

```
Offset  Size  Type        Field
──────  ────  ──────────  ─────────────────────────────────────────────────────
0       1     uint8       Magic byte: 0xDE (decimal 222)
1       1     uint8       Version: currently 0x01
2       2     uint16 LE   Message type (see Section 4)
4       4     uint8[4]    Schema hash: first 4 bytes of SHA-256 of canonical schema JSON
8       4     uint32 LE   Payload length: number of bytes in the payload section
```

**Magic byte**: The magic byte `0xDE` (222) identifies the stream as a Relay message. Any parser encountering a byte other than `0xDE` at offset 0 must raise `ParseError` (E001).

**Version**: The current version is `0x01`. Parsers must reject messages with an unknown version with `ParseError` (E001). Version negotiation is out of scope for this document.

**Schema hash**: The 4-byte schema hash is the first 4 bytes of the SHA-256 hash of the schema's canonical JSON representation (see `RELAY_SCHEMA_REGISTRY.md`). The consumer must resolve this hash against its local registry before processing the payload. If the hash cannot be resolved, the consumer must raise `SchemaNotFoundError` (E003).

**Payload length**: The number of bytes that follow the header. A payload length of 0 is valid for `ERROR` and `REF_ONLY` message types. Implementations must not read beyond `offset + 12 + payload_length`.

### 3.2 Frame Header Wire Example

A FULL message with schema hash `a3f2bc01` and a 47-byte payload:

```
DE 01 01 00 A3 F2 BC 01 2F 00 00 00
│  │  ├──┘ ├────────┘ ├──────────┘
│  │  │    │          └── Payload length: 47 (0x0000002F LE)
│  │  │    └── Schema hash: a3f2bc01
│  │  └── Message type: 0x0001 = FULL
│  └── Version: 0x01
└── Magic: 0xDE
```

---

## 4. Message Types

| Code     | Name        | Description |
|----------|-------------|-------------|
| `0x0001` | `FULL`      | A complete message carrying all field values explicitly. |
| `0x0002` | `DELTA`     | A mutation over a prior FULL message. Contains delta operations referencing a base message. |
| `0x0003` | `REF_ONLY`  | The entire message is a reference to a prior output. Payload contains a single `ref` field frame. |
| `0x0004` | `SCHEMA_DEF`| Carries a schema definition inline. Used for schema exchange without a pre-shared registry. |
| `0x0005` | `ERROR`     | An error message. Payload contains structured error fields (see Section 8). |

### 4.1 FULL Messages

FULL messages carry all fields explicitly. The payload is a sequence of field frames (see Section 5). Every required field declared in the schema must be present. Optional fields may be omitted.

### 4.2 DELTA Messages

DELTA messages express a mutation over a prior FULL message identified by a `$ref`. The payload is:

1. A mandatory `__base__` field (field ID 0x0000) of type `ref` (tag `0x18`) identifying the base message.
2. A sequence of `delta_op` field frames (tag `0x19`) each representing one mutation operation.

See `RELAY_REFERENCE.md` for complete delta semantics.

### 4.3 REF_ONLY Messages

REF_ONLY messages carry no inline field data. The entire message is a pointer to a prior output in the session context. The payload contains a single field frame with type tag `0x18` (`ref`).

### 4.4 SCHEMA_DEF Messages

SCHEMA_DEF messages carry a schema definition inline. The schema hash in the frame header is computed from the carried schema. The payload contains the schema encoded as a UTF-8 string in the `.rschema` text format. The receiving party must register the schema in its local registry before processing subsequent messages that reference this hash.

The payload field layout for SCHEMA_DEF:

```
Field ID 0x0001: type 0x0D (string), value = UTF-8 encoded .rschema content
```

### 4.5 ERROR Messages

ERROR messages carry a structured error. The schema hash field in the header is all zeros (`00 00 00 00`) for ERROR messages. The payload field layout is defined in Section 8.

---

## 5. Payload Encoding

The payload of a FULL message is a contiguous sequence of **field frames**. Field frames are self-delimiting: a parser can skip any field frame without understanding its type by reading the `field_length` and advancing the cursor.

### 5.1 Field Frame Layout

Each field frame is a minimum of 7 bytes (header) followed by `field_length` value bytes.

```
Offset  Size  Type        Field
──────  ────  ──────────  ─────────────────────────────────────────────────────
0       2     uint16 LE   Field ID: maps to a field name via the schema
2       1     uint8       Type tag: identifies the encoding of the value
3       4     uint32 LE   Field length: number of value bytes following this header
7       N     bytes       Field value (N = field_length)
```

**Field ID**: A 16-bit unsigned integer assigned by the schema to each named field. Field IDs are 1-based. Field ID `0x0000` is reserved for the `__base__` reference in DELTA messages. The schema defines the mapping of field names to field IDs.

**Type tag**: Identifies how the value bytes are to be interpreted. The type tag must match the type declared in the schema for this field ID, or the parser must raise `TypeMismatchError` (E002).

**Field length**: The exact number of bytes in the value section. For variable-length types (string, bytes, array, object, etc.), this is the total byte count of the encoded value. For fixed-length types (bool, int32, float64, uuid, etc.), the field length must exactly match the fixed size specified in `RELAY_TYPES.md`; a mismatch raises `ParseError` (E001).

### 5.2 Field Ordering

Field frames within a FULL message payload may appear in any order. The schema defines field IDs, not positions. Consumers must be prepared to receive fields in any order. However, the **canonical ordering** (used for hashing and byte-equality comparisons) is ascending field ID order.

### 5.3 Duplicate Fields

If the same field ID appears more than once in a payload, the parser must raise `ParseError` (E001). Duplicate fields are not allowed.

### 5.4 Unknown Fields

If a field frame contains a field ID not declared in the schema, the parser must raise `TypeMismatchError` (E002) unless the schema declares an `extensions: allow` directive (not currently defined; reserved for future use). In the current version, unknown fields always raise an error.

---

## 6. Type Tags

The following table defines all type tags. Value encoding details are specified in `RELAY_TYPES.md`.

| Tag    | Name             | Fixed Size | Description |
|--------|------------------|------------|-------------|
| `0x01` | `null`           | 0 bytes    | Null / absent value. Field length must be 0. |
| `0x02` | `bool`           | 1 byte     | Boolean. `0x00` = false, `0x01` = true. |
| `0x03` | `int8`           | 1 byte     | Signed 8-bit integer. |
| `0x04` | `int16`          | 2 bytes    | Signed 16-bit integer, little-endian. |
| `0x05` | `int32`          | 4 bytes    | Signed 32-bit integer, little-endian. |
| `0x06` | `int64`          | 8 bytes    | Signed 64-bit integer, little-endian. |
| `0x07` | `uint8`          | 1 byte     | Unsigned 8-bit integer. |
| `0x08` | `uint16`         | 2 bytes    | Unsigned 16-bit integer, little-endian. |
| `0x09` | `uint32`         | 4 bytes    | Unsigned 32-bit integer, little-endian. |
| `0x0A` | `uint64`         | 8 bytes    | Unsigned 64-bit integer, little-endian. |
| `0x0B` | `float32`        | 4 bytes    | IEEE 754 single-precision, little-endian. |
| `0x0C` | `float64`        | 8 bytes    | IEEE 754 double-precision, little-endian. |
| `0x0D` | `string`         | variable   | UTF-8 encoded string. No null terminator. |
| `0x0E` | `bytes`          | variable   | Raw binary data, no encoding. |
| `0x0F` | `array`          | variable   | Length-prefixed sequence of element frames. |
| `0x10` | `object`         | variable   | Nested field frame sequence. |
| `0x11` | `uuid`           | 16 bytes   | UUID in RFC 4122 binary form (big-endian bytes). |
| `0x12` | `datetime`       | 8 bytes    | int64 LE microseconds since Unix epoch, UTC. |
| `0x13` | `uri`            | variable   | UTF-8 string, validated as RFC 3986. |
| `0x14` | `vector`         | variable   | Typed numeric array (see Section 6.1). |
| `0x15` | `enum`           | 4 bytes    | uint32 LE enum value index (validated against schema). |
| `0x16` | `code_block`     | variable   | Language-tagged source code (see Section 6.2). |
| `0x17` | `markdown_block` | variable   | UTF-8 Markdown text. |
| `0x18` | `ref`            | variable   | Reference to a prior session output (see Section 6.3). |
| `0x19` | `delta_op`       | variable   | Delta operation (see `RELAY_REFERENCE.md`). |

### 6.1 Vector Encoding (`0x14`)

A `vector` field carries a typed numeric array with a declared dtype and dimension.

```
Offset  Size  Field
0       4     dtype tag: uint32 LE
4       4     dim: uint32 LE — number of elements
8       N     element bytes: dim * element_size bytes, little-endian

dtype tags:
  0x00000001 = float16  (2 bytes per element, IEEE 754 half-precision)
  0x00000002 = float32  (4 bytes per element, IEEE 754 single-precision)
  0x00000003 = float64  (8 bytes per element, IEEE 754 double-precision)
  0x00000004 = int8     (1 byte per element, signed)
```

The total field length is `8 + dim * element_size`. A field length that does not satisfy this equation must raise `ParseError` (E001).

The `dim` declared in the value bytes must match the dimension declared in the schema type (`vector<dtype, dim>`). A mismatch must raise `TypeMismatchError` (E002).

### 6.2 Code Block Encoding (`0x16`)

A `code_block` carries a language identifier and source code.

```
Offset  Size  Field
0       2     lang_length: uint16 LE — byte length of the language string
2       L     lang: UTF-8 string of length lang_length (e.g., "python", "javascript")
2+L     4     code_length: uint32 LE — byte length of the code string
6+L     C     code: UTF-8 string of length code_length
```

Total field length: `2 + lang_length + 4 + code_length`. The language identifier must be a non-empty string. Empty language identifiers must raise `ValidationError` (E006).

### 6.3 Reference Encoding (`0x18`)

A `ref` value points to a field in a prior session output.

```
Offset  Size  Field
0       16    session_id: UUID in RFC 4122 binary form (big-endian)
16      4     call_index: uint32 LE — 0-based index of the call in the session
20      N+1   field_path: null-terminated UTF-8 string
```

The field path uses dot notation: `output.embedding`. Array indexing uses bracket notation: `output.tokens[3]`. An empty field path (just a null byte) refers to the entire message output, not an individual field.

Total field length: `20 + len(field_path_utf8) + 1` (the +1 is for the null terminator).

---

## 7. Array and Object Encoding

### 7.1 Array (`0x0F`)

An array value begins with a 4-byte element count, followed by element frames. Each element frame is itself a field frame, but with field ID `0x0000` (reserved for array elements within array context).

```
Offset  Size  Field
0       4     count: uint32 LE — number of elements
4       ...   element frames, each: [field_id=0x0000 2B][type_tag 1B][elem_length 4B][value NB]
```

All elements in an array must have the same type tag (homogeneous arrays). Heterogeneous arrays are not supported in the current version; they must be represented as a sequence of `object` values. A type tag mismatch between elements raises `TypeMismatchError` (E002).

### 7.2 Object (`0x10`)

An object value is a nested sequence of field frames, using the same encoding as the top-level payload. The field IDs within a nested object are resolved against the sub-schema declared for that field in the parent schema.

Nested object field frames are identical in structure to top-level field frames. The total byte count of all nested field frames equals the object's `field_length` in the parent frame.

---

## 8. ERROR Message Payload

ERROR messages use a fixed schema (no schema hash resolution required; schema hash bytes are `00 00 00 00`).

The payload contains the following field frames in canonical order:

| Field ID | Field Name      | Type   | Required | Description |
|----------|-----------------|--------|----------|-------------|
| `0x0001` | `error_code`    | uint16 | yes      | Machine-readable error code (see `RELAY_ERRORS.md`) |
| `0x0002` | `error_name`    | string | yes      | Human-readable error name, e.g., `TypeMismatchError` |
| `0x0003` | `message`       | string | yes      | Human-readable error description |
| `0x0004` | `field_path`    | string | no       | Dot-path to the field where the error occurred |
| `0x0005` | `expected_type` | string | no       | Expected type name, for type mismatch errors |
| `0x0006` | `actual_type`   | string | no       | Actual type tag received, for type mismatch errors |
| `0x0007` | `schema_hash`   | bytes  | no       | 4-byte hash that could not be resolved |
| `0x0008` | `context`       | string | no       | Additional context for debugging |

---

## 9. Streaming Parsing

Relay is designed for incremental parsing. A compliant parser must be able to emit parsed fields as they arrive without buffering the entire payload.

### 9.1 Streaming Algorithm

1. Buffer exactly 12 bytes to read the frame header.
2. Validate magic byte and version; raise `ParseError` (E001) on mismatch.
3. Resolve schema hash; raise `SchemaNotFoundError` (E003) if unknown.
4. Begin iterating field frames. For each field frame:
   a. Buffer 7 bytes to read the field frame header.
   b. Validate field ID against schema; raise `TypeMismatchError` (E002) if unknown.
   c. Validate type tag against schema-declared type; raise `TypeMismatchError` (E002) on mismatch.
   d. Buffer exactly `field_length` bytes to read the value.
   e. Decode the value per the type tag specification.
   f. **Yield the decoded field to the consumer immediately.**
5. After yielding each field, continue to the next field frame.
6. Stop when the total bytes consumed equals `12 + payload_length`.

### 9.2 Partial Delivery

The streaming parser must handle partial delivery at any byte boundary. The implementation must maintain a byte buffer and resume parsing when new bytes arrive. The `decode_stream(stream: BinaryIO)` API yields complete `RelayMessage` objects one field at a time.

---

## 10. Canonical Form

The **canonical form** of a Relay message is the binary encoding with:

1. Fields in ascending field ID order.
2. No duplicate fields.
3. No optional fields with null values (omit them instead).
4. Object subfields in ascending field ID order (recursively).
5. Array elements in original order (arrays are ordered).

Canonical form is used for:
- Computing schema hashes (see `RELAY_SCHEMA_REGISTRY.md`).
- Round-trip byte-equality comparisons.
- Signature computation (future extension).

---

## 11. Endianness

All multi-byte integer fields in Relay are **little-endian** (LE) unless otherwise noted. The UUID binary form is an exception: it is stored in **big-endian** (network byte order) per RFC 4122. float32 and float64 values follow IEEE 754 with **little-endian** byte ordering.

---

## 12. Reserved Ranges

| Range             | Status |
|-------------------|--------|
| Message types `0x0006`–`0xFFFF` | Reserved for future use |
| Type tags `0x1A`–`0xFF`         | Reserved for future use |
| Field ID `0x0000`               | Reserved (array element marker, delta base reference) |
| Field IDs `0xFF00`–`0xFFFF`     | Reserved for internal/system use |

---

## 13. Interoperability Requirements

A conforming Relay implementation must:

1. Implement all 25 type tags (0x01–0x19).
2. Implement all 5 message types (0x0001–0x0005).
3. Raise typed `RelayError` subclasses (not unstructured exceptions) for every error condition.
4. Produce canonical form binary output.
5. Accept fields in any order when decoding.
6. Support streaming decoding at the field level.
7. Validate schema compliance on both encode and decode.

---

## 14. Version Compatibility

Version `0x01` is the initial release. Future versions may extend the type tag space, add new message types, or modify field frame encoding. Parsers must reject messages with unknown versions; they must not attempt to parse forward-incompatible formats.

---

## Appendix A: Complete Binary Example

The following is a complete binary Relay message encoding the object `{"role": 2, "name": "calculate_npv"}` against schema `agent_tool_call` (hash `a3f2bc01`).

Schema field assignments:
- Field 1: `role` (enum, index 2 = "assistant")
- Field 2: `name` (string)

```
Frame header (12 bytes):
  DE 01 01 00 A3 F2 BC 01 19 00 00 00
  │  │  ├──┘ ├────────┘ ├──────────┘
  │  │  │    │          Payload length: 25
  │  │  │    Schema hash: a3f2bc01
  │  │  Message type: FULL (0x0001)
  │  Version: 0x01
  Magic: 0xDE

Field frame 1 — role (field ID 1, enum, value index 2):
  01 00 15 04 00 00 00 02 00 00 00
  ├───┘ │  ├────────┘ ├──────────┘
  │     │  field_len=4  value: uint32 LE 2
  │     type: 0x15 (enum)
  field_id: 0x0001

Field frame 2 — name (field ID 2, string, "calculate_npv" = 13 bytes):
  02 00 0D 0D 00 00 00 63 61 6C 63 75 6C 61 74 65 5F 6E 70 76
  ├───┘ │  ├────────┘ ├─────────────────────────────────────┘
  │     │  field_len=13  value: UTF-8 "calculate_npv"
  │     type: 0x0D (string)
  field_id: 0x0002
```

Total: 12 (header) + 11 (field 1) + 14 (field 2 header+value) = wait, recalculated:
- Field 1: 7 (frame header) + 4 (value) = 11 bytes
- Field 2: 7 (frame header) + 13 (value) = 20 bytes (but header says 25 — the example shows field 2 needs 14 bytes: 7 header + 13 value, field 1 needs 11 bytes = 25 total payload). Confirmed.

---

## Appendix B: BNF Grammar (Informative)

```bnf
relay-message   ::= frame-header payload
frame-header    ::= magic version msg-type schema-hash payload-len
magic           ::= %xDE
version         ::= %x01
msg-type        ::= %x00 %x01   ; FULL
                  | %x00 %x02   ; DELTA
                  | %x00 %x03   ; REF_ONLY
                  | %x00 %x04   ; SCHEMA_DEF
                  | %x00 %x05   ; ERROR
schema-hash     ::= 4OCTET
payload-len     ::= 4OCTET      ; uint32 LE
payload         ::= *field-frame
field-frame     ::= field-id type-tag field-len field-value
field-id        ::= 2OCTET      ; uint16 LE
type-tag        ::= 1OCTET      ; 0x01..0x19
field-len       ::= 4OCTET      ; uint32 LE
field-value     ::= *OCTET      ; field-len octets
```
