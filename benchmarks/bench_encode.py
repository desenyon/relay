"""
bench_encode.py — Relay encode vs json.dumps throughput benchmark.

Measures encoding throughput for small (~100B), medium (~1KB), and large (~10KB)
payloads across 10000 iterations per size class. Prints a results table to stdout.

Usage:
    python benchmarks/bench_encode.py
"""

import json
import sys
import timeit
from pathlib import Path

# Ensure the repo root is on the path so `relay` is importable without install.
sys.path.insert(0, str(Path(__file__).parent.parent))

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

# Build a large dict by repeating records
LARGE_DICT = {
    "batch_id": "batch-2025-001",
    "model": "claude-sonnet-4-6",
    "records": [
        {
            "index": i,
            "role": "assistant",
            "content": f"Generated response number {i} with some padding text to increase payload size significantly for benchmarking purposes.",
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

# ---------------------------------------------------------------------------
# Schema definitions (minimal, used only to satisfy relay.encode signature)
# ---------------------------------------------------------------------------

SMALL_SCHEMA_DICT = {
    "name": "bench_small",
    "version": 1,
    "fields": {
        "role": {"type": "string", "required": True},
        "content": {"type": "string", "required": False},
        "call_id": {"type": "string", "required": False},
    },
}

MEDIUM_SCHEMA_DICT = {
    "name": "bench_medium",
    "version": 1,
    "fields": {
        "role": {"type": "string", "required": True},
        "content": {"type": "string", "required": False},
        "tool_call": {"type": "object", "required": False},
        "metadata": {"type": "object", "required": False},
    },
}

LARGE_SCHEMA_DICT = {
    "name": "bench_large",
    "version": 1,
    "fields": {
        "batch_id": {"type": "string", "required": True},
        "model": {"type": "string", "required": False},
        "records": {"type": "array", "required": False},
    },
}


# ---------------------------------------------------------------------------
# Benchmark helpers
# ---------------------------------------------------------------------------

ITERATIONS = 10_000


def bench_relay_encode(payload: dict, schema: RelaySchema, iterations: int) -> float:
    """Return microseconds per operation (us/op)."""
    elapsed = timeit.timeit(
        stmt=lambda: relay.encode(payload, schema),
        number=iterations,
    )
    return (elapsed / iterations) * 1e6


def bench_json_encode(payload: dict, iterations: int) -> float:
    """Return microseconds per operation (us/op)."""
    elapsed = timeit.timeit(
        stmt=lambda: json.dumps(payload),
        number=iterations,
    )
    return (elapsed / iterations) * 1e6


def format_row(
    label: str,
    relay_us: float,
    json_us: float,
    ratio: float,
    target: float,
    passed: bool,
) -> str:
    status = "PASS" if passed else "FAIL"
    return (
        f"  {label:<22} {relay_us:>10.2f}  {json_us:>10.2f}  {ratio:>7.2f}x  "
        f"{target:>7.1f}x  {status}"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    registry = SchemaRegistry()
    small_schema = RelaySchema.from_dict(SMALL_SCHEMA_DICT)
    medium_schema = RelaySchema.from_dict(MEDIUM_SCHEMA_DICT)
    large_schema = RelaySchema.from_dict(LARGE_SCHEMA_DICT)

    registry.register(small_schema)
    registry.register(medium_schema)
    registry.register(large_schema)

    cases = [
        ("small  (~100 B)", SMALL_DICT, small_schema),
        ("medium (~1 KB) ", MEDIUM_DICT, medium_schema),
        ("large  (~10 KB)", LARGE_DICT, large_schema),
    ]

    target_ratio = 2.0  # relay must be >= 2x faster than json.dumps

    print()
    print("=" * 78)
    print("  Relay encode vs json.dumps — encode throughput benchmark")
    print(f"  Iterations per case: {ITERATIONS:,}")
    print("=" * 78)
    print(
        f"  {'Payload':<22} {'relay us/op':>10}  {'json us/op':>10}  "
        f"{'ratio':>7}  {'target':>7}  status"
    )
    print("-" * 78)

    all_passed = True
    for label, payload, schema in cases:
        relay_us = bench_relay_encode(payload, schema, ITERATIONS)
        json_us = bench_json_encode(payload, ITERATIONS)
        ratio = json_us / relay_us  # >1 means relay is faster
        passed = ratio >= target_ratio
        if not passed:
            all_passed = False
        print(format_row(label, relay_us, json_us, ratio, target_ratio, passed))

    print("=" * 78)
    if all_passed:
        print("  All targets met.")
    else:
        print("  WARNING: One or more targets not met. See FAIL rows above.")
    print()


if __name__ == "__main__":
    main()
