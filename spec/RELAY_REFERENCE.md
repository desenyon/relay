# References and Deltas

## References (`$ref`)

Binary encoding: type tag `0x18` — session UUID (16 bytes, RFC 4122), call index (uint32 LE), null-terminated UTF-8 field path.

Text form: `$ref session:<uuid>.call[<index>].<field.path>`.

## Delta operations

Opcode bytes: SET `0x01`, DEL `0x02`, APP `0x03`, SPL `0x04`. Layout is specified in `RELAY_TYPES.md` section 5.9.

DELTA frames include field ID `0` (`__base__`) with a `ref` value, followed by `delta_op` fields.
