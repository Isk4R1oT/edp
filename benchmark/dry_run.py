"""Single-case dry-run: 1 task × 1 condition × 1 seed.

Purpose: smoke-test the end-to-end pipeline (preflight check, ClaudeAgentOptions
construction, query() invocation, JSONL writer, summary writer) on a single
trajectory before launching the full sweep.

Default: T6 (pytest-dev/pytest-11604, medium difficulty) under condition A
(bare agent, no EDP, no placebo) with seed=1. Estimated cost: ~$0.50, wall
time ~5 min.

Override with CLI flags:
  python -m benchmark.dry_run --task pytest-dev__pytest-11604 --condition A --seed 1

A successful dry_run produces:
  benchmark/runs/<run_id>/traj_*.jsonl       (per-step log)
  benchmark/runs/<run_id>/traj_*.summary.json (terminal summary)
  benchmark/runs/manifest.jsonl              (one entry)

A failing dry_run surfaces (a) MCP server missing, (b) tool-schema parity
broken, (c) JSONL schema field mismatch, (d) API auth issues — before the
full sweep wastes hours.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from benchmark.conditions import ConditionName
from benchmark.runner import RunSpec, preflight_check, run_one
from benchmark.logger import open_manifest
from benchmark.tasks import TASK_REGISTRY


async def _drive_one(spec: RunSpec, out_dir: Path) -> None:
    manifest = open_manifest(out_dir)
    task = TASK_REGISTRY[spec.task_id]
    print(f"[dry_run] starting {spec.task_id} cond={spec.condition} seed={spec.seed}")
    summary = await run_one(
        spec=spec, task=task, out_dir=out_dir, manifest_path=manifest
    )
    print(f"[dry_run] done trajectory_id={summary.trajectory_id}")
    print(f"[dry_run]   subtype={summary.subtype}")
    print(f"[dry_run]   num_turns={summary.num_turns}")
    print(f"[dry_run]   duration_ms={summary.duration_ms}")
    print(f"[dry_run]   total_cost_usd={summary.total_cost_usd}")
    print(f"[dry_run]   budget_exhausted={summary.budget_exhausted}")
    print(f"[dry_run]   error={summary.error}")


def main() -> None:
    parser = argparse.ArgumentParser(description="EDP benchmark dry-run (single case)")
    parser.add_argument(
        "--task", default="pytest-dev__pytest-11604",
        choices=list(TASK_REGISTRY.keys()),
        help="Task id (default: T6 pytest-dev/pytest-11604)",
    )
    parser.add_argument("--condition", default="A", choices=["A", "B", "C"])
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument(
        "--enable-verifier",
        action="store_true",
        help=(
            "Only meaningful with --condition B. Stages a PreToolUse hook that "
            "invokes the v0.2.0 verifier on write-class tools. Requires "
            "'pip install explicit-decision-protocol[verifier]' + ANTHROPIC_API_KEY."
        ),
    )
    parser.add_argument("--model", default="claude-haiku-4-5",
                        help="Default: Haiku 4.5 (cheap for dry-run). "
                             "Use claude-sonnet-4-6 for cost-realistic dry-run.")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--out-dir", type=Path, default=Path("benchmark/runs/_dry"))
    parser.add_argument("--skip-preflight", action="store_true")
    args = parser.parse_args()

    if not args.skip_preflight:
        try:
            preflight_check()
        except RuntimeError as exc:
            print(f"[dry_run] preflight FAILED:\n{exc}", file=sys.stderr)
            sys.exit(2)

    spec = RunSpec(
        task_id=args.task,
        condition=args.condition,
        seed=args.seed,
        model=args.model,
        temperature=args.temperature,
        verifier_enabled=args.enable_verifier,
    )
    asyncio.run(_drive_one(spec, args.out_dir))


if __name__ == "__main__":
    main()
