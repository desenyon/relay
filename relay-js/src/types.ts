/**
 * All Relay primitive types, message structures, and supporting interfaces.
 *
 * This module defines the complete type system used throughout the Relay runtime.
 * Every value that flows through encoding, decoding, schema validation, delta
 * application, and reference resolution is represented by one of the types here.
 *
 * @module types
 */

// ---------------------------------------------------------------------------
// Wire-format constants
// ---------------------------------------------------------------------------

/** Frame magic byte (0xDE / 222 decimal). */
export const MAGIC = 0xde as const;

/** Current wire-format version byte. */
export const VERSION = 0x01 as const;

/** Fixed size of the 12-byte frame header in bytes. */
export const FRAME_HEADER_SIZE = 12 as const;

/** Fixed size of the 7-byte per-field header in bytes. */
export const FIELD_HEADER_SIZE = 7 as const;

// ---------------------------------------------------------------------------
// Enumerations
// ---------------------------------------------------------------------------

/**
 * Wire-level type tag byte values used in Relay field frames.
 *
 * Each value corresponds to the `Type tag` byte in the field frame header
 * as defined in the Relay wire-format specification.
 *
 * @example
 * ```ts
 * console.log(TypeTag.STRING); // 13
 * console.log(TypeTag.UUID.toString(16)); // "11"
 * ```
 */
export enum TypeTag {
  NULL           = 0x01,
  BOOL           = 0x02,
  INT8           = 0x03,
  INT16          = 0x04,
  INT32          = 0x05,
  INT64          = 0x06,
  UINT8          = 0x07,
  UINT16         = 0x08,
  UINT32         = 0x09,
  UINT64         = 0x0a,
  FLOAT32        = 0x0b,
  FLOAT64        = 0x0c,
  STRING         = 0x0d,
  BYTES          = 0x0e,
  ARRAY          = 0x0f,
  OBJECT         = 0x10,
  UUID           = 0x11,
  DATETIME       = 0x12,
  URI            = 0x13,
  VECTOR         = 0x14,
  ENUM           = 0x15,
  CODE_BLOCK     = 0x16,
  MARKDOWN_BLOCK = 0x17,
  REF            = 0x18,
  DELTA_OP       = 0x19,
}

/**
 * Relay message-type codes stored in bytes 2-3 of the frame header.
 *
 * @example
 * ```ts
 * console.log(MessageType.FULL); // 1
 * ```
 */
export enum MessageType {
  FULL       = 0x0001,
  DELTA      = 0x0002,
  REF_ONLY   = 0x0003,
  SCHEMA_DEF = 0x0004,
  ERROR      = 0x0005,
}

/**
 * Sub-type tag for the `vector` semantic type.
 *
 * Stored in the first 4 bytes of a vector field value.
 *
 * @example
 * ```ts
 * console.log(VectorDtype.FLOAT32); // 2
 * ```
 */
export enum VectorDtype {
  FLOAT16 = 0x01,
  FLOAT32 = 0x02,
  FLOAT64 = 0x03,
  INT8    = 0x04,
}

/**
 * Operation types for Relay DELTA messages.
 *
 * @example
 * ```ts
 * console.log(DeltaOpType.SET); // "SET"
 * ```
 */
export enum DeltaOpType {
  SET = 'SET',
  DEL = 'DEL',
  APP = 'APP',
  SPL = 'SPL',
}

// ---------------------------------------------------------------------------
// Semantic value interfaces
// ---------------------------------------------------------------------------

/**
 * A typed, fixed-dimension numeric array (Relay `vector` semantic type).
 *
 * @example
 * ```ts
 * const v: VectorValue = {
 *   dtype: VectorDtype.FLOAT32,
 *   dim: 3,
 *   data: new Float32Array([1.0, 2.0, 3.0]),
 * };
 * ```
 */
export interface VectorValue {
  /** Element numeric type. */
  dtype: VectorDtype;
  /** Number of elements; must equal `data.length`. */
  dim: number;
  /**
   * The numeric payload as a typed array.
   * Float16 is represented as Float32Array (JS has no Float16Array).
   */
  data: Float32Array | Float64Array | Int8Array;
}

