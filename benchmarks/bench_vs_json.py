"""
bench_vs_json.py — Primary benchmark: Relay vs JSON encode/decode throughput.

Writes structured results to benchmarks/results/latest.json and prints a
summary table to stdout. This is the script run by CI on every merge to main.

Output JSON structure::

    {
      "timestamp": "2025-04-01T12:00:00Z",
      "python_version": "3.11.9",
      "platform": "macOS-14.4-arm64",
      "relay_version": "0.1.0",
      "results": [
        {
          "operation": "encode_small",
          "relay_us_per_op": 1.23,
          "json_us_per_op": 3.45,
          "ratio": 2.80,
          "target_ratio": 2.0,
          "passed": true
        },
        ...
      ],
      "all_passed": true
    }

Usage:
    python benchmarks/bench_vs_json.py
    python benchmarks/bench_vs_json.py --iterations 50000
    python benchmarks/bench_vs_json.py --output path/to/output.json
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import timeit
from datetime import datetime, timezone
from pathlib import Path

# Ensure the repo root is importable without a prior `pip install`.
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

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

# ---------------------------------------------------------------------------
# Schema definitions
# ---------------------------------------------------------------------------

_SMALL_SCHEMA_DICT = {
    "name": "bench_small",
    "version": 1,
    "fields": {
        "role": {"type": "string", "required": True},
        "content": {"type": "string", "required": False},
        "call_id": {"type": "string", "required": False},
    },
}

_MEDIUM_SCHEMA_DICT = {
    "name": "bench_medium",
    "version": 1,
    "fields": {
        "role": {"type": "string", "required": True},
        "content": {"type": "string", "required": False},
        "tool_call": {"type": "object", "required": False},
        "metadata": {"type": "object", "required": False},
    },
}

_LARGE_SCHEMA_DICT = {
    "name": "bench_large",
    "version": 1,
    "fields": {
        "batch_id": {"type": "string", "required": True},
        "model": {"type": "string", "required": False},
        "records": {"type": "array", "required": False},
    },
}

# Encode target: relay >= 2x json.dumps
# Decode target: relay >= 1.5x json.loads
_TARGETS: dict[str, float] = {
    "encode_small": 2.0,
    "encode_medium": 2.0,
    "encode_large": 2.0,
    "decode_small": 1.5,
    "decode_medium": 1.5,
    "decode_large": 1.5,
}


# ---------------------------------------------------------------------------
# Measurement helpers
# ---------------------------------------------------------------------------

def _us_per_op(fn, iterations: int) -> float:
    """Run *fn* for *iterations* times, return microseconds per call."""
    elapsed = timeit.timeit(fn, number=iterations)
    return (elapsed / iterations) * 1e6


def run_benchmarks(iterations: int) -> list[dict]:
    """Execute all benchmark cases and return a list of result dicts."""
    registry = SchemaRegistry()
    small_schema = RelaySchema.from_dict(_SMALL_SCHEMA_DICT)
    medium_schema = RelaySchema.from_dict(_MEDIUM_SCHEMA_DICT)
    large_schema = RelaySchema.from_dict(_LARGE_SCHEMA_DICT)
    for s in (small_schema, medium_schema, large_schema):
        registry.register(s)

    # Pre-encode for decode benchmarks
    small_bytes = relay.encode(SMALL_DICT, small_schema)
    medium_bytes = relay.encode(MEDIUM_DICT, medium_schema)
    large_bytes = relay.encode(LARGE_DICT, large_schema)

    import json as _json
    small_json_str = _json.dumps(SMALL_DICT)
    medium_json_str = _json.dumps(MEDIUM_DICT)
    large_json_str = _json.dumps(LARGE_DICT)

    encode_cases = [
        ("encode_small",  SMALL_DICT,  small_schema,  small_json_str),
        ("encode_medium", MEDIUM_DICT, medium_schema, medium_json_str),
        ("encode_large",  LARGE_DICT,  large_schema,  large_json_str),
    ]
    decode_cases = [
        ("decode_small",  small_bytes,  small_json_str),
        ("decode_medium", medium_bytes, medium_json_str),
        ("decode_large",  large_bytes,  large_json_str),
    ]

    results = []

    for op, payload, schema, json_str in encode_cases:
        relay_us = _us_per_op(lambda p=payload, s=schema: relay.encode(p, s), iterations)
        json_us = _us_per_op(lambda js=json_str: _json.loads(js) or _json.dumps(payload), iterations)
        # json encode (not decode)
        json_enc_us = _us_per_op(lambda p=payload: _json.dumps(p), iterations)
        target = _TARGETS[op]
        ratio = json_enc_us / relay_us
        results.append({
            "operation": op,
            "relay_us_per_op": round(relay_us, 4),
            "json_us_per_op": round(json_enc_us, 4),
            "ratio": round(ratio, 4),
            "target_ratio": target,
            "passed": ratio >= target,
        })

    for op, relay_bytes, json_str in decode_cases:
        relay_us = _us_per_op(lambda rb=relay_bytes: relay.decode(rb), iterations)
        json_us = _us_per_op(lambda js=json_str: _json.loads(js), iterations)
        target = _TARGETS[op]
        ratio = json_us / relay_us
        results.append({
            "operation": op,
            "relay_us_per_op": round(relay_us, 4),
            "json_us_per_op": round(json_us, 4),
            "ratio": round(ratio, 4),
            "target_ratio": target,
            "passed": ratio >= target,
        })

    return results


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _print_table(results: list[dict]) -> None:
    print()
    print("=" * 82)
    print("  Relay vs JSON — encode/decode throughput")
    print("=" * 82)
    print(
        f"  {'operation':<20} {'relay us/op':>12}  {'json us/op':>12}  "
        f"{'ratio':>8}  {'target':>8}  status"
    )
    print("-" * 82)
    for r in results:
        status = "PASS" if r["passed"] else "FAIL"
        print(
            f"  {r['operation']:<20} {r['relay_us_per_op']:>12.4f}  "
            f"{r['json_us_per_op']:>12.4f}  {r['ratio']:>8.3f}x  "
            f"{r['target_ratio']:>7.1f}x  {status}"
        )
    print("=" * 82)


def build_output(results: list[dict]) -> dict:
    return {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "relay_version": relay.__version__,
        "results": results,
        "all_passed": all(r["passed"] for r in results),
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Relay vs JSON throughput benchmark — writes results/latest.json"
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=10_000,
        help="Number of iterations per operation (default: 10000)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=_ROOT / "benchmarks" / "results" / "latest.json",
        help="Path to write JSON results (default: benchmarks/results/latest.json)",
    )
    args = parser.parse_args()

    print(f"Running {args.iterations:,} iterations per operation …")
    results = run_benchmarks(args.iterations)
    output = build_output(results)

    _print_table(results)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + "\n")
    print(f"\nResults written to: {args.output}")

    if not output["all_passed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
