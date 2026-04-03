"""
bench_vs_msgpack.py — Relay vs MessagePack encode/decode throughput benchmark.

MessagePack is a common binary alternative to JSON. This benchmark provides
context for how Relay's binary encoding compares to MessagePack, which has
no semantic typing, schema enforcement, or streaming field dispatch.

Requires the `msgpack` package (already a Relay dependency).

Usage:
    python benchmarks/bench_vs_msgpack.py
    python benchmarks/bench_vs_msgpack.py --iterations 50000
"""

from __future__ import annotations

import argparse
import sys
import timeit
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

try:
    import msgpack
except ImportError:
    print("msgpack is not installed. Run: pip install msgpack")
    sys.exit(1)

import relay
from relay.schema import RelaySchema
from relay.registry import SchemaRegistry

# ---------------------------------------------------------------------------
# Payload fixtures
# ---------------------------------------------------------------------------

SMALL_DICT = {
    "role": "assistant",
    "content": "Hello, world!",
    "call_id": "550e8400-e29b-41d4-a716-446655440000",
}

MEDIUM_DICT = {
    "role": "assistant",
    "content": "Here is the result of the calculation you requested.",
    "tool_call": {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "name": "calculate_npv",
        "arguments": {
            "cash_flows": [100.0, 200.0, 300.0, 400.0, 500.0, 150.0, 250.0, 350.0],
            "discount_rate": 0.08,
            "periods": 8,
            "currency": "USD",
            "label": "Project Alpha NPV",
        },
    },
    "metadata": {
        "model": "claude-sonnet-4-6",
        "tokens_used": 512,
        "latency_ms": 340,
        "session_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    },
}

LARGE_DICT = {
    "batch_id": "batch-2025-001",
    "model": "claude-sonnet-4-6",
    "records": [
        {
            "index": i,
            "role": "assistant",
            "content": (
                f"Generated response number {i} with padding text to increase "
                "payload size significantly for benchmarking purposes."
            ),
            "tool_call": {
                "id": f"call-{i:04d}-550e8400-e29b-41d4-a716-{i:012d}",
                "name": "analyze_data",
                "arguments": {
                    "dataset": f"dataset_{i}",
                    "operation": "summarize",
                    "parameters": {
                        "max_rows": 1000 + i,
                        "timeout": 30.0,
                        "include_metadata": True,
                    },
                },
            },
            "score": 0.85 + (i % 10) * 0.01,
        }
        for i in range(20)
    ],
}

_SMALL_SCHEMA = {
    "name": "bench_small",
    "version": 1,
    "fields": {
        "role": {"type": "string", "required": True},
        "content": {"type": "string", "required": False},
        "call_id": {"type": "string", "required": False},
    },
}
_MEDIUM_SCHEMA = {
    "name": "bench_medium",
    "version": 1,
    "fields": {
        "role": {"type": "string", "required": True},
        "content": {"type": "string", "required": False},
        "tool_call": {"type": "object", "required": False},
        "metadata": {"type": "object", "required": False},
    },
}
_LARGE_SCHEMA = {
    "name": "bench_large",
    "version": 1,
    "fields": {
        "batch_id": {"type": "string", "required": True},
        "model": {"type": "string", "required": False},
        "records": {"type": "array", "required": False},
    },
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _us(fn, iterations: int) -> float:
    elapsed = timeit.timeit(fn, number=iterations)
    return (elapsed / iterations) * 1e6


def _encode_size(data: bytes) -> str:
    if len(data) < 1024:
        return f"{len(data)} B"
    return f"{len(data) / 1024:.1f} KB"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Relay vs MessagePack throughput benchmark"
    )
    parser.add_argument("--iterations", type=int, default=10_000)
    args = parser.parse_args()
    iters = args.iterations

    registry = SchemaRegistry()
    small_schema = RelaySchema.from_dict(_SMALL_SCHEMA)
    medium_schema = RelaySchema.from_dict(_MEDIUM_SCHEMA)
    large_schema = RelaySchema.from_dict(_LARGE_SCHEMA)
    for s in (small_schema, medium_schema, large_schema):
        registry.register(s)

    cases = [
        ("small  (~100 B)", SMALL_DICT, small_schema),
        ("medium (~1 KB) ", MEDIUM_DICT, medium_schema),
        ("large  (~10 KB)", LARGE_DICT, large_schema),
    ]

    print()
    print("=" * 90)
    print("  Relay vs MessagePack — encode/decode throughput comparison")
    print(f"  Iterations per case: {iters:,}")
    print("  Note: MessagePack has no schema enforcement, semantic types, or streaming.")
    print("=" * 90)

    # ----- encode -----
    print()
    print("  ENCODE")
    print(
        f"  {'Payload':<22} {'relay us/op':>12}  {'msgpack us/op':>14}  "
        f"{'relay size':>12}  {'msgpack size':>13}  {'ratio':>8}"
    )
    print("-" * 90)

    for label, payload, schema in cases:
        relay_bytes = relay.encode(payload, schema)
        msgpack_bytes = msgpack.packb(payload, use_bin_type=True)

        relay_enc_us = _us(lambda p=payload, s=schema: relay.encode(p, s), iters)
        msgpack_enc_us = _us(lambda p=payload: msgpack.packb(p, use_bin_type=True), iters)
        ratio = msgpack_enc_us / relay_enc_us

        print(
            f"  {label:<22} {relay_enc_us:>12.4f}  {msgpack_enc_us:>14.4f}  "
            f"{_encode_size(relay_bytes):>12}  {_encode_size(msgpack_bytes):>13}  "
            f"{ratio:>7.2f}x"
        )

    # ----- decode -----
    print()
    print("  DECODE")
    print(
        f"  {'Payload':<22} {'relay us/op':>12}  {'msgpack us/op':>14}  {'ratio':>8}"
    )
    print("-" * 90)

    for label, payload, schema in cases:
        relay_bytes = relay.encode(payload, schema)
        msgpack_bytes = msgpack.packb(payload, use_bin_type=True)

        relay_dec_us = _us(lambda rb=relay_bytes: relay.decode(rb), iters)
        msgpack_dec_us = _us(
            lambda mb=msgpack_bytes: msgpack.unpackb(mb, raw=False), iters
        )
        ratio = msgpack_dec_us / relay_dec_us

        print(
            f"  {label:<22} {relay_dec_us:>12.4f}  {msgpack_dec_us:>14.4f}  "
            f"{ratio:>7.2f}x"
        )

    print("=" * 90)
    print()
    print(
        "  Relay's ratio >1 means Relay is faster than MessagePack despite carrying "
        "full schema enforcement and semantic type validation."
    )
    print()


if __name__ == "__main__":
    main()
