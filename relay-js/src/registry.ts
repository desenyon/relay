/**
 * Schema registry for the Relay runtime.
 *
 * The registry stores schemas keyed by `name:hash`. It is in-memory for
 * universal browser/Node compatibility, with optional `localStorage`
 * persistence when running in a browser environment.
 *
 * @module registry
 */

import { RegistryError, SchemaNotFoundError } from './errors.js';
import { RelaySchema } from './schema.js';

const LOCALSTORAGE_PREFIX = 'relay:schema:';

/**
 * Summary entry returned by `SchemaRegistry.list()`.
 */
export interface SchemaEntry {
  /** Schema name. */
  name: string;
  /** 8-character hex hash (4 bytes). */
  hash: string;
  /** Schema version integer. */
  version: number;
}

/**
 * In-memory schema registry with optional `localStorage` persistence.
 *
 * Use a single shared `SchemaRegistry` instance (or the module-level
 * `globalRegistry`) within an application.
 *
 * @example
 * ```ts
 * const registry = new SchemaRegistry();
 * const hash = await registry.register(mySchema);
 * const schema = registry.get("my_schema", hash);
 * ```
 */
export class SchemaRegistry {
  /** Use localStorage for persistence (browser only). */
  readonly persistent: boolean;

  private readonly _store = new Map<string, RelaySchema>();

  /**
   * @param persistent - If `true`, attempt to persist schemas to `localStorage`.
   *   Silently falls back to in-memory if `localStorage` is unavailable.
   */
  constructor(persistent = false) {
    this.persistent = persistent;
    if (persistent) {
      this._loadFromStorage();
    }
  }

  // ---------------------------------------------------------------------------
  // Public API
  // ---------------------------------------------------------------------------

  /**
   * Register a schema in the registry.
   *
   * If a schema with the same `name:hash` is already registered, this is a
   * no-op and the existing hash is returned.
   *
   * @param schema - The `RelaySchema` to register.
   * @returns Promise resolving to the 8-character hex hash of the schema.
   *
   * @throws {RegistryError} If the hash computation fails.
   *
   * @example
   * ```ts
   * const hash = await registry.register(mySchema);
   * console.log(hash); // "a3f2bc01"
   * ```
   */
  async register(schema: RelaySchema): Promise<string> {
    let hash: string;
    try {
      hash = await schema.hash();
    } catch (err) {
      throw new RegistryError(`Failed to compute schema hash: ${String(err)}`, {
        details: { schemaName: schema.name },
      });
    }
    const key = `${schema.name}:${hash}`;
    if (!this._store.has(key)) {
      this._store.set(key, schema);
      if (this.persistent) {
        this._persistToStorage(key, schema);
      }
    }
    return hash;
  }

  /**
   * Retrieve a schema by name and hash.
   *
   * @param name - The schema name.
   * @param hash - The 8-character hex hash string.
   * @returns The `RelaySchema` instance.
   *
   * @throws {SchemaNotFoundError} If no matching schema is found.
   *
   * @example
   * ```ts
   * const schema = registry.get("agent_tool_call", "a3f2bc01");
   * ```
   */
  get(name: string, hash: string): RelaySchema {
    const key = `${name}:${hash}`;
    const schema = this._store.get(key);
    if (!schema) {
      throw new SchemaNotFoundError(
        `Schema '${name}:${hash}' not found in registry`,
        { details: { name, hash } }
      );
    }
    return schema;
  }

  /**
   * Look up a schema by the raw 4-byte hash. Scans all entries.
   *
   * @param hashBytes - 4-byte `Uint8Array` from a frame header.
   * @returns The matching `RelaySchema` or `undefined`.
   *
   * @example
   * ```ts
   * const schema = registry.getByHashBytes(frameHeader.slice(4, 8));
   * ```
   */
  getByHashBytes(hashBytes: Uint8Array): RelaySchema | undefined {
    const hexStr = Array.from(hashBytes)
      .map((b) => b.toString(16).padStart(2, '0'))
      .join('');
    for (const [key, schema] of this._store.entries()) {
      if (key.endsWith(`:${hexStr}`)) {
        return schema;
      }
    }
    return undefined;
  }

  /**
   * List all registered schemas.
   *
   * @returns Array of `SchemaEntry` objects.
   *
   * @example
   * ```ts
   * const entries = registry.list();
   * entries.forEach(e => console.log(`${e.name}:${e.hash} v${e.version}`));
   * ```
   */
  list(): SchemaEntry[] {
    const entries: SchemaEntry[] = [];
    for (const [key, schema] of this._store.entries()) {
      const colonIdx = key.lastIndexOf(':');
      const hash = key.slice(colonIdx + 1);
      entries.push({ name: schema.name, hash, version: schema.version });
    }
    return entries;
  }

  /**
   * Remove all schemas from the registry (and from `localStorage` if persistent).
   *
   * @example
   * ```ts
   * registry.clear();
   * ```
   */
  clear(): void {
    if (this.persistent) {
      for (const key of this._store.keys()) {
        try {
          localStorage.removeItem(LOCALSTORAGE_PREFIX + key);
        } catch {
          // Ignore storage errors
        }
      }
    }
    this._store.clear();
  }

  // ---------------------------------------------------------------------------
  // Private persistence helpers (browser localStorage)
  // ---------------------------------------------------------------------------

  private _persistToStorage(key: string, schema: RelaySchema): void {
    try {
      localStorage.setItem(
        LOCALSTORAGE_PREFIX + key,
        JSON.stringify(schema.toDict())
      );
    } catch {
      // localStorage unavailable or quota exceeded — silently continue
    }
  }

  private _loadFromStorage(): void {
    try {
      for (let i = 0; i < localStorage.length; i++) {
        const storageKey = localStorage.key(i);
        if (storageKey?.startsWith(LOCALSTORAGE_PREFIX)) {
          const raw = localStorage.getItem(storageKey);
          if (raw) {
            try {
              const dict = JSON.parse(raw) as Record<string, unknown>;
              const schema = RelaySchema.fromDict(dict);
              const key = storageKey.slice(LOCALSTORAGE_PREFIX.length);
              this._store.set(key, schema);
            } catch {
              // Corrupted entry — skip
            }
          }
        }
      }
    } catch {
      // localStorage unavailable — skip
    }
  }
}

/**
 * Module-level global registry instance.
 *
 * Most applications should register schemas into this shared instance.
 */
export const globalRegistry = new SchemaRegistry();
