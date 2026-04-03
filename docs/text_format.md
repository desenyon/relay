# Text format

Human-readable `.relay` documents are specified in
[`spec/RELAY_TEXT_FORMAT.md`](../spec/RELAY_TEXT_FORMAT.md).

The Python APIs `relay.encode_text` and `relay.decode_text` round-trip with the
binary wire format when a schema is registered for hash resolution.
