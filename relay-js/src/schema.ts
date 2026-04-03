/**
 * Schema definition, hashing, and registry types for the Relay runtime.
 *
 * Schemas are the contract between Relay producers and consumers. Every Relay
 * message carries a 4-byte schema hash in its frame header that references a
 * schema in the local registry. Consumers validate type correctness before
 * processing begins, not after.
 *
 * @module schema
 */

import { SchemaNotFoundError } from './errors.js';

// ---------------------------------------------------------------------------
// Schema field definition
// ---------------------------------------------------------------------------

/**
 * A single field definition within a Relay schema.
 *
 * @example
 * ```ts
 * const field: SchemaField = {
 *   name: "role",
 *   type: "enum",
 *   enumName: "MessageRole",
 *   required: true,
 * };
 * ```
 */
export interface SchemaField {
  /** Field name as used in wire encoding and text format. */
  name: string;
  /**
   * Relay type name. One of: null, bool, int8, int16, int32, int64,
   * uint8, uint16, uint32, uint64, float32, float64, string, bytes,
   * array, object, uuid, datetime, uri, vector, enum, code_block,
   * markdown_block, ref, any.
   */
  type: string;
  /** For `enum` fields: the enum definition name. */
  enumName?: string;
  /** For `vector` fields: the element dtype (float16, float32, float64, int8). */
  vectorDtype?: string;
  /** For `vector` fields: the fixed dimension count. */
  vectorDim?: number;
  /** Whether this field must be present in every message. */
  required: boolean;
  /** For `object` fields: nested field definitions. */
  fields?: SchemaField[];
  /** Numeric field ID assigned during schema registration (0-indexed by position). */
  fieldId?: number;
}

/**
 * An enum type definition within a schema.
 *
 * @example
 * ```ts
 * const enumDef: EnumDefinition = {
 *   name: "MessageRole",
 *   values: ["system", "user", "assistant", "tool"],
 * };
 * ```
 */
export interface EnumDefinition {
  /** Enum type name. */
  name: string;
  /** Ordered list of symbolic value names. Index in this array = wire index. */
  values: string[];
}

// ---------------------------------------------------------------------------
// RelaySchema class
// ---------------------------------------------------------------------------

/**
 * A Relay schema definition.
 *
 * Schemas are immutable once constructed. The `hash()` method returns a stable
 * hex string derived from the canonical JSON representation of the schema.
 * Use `RelaySchema.fromDict()` for the standard construction path.
 *
 * @example
 * ```ts
 * const schema = RelaySchema.fromDict({
 *   name: "agent_tool_call",
 *   version: 1,
 *   fields: [
 *     { name: "role", type: "enum", enumName: "MessageRole", required: true },
 *   ],
 *   enums: [
 *     { name: "MessageRole", values: ["system", "user", "assistant", "tool"] },
 *   ],
 * });
 * const hashHex = await schema.hash();
 * ```
 */
export class RelaySchema {
  /** Schema name as registered in the registry. */
  readonly name: string;
  /** Schema version integer. */
  readonly version: number;
  /** Top-level field definitions (assigned fieldIds starting at 0). */
  readonly fields: SchemaField[];
  /** Enum type definitions available within this schema. */
  readonly enums: EnumDefinition[];

  private _hashCache: string | undefined;
  private _hashBytesCache: Uint8Array | undefined;

  constructor(
    name: string,
    version: number,
    fields: SchemaField[],
    enums: EnumDefinition[]
  ) {
    this.name = name;
    this.version = version;
    this.fields = this._assignFieldIds(fields, 0);
    this.enums = enums;
  }

  /**
   * Construct a `RelaySchema` from a plain object.
   *
   * @param d - Schema definition object.
   * @returns A new `RelaySchema` instance.
   *
   * @throws {SchemaNotFoundError} If required schema properties are missing.
   *
   * @example
   * ```ts
   * const schema = RelaySchema.fromDict({
   *   name: "my_schema",
   *   version: 1,
   *   fields: [{ name: "id", type: "uuid", required: true }],
   *   enums: [],
   * });
   * ```
   */
  static fromDict(d: Record<string, unknown>): RelaySchema {
    if (typeof d.name !== 'string') {
      throw new SchemaNotFoundError('Schema dict must have a string "name" field');
    }
    if (typeof d.version !== 'number') {
      throw new SchemaNotFoundError('Schema dict must have a numeric "version" field');
    }
    const fields = (d.fields as SchemaField[] | undefined) ?? [];
    const enums = (d.enums as EnumDefinition[] | undefined) ?? [];
    return new RelaySchema(d.name, d.version, fields, enums);
  }

  // ---------------------------------------------------------------------------
  // Hashing
  // ---------------------------------------------------------------------------

  /**
   * Return the first 4 bytes of SHA-256 of the canonical schema JSON as a hex string.
   *
   * This is an async method because `crypto.subtle.digest` is async in browsers.
   * The result is cached after the first call.
   *
   * @returns Promise resolving to an 8-character hex string (4 bytes).
   *
   * @example
   * ```ts
   * const h = await schema.hash();
   * console.log(h); // e.g. "a3f2bc01"
   * ```
   */
  async hash(): Promise<string> {
    if (this._hashCache !== undefined) return this._hashCache;
    const bytes = await this.hashBytes();
    this._hashCache = Array.from(bytes)
      .map((b) => b.toString(16).padStart(2, '0'))
      .join('');
    return this._hashCache;
  }

