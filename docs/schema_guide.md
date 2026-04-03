# Schema guide

Schemas can be authored as `.rschema` files or built with `RelaySchema.from_dict`.
See [`spec/RELAY_SCHEMA_REGISTRY.md`](../spec/RELAY_SCHEMA_REGISTRY.md) for the
registry protocol and [`relay/schema.py`](../relay/schema.py) for the Python model.

Register schemas with `relay.registry.register` or `relay schema register`.
