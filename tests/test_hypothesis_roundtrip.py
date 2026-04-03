"""Property-style round-trips (Hypothesis) for encoder / text format."""

from __future__ import annotations

import tempfile
from pathlib import Path

pytest = __import__("pytest")
pytest.importorskip("hypothesis")

from hypothesis import given, settings
from hypothesis import strategies as st

from relay.decoder import decode
from relay.encoder import encode
from relay.registry import SchemaRegistry
from relay.schema import RelaySchema
from relay.text_decoder import decode_text
from relay.text_encoder import encode_text


@settings(max_examples=30, deadline=None)
@given(st.text(min_size=0, max_size=200))
def test_binary_roundtrip_string_payload(msg: str) -> None:
    sch = RelaySchema.from_dict(
        {
            "name": "hyp_ping",
            "version": 1,
            "fields": [{"name": "msg", "type": "string", "required": True}],
            "enums": {},
        }
    )
    raw = encode({"msg": msg}, sch)
    out = decode(raw, schema=sch, validate=True)
    assert out.get_field("msg").value == msg


@settings(max_examples=20, deadline=None)
@given(st.integers(min_value=-1000, max_value=1000))
def test_text_roundtrip_int32(n: int) -> None:
    sch = RelaySchema.from_dict(
        {
            "name": "hyp_int",
            "version": 1,
            "fields": [{"name": "x", "type": "int32", "required": True}],
            "enums": {},
        }
    )
    with tempfile.TemporaryDirectory() as td:
        reg = SchemaRegistry(Path(td) / "reg2")
        reg.register(sch)
        text = encode_text({"x": n}, sch)
        m = decode_text(text, registry=reg)
        assert m.get_field("x").value == n