  /**
   * Return the first 4 bytes of SHA-256 of the canonical schema JSON.
   *
   * @returns Promise resolving to a 4-byte `Uint8Array`.
   *
   * @example
   * ```ts
   * const bytes = await schema.hashBytes();
   * console.log(bytes.length); // 4
   * ```
   */
  async hashBytes(): Promise<Uint8Array> {
    if (this._hashBytesCache !== undefined) return this._hashBytesCache;
    const canonical = this.toCanonicalJson();
    const encoder = new TextEncoder();
    const data = encoder.encode(canonical);
    const hashBuffer = await crypto.subtle.digest('SHA-256', data);
    this._hashBytesCache = new Uint8Array(hashBuffer.slice(0, 4));
    return this._hashBytesCache;
  }

  // ---------------------------------------------------------------------------
  // Field lookup
  // ---------------------------------------------------------------------------

  /**
   * Return the schema field definition for `name`, or `undefined` if not found.
   *
   * Only searches top-level fields.
   *
   * @param name - Field name to look up.
   * @returns The matching `SchemaField` or `undefined`.
   *
   * @example
   * ```ts
   * const f = schema.getField("role");
   * console.log(f?.type); // "enum"
   * ```
   */
  getField(name: string): SchemaField | undefined {
    return this.fields.find((f) => f.name === name);
  }

  /**
   * Return the wire index (0-based) of an enum value within a named enum.
   *
   * @param enumName - Name of the enum type, e.g. "MessageRole".
   * @param valueName - Symbolic value name, e.g. "assistant".
   * @returns The integer index.
   *
   * @throws {SchemaNotFoundError} If the enum or value is not found.
   *
   * @example
   * ```ts
   * const idx = schema.getEnumIndex("MessageRole", "assistant");
   * console.log(idx); // 2
   * ```
   */
  getEnumIndex(enumName: string, valueName: string): number {
    const def = this.enums.find((e) => e.name === enumName);
    if (!def) {
      throw new SchemaNotFoundError(`Enum '${enumName}' not found in schema '${this.name}'`);
    }
    const idx = def.values.indexOf(valueName);
    if (idx === -1) {
      throw new SchemaNotFoundError(
        `Value '${valueName}' not found in enum '${enumName}'`,
        { details: { enumName, valueName, available: def.values } }
      );
    }
    return idx;
  }

  /**
   * Return the symbolic name for an enum value at the given index.
   *
   * @param enumName - Name of the enum type.
   * @param index - Zero-based index.
   * @returns The symbolic name string.
   *
   * @throws {SchemaNotFoundError} If the enum is not found or index is out of range.
   *
   * @example
   * ```ts
   * const name = schema.getEnumName("MessageRole", 2);
   * console.log(name); // "assistant"
   * ```
   */
  getEnumName(enumName: string, index: number): string {
    const def = this.enums.find((e) => e.name === enumName);
    if (!def) {
      throw new SchemaNotFoundError(`Enum '${enumName}' not found in schema '${this.name}'`);
    }
    if (index < 0 || index >= def.values.length) {
      throw new SchemaNotFoundError(
        `Enum index ${index} out of range for enum '${enumName}' (length ${def.values.length})`,
        { details: { enumName, index, length: def.values.length } }
      );
    }
    return def.values[index];
  }

  // ---------------------------------------------------------------------------
  // Canonical JSON serialization
  // ---------------------------------------------------------------------------

  /**
   * Produce the canonical JSON string used for hash computation.
   *
   * Fields are sorted alphabetically to ensure deterministic output.
   *
   * @returns Canonical JSON string of the schema.
   *
   * @example
   * ```ts
   * const json = schema.toCanonicalJson();
   * ```
   */
  toCanonicalJson(): string {
    const obj = {
      name: this.name,
      version: this.version,
      fields: this.fields.map(canonicalizeField),
      enums: this.enums.map((e) => ({ name: e.name, values: [...e.values] })),
    };
    return JSON.stringify(obj);
  }

  /**
   * Serialize this schema to a plain object.
   *
   * @returns A plain object representation of the schema.
   */
  toDict(): Record<string, unknown> {
    return {
      name: this.name,
      version: this.version,
      fields: this.fields,
      enums: this.enums,
    };
  }

  // ---------------------------------------------------------------------------
  // Private helpers
  // ---------------------------------------------------------------------------

  private _assignFieldIds(fields: SchemaField[], startId: number): SchemaField[] {
    let id = startId;
    return fields.map((f) => {
      const assigned: SchemaField = { ...f, fieldId: id++ };
      if (f.fields) {
        // Nested objects reuse a local counter starting from 0
        assigned.fields = this._assignFieldIds(f.fields, 0);
      }
      return assigned;
    });
  }
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

function canonicalizeField(f: SchemaField): Record<string, unknown> {
  const out: Record<string, unknown> = {
    name: f.name,
    type: f.type,
    required: f.required,
  };
  if (f.enumName !== undefined) out.enumName = f.enumName;
  if (f.vectorDtype !== undefined) out.vectorDtype = f.vectorDtype;
  if (f.vectorDim !== undefined) out.vectorDim = f.vectorDim;
  if (f.fields !== undefined) out.fields = f.fields.map(canonicalizeField);
  return out;
}
