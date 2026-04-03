# Wire format

The authoritative binary layout for Relay frames is defined in
[`spec/RELAY_SPEC.md`](../spec/RELAY_SPEC.md). This page summarizes the model:

- A fixed 12-byte frame header (magic, version, message type, schema hash, payload length).
- A payload made of length-prefixed field frames, each with a type tag and value bytes.

Use the Python package (`relay.encode` / `relay.decode`) or the in-progress
`relay-js` build for implementations.
