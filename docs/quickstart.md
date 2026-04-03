# Quickstart

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
binary = relay.encode({"msg": "hello"}, schema)
msg = relay.decode(binary, schema=schema)
```

Install the package in editable mode: `pip install -e ".[dev]"`.
