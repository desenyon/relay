"""``relay bench`` — run bundled performance comparisons."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import click
from rich.console import Console

console = Console()


@click.command("bench")
@click.option("--iterations", default=5000, show_default=True)
@click.option(
    "--payload-size",
    type=click.Choice(["small", "medium", "large"], case_sensitive=False),
    default="medium",
)
@click.option(
    "--compare",
    type=click.Choice(["json", "msgpack", "both"], case_sensitive=False),
    default="both",
)
def bench_cmd(iterations: int, payload_size: str, compare: str) -> None:
    """Run encode/decode benchmarks (JSON / MessagePack baseline)."""
    root = Path(__file__).resolve().parents[3]
    script = root / "benchmarks" / "bench_vs_json.py"
    env = {**os.environ, "RELAY_BENCH_ITERATIONS": str(iterations)}
    if not script.exists():
        console.print("[yellow]benchmarks/bench_vs_json.py not found[/yellow]")
        raise SystemExit(1)
    console.print(
        f"[dim]Running {script.name} "
        f"(iterations={iterations}, size={payload_size}, compare={compare})[/dim]"
    )
    rc = subprocess.call([sys.executable, str(script)], cwd=str(root), env=env)
    raise SystemExit(rc)


__all__ = ["bench_cmd"]