/**
 * A fenced code block with an explicit language tag.
 *
 * @example
 * ```ts
 * const cb: CodeBlock = { lang: "python", code: "print('hello')" };
 * ```
 */
export interface CodeBlock {
  /** Language identifier, e.g. "python", "json". */
  lang: string;
  /** Source code content. */
  code: string;
}

/**
 * A Markdown-formatted text block.
 *
 * @example
 * ```ts
 * const mb: MarkdownBlock = { content: "# Hello\nWorld" };
 * ```
 */
export interface MarkdownBlock {
  /** Raw Markdown text. */
  content: string;
}

/**
 * A resolved enum value carrying both the symbolic name and its numeric index.
 *
 * @example
 * ```ts
 * const ev: EnumValue = { name: "assistant", index: 2 };
 * ```
 */
export interface EnumValue {
  /** Symbolic enum value name, e.g. "assistant". */
  name: string;
  /** Zero-based position in the enum definition order. */
  index: number;
}

// ---------------------------------------------------------------------------
// Reference type
// ---------------------------------------------------------------------------

/**
 * A `$ref` expression pointing to a field in a prior session output.
 *
 * @example
 * ```ts
 * const ref: RelayRef = {
 *   sessionId: "550e8400-e29b-41d4-a716-446655440000",
 *   callIndex: 2,
 *   fieldPath: "output.embedding",
 * };
 * ```
 */
export interface RelayRef {
  /** The session UUID that produced the referenced output. */
  sessionId: string;
  /** Zero-based index of the call within the session. */
  callIndex: number;
  /** Dot-separated path into the message, e.g. "tool_call.arguments.rate". */
  fieldPath: string;
}

// ---------------------------------------------------------------------------
// Delta operation
// ---------------------------------------------------------------------------

/**
 * A single mutation operation within a Relay DELTA message.
 *
 * @example
 * ```ts
 * const op: DeltaOp = {
 *   opType: DeltaOpType.SET,
 *   fieldPath: "tool_call.arguments.rate",
 *   typeTag: TypeTag.FLOAT64,
 *   value: 0.10,
 * };
 * ```
 */
export interface DeltaOp {
  /** The kind of operation: SET, DEL, APP, or SPL. */
  opType: DeltaOpType;
  /** Dot-separated path to the target field. */
  fieldPath: string;
  /**
   * The Relay type tag of `value`. Required for SET, APP, and SPL;
   * `undefined` for DEL.
   */
  typeTag?: TypeTag;
  /** The new value to write. `undefined` for DEL. */
  value?: FieldValue;
  /** Inclusive start index for SPL operations. */
  spliceStart?: number;
  /** Exclusive end index for SPL operations. */
  spliceEnd?: number;
}

// ---------------------------------------------------------------------------
// Core message structures
// ---------------------------------------------------------------------------

/**
 * Union type of all possible decoded field values.
 * Excludes `any` — typed strictly.
 */
export type FieldValue =
  | null
  | boolean
  | number
  | bigint
  | string
  | Uint8Array
  | VectorValue
  | CodeBlock
  | MarkdownBlock
  | EnumValue
  | RelayRef
  | DeltaOp
  | RelayField[]
  | FieldValue[];

/**
 * A single decoded field within a Relay message payload.
 *
 * @example
 * ```ts
 * const f: RelayField = {
 *   fieldId: 1,
 *   name: "role",
 *   typeTag: TypeTag.ENUM,
 *   value: { name: "assistant", index: 2 },
 * };
 * ```
 */
export interface RelayField {
  /** Numeric field identifier (uint16) that maps to a name via the schema. */
  fieldId: number;
  /** Human-readable field name resolved from the schema. */
  name: string;
  /** The wire type tag for this field. */
  typeTag: TypeTag;
  /**
   * The decoded value. For nested objects this is an array of `RelayField`;
   * for arrays it is an array of values; for semantic types it is the
   * appropriate interface (e.g. `VectorValue`, `CodeBlock`).
   */
  value: FieldValue;
}

/**
 * A fully decoded Relay message.
 *
 * @example
 * ```ts
 * const msg: RelayMessage = {
 *   messageType: MessageType.FULL,
 *   schemaHash: new Uint8Array([0xa3, 0xf2, 0xbc, 0x01]),
 *   fields: [],
 * };
 * ```
 */
