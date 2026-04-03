/**
 * Relay error class hierarchy with machine-readable error codes.
 *
 * Every error in the Relay system is a typed `RelayError` subclass that carries
 * a stable, machine-readable `code` string, an optional `fieldPath` that
 * locates the offending field inside a Relay message, and a free-form `details`
 * record for supplemental context.
 *
 * @module errors
 */

/**
 * Serialized representation of a Relay error.
 */
export interface RelayErrorDict {
  code: string;
  errorType: string;
  message: string;
  fieldPath: string | undefined;
  details: Record<string, unknown>;
}

/**
 * Base class for all Relay errors.
 *
 * @example
 * ```ts
 * const err = new RelayError("something went wrong", { code: "E000" });
 * console.log(err.code); // "E000"
 * ```
 */
export class RelayError extends Error {
  /** Machine-readable error code of the form `E0NN`. */
  readonly code: string;
  /** Dot-separated path to the field that triggered the error, if applicable. */
  readonly fieldPath: string | undefined;
  /** Arbitrary supplemental data. */
  readonly details: Record<string, unknown>;

  /**
   * @param message - Human-readable description of the error.
   * @param options - Optional configuration.
   * @param options.code - Machine-readable error code (default: "E000").
   * @param options.fieldPath - Dot-separated field path, e.g. "tool_call.arguments.discount_rate".
   * @param options.details - Arbitrary supplemental data.
   */
  constructor(
    message: string,
    options: {
      code?: string;
      fieldPath?: string;
      details?: Record<string, unknown>;
    } = {}
  ) {
    super(message);
    this.name = this.constructor.name;
    this.code = options.code ?? 'E000';
    this.fieldPath = options.fieldPath;
    this.details = options.details ?? {};
    // Restore prototype chain (needed for instanceof checks in transpiled code)
    Object.setPrototypeOf(this, new.target.prototype);
  }

  /**
   * Serialize the error to a plain object.
   *
   * @returns A JSON-serializable representation of the error.
   *
   * @example
   * ```ts
   * const err = new RelayError("bad", { code: "E001", fieldPath: "foo.bar" });
   * console.log(err.toDict().fieldPath); // "foo.bar"
   * ```
   */
  toDict(): RelayErrorDict {
    return {
      code: this.code,
      errorType: this.constructor.name,
      message: this.message,
      fieldPath: this.fieldPath,
      details: this.details,
    };
  }
}

/**
 * Raised when raw bytes or text cannot be parsed as a valid Relay frame.
 *
 * Error code: `E001`.
 *
 * @example
 * ```ts
 * throw new ParseError("unexpected magic byte", { details: { got: 0xFF } });
 * ```
 */
export class ParseError extends RelayError {
  constructor(
    message: string,
    options: { fieldPath?: string; details?: Record<string, unknown> } = {}
  ) {
    super(message, { code: 'E001', ...options });
  }
}

/**
 * Raised when a field value does not match the declared schema type.
 *
 * Error code: `E002`.
 *
 * @example
 * ```ts
 * throw new TypeMismatchError("expected float32, got string", {
 *   fieldPath: "arguments.rate",
 *   details: { expected: "float32", got: "string" },
 * });
 * ```
 */
export class TypeMismatchError extends RelayError {
  constructor(
    message: string,
    options: { fieldPath?: string; details?: Record<string, unknown> } = {}
  ) {
    super(message, { code: 'E002', ...options });
  }
}

/**
 * Raised when a referenced schema cannot be located in the registry,
 * or when a required field is absent from a message.
 *
 * Error code: `E003`.
 *
 * @example
 * ```ts
 * throw new SchemaNotFoundError("schema 'agent_tool_call:a3f2bc01' not found");
 * ```
 */
export class SchemaNotFoundError extends RelayError {
  constructor(
    message: string,
    options: { fieldPath?: string; details?: Record<string, unknown> } = {}
  ) {
    super(message, { code: 'E003', ...options });
  }
}

/**
 * Raised when a `$ref` cannot be resolved within the session context.
 *
 * Named `RelayReferenceError` to avoid shadowing the built-in `ReferenceError`.
 *
 * Error code: `E004`.
 *
 * @example
 * ```ts
 * throw new RelayReferenceError("call index 99 does not exist in session", {
 *   details: { callIndex: 99 },
 * });
 * ```
 */
export class RelayReferenceError extends RelayError {
  constructor(
    message: string,
    options: { fieldPath?: string; details?: Record<string, unknown> } = {}
  ) {
    super(message, { code: 'E004', ...options });
  }
}

/**
 * Raised when a delta operation cannot be applied cleanly to its base.
 *
 * Error code: `E005`.
 *
 * @example
 * ```ts
 * throw new DeltaConflictError("SPL out of range", {
 *   fieldPath: "content.items",
 *   details: { spliceStart: 10, arrayLength: 3 },
 * });
 * ```
 */
export class DeltaConflictError extends RelayError {
  constructor(
    message: string,
    options: { fieldPath?: string; details?: Record<string, unknown> } = {}
  ) {
    super(message, { code: 'E005', ...options });
  }
}

/**
 * Raised when a message fails schema validation for reasons other than type mismatch.
 *
 * Error code: `E006`.
 *
 * @example
 * ```ts
 * throw new ValidationError("required field 'role' is missing", { fieldPath: "role" });
 * ```
 */
export class ValidationError extends RelayError {
  constructor(
    message: string,
    options: { fieldPath?: string; details?: Record<string, unknown> } = {}
  ) {
    super(message, { code: 'E006', ...options });
  }
}

/**
 * Raised when a JavaScript/TypeScript object cannot be encoded into a Relay binary frame.
 *
 * Error code: `E007`.
 *
 * @example
 * ```ts
 * throw new EncodingError("value out of range for int8", {
 *   fieldPath: "count",
 *   details: { value: 300 },
 * });
 * ```
 */
export class EncodingError extends RelayError {
  constructor(
    message: string,
    options: { fieldPath?: string; details?: Record<string, unknown> } = {}
  ) {
    super(message, { code: 'E007', ...options });
  }
}

/**
 * Raised when binary Relay bytes cannot be decoded into a JavaScript object.
 *
 * Error code: `E008`.
 *
 * @example
 * ```ts
 * throw new DecodingError("unexpected end of stream while reading field value", {
 *   details: { offset: 42 },
 * });
 * ```
 */
export class DecodingError extends RelayError {
  constructor(
    message: string,
    options: { fieldPath?: string; details?: Record<string, unknown> } = {}
  ) {
    super(message, { code: 'E008', ...options });
  }
}

/**
 * Raised when the schema registry encounters a storage or consistency error.
 *
 * Error code: `E009`.
 *
 * @example
 * ```ts
 * throw new RegistryError("registry is corrupted");
 * ```
 */
export class RegistryError extends RelayError {
  constructor(
    message: string,
    options: { fieldPath?: string; details?: Record<string, unknown> } = {}
  ) {
    super(message, { code: 'E009', ...options });
  }
}

/**
 * Raised when the 4-byte schema hash in a frame header does not match any registered schema.
 *
 * Error code: `E010`.
 *
 * @example
 * ```ts
 * throw new SchemaHashMismatch("schema hash a3f2bc01 not found in registry", {
 *   details: { hash: "a3f2bc01" },
 * });
 * ```
 */
export class SchemaHashMismatch extends RelayError {
  constructor(
    message: string,
    options: { fieldPath?: string; details?: Record<string, unknown> } = {}
  ) {
    super(message, { code: 'E010', ...options });
  }
}
