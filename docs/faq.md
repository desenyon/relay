# FAQ

**Why does `import relay.registry` not load the registry module?**  
The `relay` package exposes a `registry` attribute (the default
`SchemaRegistry` instance), which shadows the submodule name. Use
`importlib.import_module("relay.registry")` and then call `get_default_registry()`
on that module (see `relay/registry.py`).
from application code that must patch the default registry in tests.

**Where is the full spec?**  
Under `spec/` in the repository; start with `RELAY_SPEC.md`.
