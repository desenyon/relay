# Schema Registry

Schemas are canonically represented as compact JSON (sorted keys) and hashed with SHA-256; the first four bytes of the digest are embedded in the frame header.

The Python implementation stores JSON files under `~/.relay/registry/` by default (`SchemaRegistry`).
