# Relay

[![CI](https://github.com/desenyon/relay/actions/workflows/ci.yml/badge.svg)](https://github.com/desenyon/relay/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

**Relay** is a production-oriented, schema-enforced binary interchange format for agentic AI stacks: length-prefixed field frames (streaming-friendly), semantic wire types (`uuid`, `datetime`, `vector`, `enum`, `markdown_block`, …), **DELTA** mutations, and session **`$ref`** resolution. A canonical **text** encoding (`.relay`) round-trips with the binary wire format.

| Artifact | Package / path |
|----------|----------------|
| Python | `relay-format` on PyPI — `import relay` |
| TypeScript | `relay-format` on npm — `relay-js/` (types, schema helpers; encoder parity expanding) |
| Spec | [`spec/RELAY_SPEC.md`](spec/RELAY_SPEC.md) |

---

## Install

**Python** (3.10+):

```bash
pip install relay-format
# or from a clone:
pip install -e ".[dev]"
```

**Node** (workspace / local build):

```bash
npm install
npm run build -w relay-js
```

---

## Python quickstart (under 20 lines)

```python
import relay
from relay.schema import RelaySchema

schema = RelaySchema.from_dict({
    "name": "ping",
    "version": 1,
    "fields": [{"name": "msg", "type": "string", "required": True}],
    "enums": {},
})

relay.registry.register(schema)

payload = {"msg": "hello, agents"}
binary = relay.encode(payload, schema)
msg = relay.decode(binary, schema=schema)
assert msg.get_field("msg").value == "hello, agents"

text = relay.encode_text(payload, schema)
msg2 = relay.decode_text(text)  # requires schema in default registry
```

### Text format

```python
from relay.text_encoder import RelayTextEncoder

enc = RelayTextEncoder(schema)
print(enc.encode_text({"msg": "Line one.\nLine two."}))
# @relay 1.0
# @schema ping:<hash>
# @type FULL
#
# msg: string "Line one.\nLine two."
```

### Session and references

```python
from relay.session import Session
from relay.types import RelayRef
from uuid import UUID

sess = Session(session_id=UUID("550e8400-e29b-41d4-a716-446655440000"))
idx = sess.record(msg)
ref = RelayRef(sess.session_id, idx, "msg")
assert sess.resolve_ref(ref) == "hello, agents"
```

### Compatibility (OpenAI / Anthropic)

```python
from relay.compat import from_openai_tool_call, to_openai_tool_call

call = {
    "id": "call_abc",
    "type": "function",
    "function": {
        "name": "get_weather",
        "arguments": '{"location": "NYC"}',
    },
}
blob = from_openai_tool_call(call)
roundtrip = to_openai_tool_call(blob)
```

---

## CLI

```bash
relay --help
relay inspect message.bin --format pretty
relay validate message.bin --schema 'my_schema:deadbeef'
relay convert payload.json --from json --to relay-text --schema 'my_schema:deadbeef'
relay schema register ./schemas/agent.rschema
relay schema list
relay bench
```

---

## TypeScript (relay-js)

```typescript
import { TypeTag } from "relay-format";
import { RelayError } from "relay-format";

const tag = TypeTag.STRING;
const err = new RelayError("example", { code: "E001" });
```

Build and test from repo root:

```bash
npm ci
npm run build -w relay-js
npm test -w relay-js
```

---

## Documentation site

```bash
pip install -e ".[dev]"
mkdocs build
# output in site/
```

Guides live under [`docs/`](docs/) and link to the normative `spec/` documents.

---

## Development

```bash
make install    # pip install -e ".[dev]"
make lint       # ruff, mypy, black
make test       # pytest + coverage (threshold in pyproject.toml)
make build      # Python wheel + relay-js bundle
```

---

## Releases

- Pushing a tag matching `v*.*.*` triggers [`.github/workflows/release.yml`](.github/workflows/release.yml) (GitHub Release + attached Python sdist/wheel).
- Optional PyPI/npm publish workflows are under [`.github/workflows/`](.github/workflows/) and expect `PYPI_API_TOKEN` / `NPM_TOKEN` secrets when you enable them.

## Roadmap (vs full CLAUDE.md target)

- Raise Python line coverage toward **100%** (Hypothesis round-trips, remaining decoder/text branches).
- Complete **relay-js** encoder, decoder, streaming, text, delta, and session parity with Python tests.
- Harden benchmark gates in CI for reproducible perf baselines.

---

## License

Apache 2.0 — see [`LICENSE`](LICENSE).

Maintained by Naitik Gupta / Saerin Research.