export interface RelayMessage {
  /** FULL, DELTA, REF_ONLY, SCHEMA_DEF, or ERROR. */
  messageType: MessageType;
  /** The 4-byte schema hash extracted from the frame header. */
  schemaHash: Uint8Array;
  /** Ordered sequence of decoded fields. */
  fields: RelayField[];
  /** The original binary frame bytes, preserved for round-trip fidelity. */
  rawBytes?: Uint8Array;
}

// ---------------------------------------------------------------------------
// Helper utilities
// ---------------------------------------------------------------------------

/**
 * Return the first field in `msg` whose name matches `name`, or `undefined`.
 *
 * @param msg - The decoded Relay message.
 * @param name - The field name to look up.
 * @returns The matching field or `undefined`.
 *
 * @example
 * ```ts
 * const field = getField(msg, "role");
 * ```
 */
export function getField(msg: RelayMessage, name: string): RelayField | undefined {
  return msg.fields.find((f) => f.name === name);
}

/**
 * Convert a Relay message to a plain nested object for inspection.
 *
 * @param msg - The decoded Relay message.
 * @returns A JSON-serializable (after BigInt conversion) representation.
 *
 * @example
 * ```ts
 * const obj = messageToDict(msg);
 * console.log(obj.messageType); // "FULL"
 * ```
 */
export function messageToDict(msg: RelayMessage): Record<string, unknown> {
  return {
    messageType: MessageType[msg.messageType],
    schemaHash: Array.from(msg.schemaHash)
      .map((b) => b.toString(16).padStart(2, '0'))
      .join(''),
    fields: msg.fields.map(fieldToDict),
  };
}

/**
 * Convert a `RelayField` to a plain object recursively.
 *
 * @param f - The field to convert.
 * @returns A plain representation suitable for display.
 */
export function fieldToDict(f: RelayField): Record<string, unknown> {
  let value: unknown = f.value;

  switch (f.typeTag) {
    case TypeTag.OBJECT:
      if (Array.isArray(f.value)) {
        value = (f.value as RelayField[]).map(fieldToDict);
      }
      break;
    case TypeTag.ARRAY:
      if (Array.isArray(f.value)) {
        value = (f.value as FieldValue[]).map((item) =>
          item !== null && typeof item === 'object' && 'fieldId' in item
            ? fieldToDict(item as unknown as RelayField)
            : item
        );
      }
      break;
    case TypeTag.VECTOR: {
      const v = f.value as VectorValue;
      value = {
        dtype: VectorDtype[v.dtype],
        dim: v.dim,
        data: Array.from(v.data),
      };
      break;
    }
    case TypeTag.ENUM: {
      const ev = f.value as EnumValue;
      value = { name: ev.name, index: ev.index };
      break;
    }
    case TypeTag.CODE_BLOCK: {
      const cb = f.value as CodeBlock;
      value = { lang: cb.lang, code: cb.code };
      break;
    }
    case TypeTag.MARKDOWN_BLOCK: {
      const mb = f.value as MarkdownBlock;
      value = { content: mb.content };
      break;
    }
    case TypeTag.REF: {
      const ref = f.value as RelayRef;
      value = {
        sessionId: ref.sessionId,
        callIndex: ref.callIndex,
        fieldPath: ref.fieldPath,
      };
      break;
    }
    case TypeTag.BYTES:
      if (f.value instanceof Uint8Array) {
        value = Array.from(f.value)
          .map((b) => b.toString(16).padStart(2, '0'))
          .join('');
      }
      break;
    default:
      break;
  }

  return {
    fieldId: f.fieldId,
    name: f.name,
    type: TypeTag[f.typeTag],
    value,
  };
}

/** Bytes-per-element for each VectorDtype. */
export const VECTOR_DTYPE_ITEMSIZE: Record<VectorDtype, number> = {
  [VectorDtype.FLOAT16]: 2,
  [VectorDtype.FLOAT32]: 4,
  [VectorDtype.FLOAT64]: 8,
  [VectorDtype.INT8]:    1,
};
