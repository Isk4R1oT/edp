"""Side mini-experiment: condition B with verifier vs without, paired same-task.

NOT part of the pre-registered formal study (`benchmark-prereg-v1`). This
script exists so the user can answer one specific exploratory question:

  Does adding the v0.2.0 PreToolUse verifier on top of visibility-only EDP
  meaningfully change the trajectory (step count, drift events, cost) for
  a single task at a single seed?

Two trajectories run in fully isolated workspaces:

  workspace_no_verifier/  ← condition B, verifier_enabled=False
    ├── .edp/             ← fresh empty store
    ├── .claude/
    │   └── settings.json ← SessionStart + UserPromptSubmit hooks only
    └── (task workspace)

  workspace_with_verifier/  ← condition B, verifier_enabled=True
    ├── .edp/             ← fresh empty store (different file from above)
    ├── .claude/
    │   └── settings.json ← + PreToolUse verifier hook
    └── (task workspace)

Same task, same seed, same model — so any delta is attributable to the
verifier-hook presence (modulo the variance ceiling at single-seed N=1).
The two runs DO NOT share state — different cwd, different SQLite store,
different .claude config. Run in parallel via asyncio.gather.

Cost estimate (Haiku 4.5, single seed):
  - 2 trajectories × ~50 turns × ~5K input + ~1.5K output per turn
  - ≈ $1–2 total. Cheap.

Usage:

    pip install -e sdk-python/                              # v0.2.0
    pip install 'explicit-decision-protocol[verifier]'       # for verifier path
    pip install -e benchmark/                                # for fern-mcp-server
    export ANTHROPIC_API_KEY=sk-ant-...                      # verifier needs key

    # Default: T7 (custom multi-session tinytq, forces architectural commitments early)
    python -m benchmark.mini_experiment

    # Override:
    python -m benchmark.mini_experiment --task t01_django_11066 --seed 7 --model claude-haiku-4-5

After both trajectories complete, prints a side-by-side summary and writes a
combined manifest entry so the analysis script can stratify.

WARNING: this script is exploratory, NOT pre-registered. Results from a
single seed are statistical noise per arXiv:2602.07150. Treat any observed
delta as hypothesis-generating, not hypothesis-confirming. The formal
verifier-vs-no-verifier study requires k≥4 seeds and proper pre-registration.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import asdict
from pathlib import Path

from benchmark.logger import open_manifest
from benchmark.runner import RunSpec, preflight_check, run_one
from benchmark.tasks import TASK_REGISTRY


async def _run_pair(
    task_id: str,
    *,
    seed: int,
    model: str,
    temperature: float,
    out_dir: Path,
) -> None:
    manifest = open_manifest(out_dir)
    task = TASK_REGISTRY[task_id]

    spec_no_verifier = RunSpec(
        task_id=task_id,
        condition="B",
        seed=seed,
        model=model,
        temperature=temperature,
        verifier_enabled=False,
    )
    spec_with_verifier = RunSpec(
        task_id=task_id,
        condition="B",
        seed=seed,
        model=model,
        temperature=temperature,
        verifier_enabled=True,
    )

    print(
        f"[mini_experiment] starting paired run on {task_id} seed={seed} model={model}\n"
        f"[mini_experiment]   workspace_no_verifier  = {out_dir}/<traj_id>/workspace\n"
        f"[mini_experiment]   workspace_with_verifier = {out_dir}/<traj_id>/workspace\n"
        f"[mini_experiment] runs are isolated — separate cwd, separate .edp/, "
        f"separate .claude/ config"
    )

    # Run both in parallel — they share NOTHING on disk.
    summary_no_v, summary_with_v = await asyncio.gather(
        run_one(spec=spec_no_verifier, task=task, out_dir=out_dir, manifest_path=manifest),
        run_one(spec=spec_with_verifier, task=task, out_dir=out_dir, manifest_path=manifest),
    )

    print()
    print("=" * 78)
    print("MINI-EXPERIMENT — SIDE-BY-SIDE")
    print("=" * 78)
    print(f"{'metric':<28} {'no verifier':>20} {'with verifier':>20}  {'delta':>8}")
    print("-" * 78)

    def _row(label: str, a, b, fmt: str = "{}"):
        try:
            sa = fmt.format(a) if a is not None else "—"
            sb = fmt.format(b) if b is not None else "—"
            if isinstance(a, (int, float)) and isinstance(b, (int, float)) and a is not None and b is not None:
                d = b - a
                sd = f"{d:+.2f}" if isinstance(d, float) else f"{d:+d}"
            else:
                sd = "—"
            print(f"{label:<28} {sa:>20} {sb:>20}  {sd:>8}")
        except Exception:  # noqa: BLE001
            print(f"{label:<28} {str(a):>20} {str(b):>20}  {'—':>8}")

    _row("subtype", summary_no_v.subtype, summary_with_v.subtype)
    _row("num_turns", summary_no_v.num_turns, summary_with_v.num_turns)
    _row("duration_ms", summary_no_v.duration_ms, summary_with_v.duration_ms)
    _row("total_cost_usd", summary_no_v.total_cost_usd, summary_with_v.total_cost_usd, "{:.4f}")
    _row("budget_exhausted", summary_no_v.budget_exhausted, summary_with_v.budget_exhausted)
    _row("error", summary_no_v.error, summary_with_v.error)

    print("=" * 78)
    print()
    print("Trajectories written to:")
    print(f"  {out_dir}/{summary_no_v.trajectory_id}/    (no verifier)")
    print(f"  {out_dir}/{summary_with_v.trajectory_id}/  (with verifier)")
    print()
    print("Inspect manually — read the JSONL files turn-by-turn. The manifest")
    print(f"({out_dir}/manifest.jsonl) carries the verifier_enabled flag for stratification.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "EDP benchmark — single-task paired mini-experiment "
            "(condition B with verifier vs without)"
        )
    )
    parser.add_argument(
        "--task",
        default="t07_tiny_tq_multisession",
        choices=list(TASK_REGISTRY.keys()),
        help=(
            "Task id. Default: T7 (tinytq multi-session) — forces multiple "
            "architectural decisions early, ideal for surfacing whether the "
            "verifier blocks violations the agent would otherwise commit."
        ),
    )
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument(
        "--model",
        default="claude-haiku-4-5",
        help="Default Haiku 4.5 for the cheap mini-experiment. Sonnet 4.6 for realism.",
    )
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("benchmark/runs/_mini"),
        help="Output dir (default: benchmark/runs/_mini)",
    )
    parser.add_argument("--skip-preflight", action="store_true")
    args = parser.parse_args()

    if not args.skip_preflight:
        try:
            preflight_check()
        except RuntimeError as exc:
            print(f"[mini_experiment] preflight FAILED:\n{exc}", file=sys.stderr)
            sys.exit(2)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    asyncio.run(
        _run_pair(
            args.task,
            seed=args.seed,
            model=args.model,
            temperature=args.temperature,
            out_dir=args.out_dir,
        )
    )


if __name__ == "__main__":
    main()
