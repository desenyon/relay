# Compatibility layers

JSON, OpenAI tool-call, and Anthropic tool-use shims live under `relay.compat`.
They map external shapes into schema-fixed Relay messages. See
`relay/compat/json_compat.py`, `openai_compat.py`, and `anthropic_compat.py`.
