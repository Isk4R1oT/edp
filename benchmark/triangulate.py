"""3-way paired runner: bare baseline + EDP visibility-only + EDP+verifier.

Single task, single seed, single model — three trajectories run in parallel
in fully isolated workspaces so any delta is attributable to the condition
(modulo single-seed variance per arXiv:2602.07150). NOT pre-registered;
exploratory diagnostic only.

Defaults to T7 (`t07_tiny_tq_multisession`) — a custom multi-session task
that naturally forces architectural decisions early (sync/async, ID strategy,
retry semantics), so the EDP visibility primitive has something meaningful
to surface. Pytest-style bug-fix tasks engage EDP poorly because there are
no obvious architectural commitments to record.

Isolation guarantees per condition:
- separate cwd under benchmark/runs/_tri/<traj_id>/workspace
- separate .edp/ store (only B + B+verifier)
- separate .claude/ config (only B + B+verifier)
- same task seed and model

Usage:

    pip install -e sdk-python/
    pip install -e benchmark/
    pip install 'explicit-decision-protocol[verifier]'   # for B+verifier auth
    python -m benchmark.triangulate

Cost (Haiku 4.5 default): ~$1.5–4 total depending on task budget.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from benchmark.logger import open_manifest
from benchmark.runner import RunSpec, preflight_check, run_one
from benchmark.tasks import TASK_REGISTRY


async def _run_triplet(
    task_id: str,
    *,
    seeds: list[int],
    model: str,
    temperature: float,
    out_dir: Path,
    concurrency: int,
) -> None:
    manifest = open_manifest(out_dir)
    task = TASK_REGISTRY[task_id]

    specs: list[RunSpec] = []
    for seed in seeds:
        specs.append(RunSpec(task_id=task_id, condition="A", seed=seed,
                             model=model, temperature=temperature, verifier_enabled=False))
        specs.append(RunSpec(task_id=task_id, condition="B", seed=seed,
                             model=model, temperature=temperature, verifier_enabled=False))
        specs.append(RunSpec(task_id=task_id, condition="B", seed=seed,
                             model=model, temperature=temperature, verifier_enabled=True))

    print(
        f"[triangulate] starting {len(specs)} runs on {task_id} model={model}\n"
        f"[triangulate]   seeds: {seeds}\n"
        f"[triangulate]   3 conditions per seed: A bare / B (no verifier) / B (with verifier)\n"
        f"[triangulate]   concurrency: {concurrency}\n"
        f"[triangulate] runs are isolated: separate cwd, separate .edp/ (B and B+v), separate .claude/"
    )

    sem = asyncio.Semaphore(concurrency)

    async def gated(spec: RunSpec):
        async with sem:
            return spec, await run_one(spec=spec, task=task, out_dir=out_dir, manifest_path=manifest)

    pairs = await asyncio.gather(*[gated(s) for s in specs])
    # Re-order so output table is grouped by seed → condition
    pairs.sort(key=lambda p: (p[0].seed, p[0].condition, p[0].verifier_enabled))
    summaries = [s for _, s in pairs]
    summary_a = summaries[0] if len(specs) == 3 else None  # legacy path; multi-seed uses table below
    summary_b_no_v = summaries[1] if len(specs) == 3 else None
    summary_b_with_v = summaries[2] if len(specs) == 3 else None

    print()
    print("=" * 110)
    print("TRIANGULATE — RAW PER-RUN RESULTS")
    print("=" * 110)
    # If the task has a drift_check (phased / multi-session tasks), call it
    # per-trajectory and include in the table.
    has_drift = task.drift_check is not None
    drift_label = " drift" if has_drift else ""
    print(f"{'seed':>5} {'condition':<14} {'turns':>7} {'cost':>10} {'dur_s':>8} {'subtype':<22}{drift_label:>7} traj_id")
    print("-" * 120)
    drift_results: dict[str, tuple[int, dict]] = {}
    for spec, summary in pairs:
        cond_name = f"A" if spec.condition == "A" else (f"B+verifier" if spec.verifier_enabled else "B")
        cost = f"${(summary.total_cost_usd or 0):.4f}"
        dur = f"{(summary.duration_ms or 0) / 1000:.1f}"
        drift_str = ""
        if has_drift:
            workspace = out_dir / summary.trajectory_id / "workspace"
            try:
                drift_n, drift_details = task.drift_check(workspace)
                drift_results[summary.trajectory_id] = (drift_n, drift_details)
                drift_str = f"{drift_n:>5}"
            except Exception as exc:  # noqa: BLE001
                drift_str = f" err"
                drift_results[summary.trajectory_id] = (-1, {"error": repr(exc)})
        print(f"{spec.seed:>5} {cond_name:<14} {summary.num_turns or 0:>7} {cost:>10} {dur:>8} "
              f"{(summary.subtype or '?'):<22}{drift_str:>7} {summary.trajectory_id}")

    if has_drift:
        # Save per-trajectory drift details for offline analysis
        drift_path = out_dir / "drift_results.json"
        import json as _json
        drift_path.write_text(_json.dumps({
            tid: {"drift_count": dn, "details": dd}
            for tid, (dn, dd) in drift_results.items()
        }, indent=2, default=str))
        print(f"\n[triangulate] drift_check details → {drift_path}")

    # Per-condition aggregates
    from statistics import mean, stdev
    print()
    print("=" * 110)
    print("AGGREGATES PER CONDITION")
    print("=" * 110)
    by_cond: dict[str, list] = {"A bare": [], "B (no verifier)": [], "B (with verifier)": []}
    for spec, summary in pairs:
        if spec.condition == "A":
            label = "A bare"
        elif spec.verifier_enabled:
            label = "B (with verifier)"
        else:
            label = "B (no verifier)"
        by_cond[label].append(summary)

    drift_header = " drift mean" if has_drift else ""
    print(f"{'condition':<22} {'n':>3} {'turns mean':>12} {'turns σ':>10} {'cost mean':>12} {'cost σ':>10} {'success rate':>15}{drift_header:>14}")
    print("-" * 130)
    for label, summaries_for_cond in by_cond.items():
        if not summaries_for_cond:
            continue
        turns_vals = [s.num_turns or 0 for s in summaries_for_cond]
        cost_vals = [s.total_cost_usd or 0 for s in summaries_for_cond]
        success_rate = sum(1 for s in summaries_for_cond if s.subtype == "success") / len(summaries_for_cond)
        turns_sd = stdev(turns_vals) if len(turns_vals) > 1 else 0.0
        cost_sd = stdev(cost_vals) if len(cost_vals) > 1 else 0.0
        drift_str = ""
        if has_drift:
            drifts = [drift_results.get(s.trajectory_id, (None,))[0] for s in summaries_for_cond]
            drifts = [d for d in drifts if d is not None and d >= 0]
            if drifts:
                drift_str = f"{mean(drifts):>13.2f}"
            else:
                drift_str = f"{'—':>13}"
        print(f"{label:<22} {len(summaries_for_cond):>3} {mean(turns_vals):>12.1f} {turns_sd:>10.2f} "
              f"${mean(cost_vals):>10.4f} ${cost_sd:>8.4f} {success_rate*100:>14.0f}%{drift_str:>14}")

    print()
    print(f"Manifest (with condition + verifier_enabled): {out_dir}/manifest.jsonl")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="EDP benchmark — 3-way paired exploratory triangulation (A vs B vs B+verifier)"
    )
    parser.add_argument(
        "--task",
        default="tiny_tq_multisession",
        choices=list(TASK_REGISTRY.keys()),
        help=(
            "Task id. Default T7 (tinytq multi-session) naturally engages EDP "
            "via early architectural commitments. SWE-Bench bug-fix tasks "
            "engage EDP poorly — agent has no commitments to record."
        ),
    )
    parser.add_argument("--seeds", type=int, nargs="+", default=[1],
                        help="Seeds to run; total runs = len(seeds) × 3 conditions. Default [1] (single seed).")
    parser.add_argument(
        "--model",
        default="claude-haiku-4-5",
        help="Default Haiku 4.5 for the cheap triangulation. Sonnet 4.6 for realism.",
    )
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("benchmark/runs/_tri"),
        help="Output dir (default: benchmark/runs/_tri)",
    )
    parser.add_argument("--concurrency", type=int, default=4,
                        help="Max parallel trajectories (default 4).")
    parser.add_argument("--skip-preflight", action="store_true")
    args = parser.parse_args()

    if not args.skip_preflight:
        try:
            preflight_check()
        except RuntimeError as exc:
            print(f"[triangulate] preflight FAILED:\n{exc}", file=sys.stderr)
            sys.exit(2)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    asyncio.run(
        _run_triplet(
            args.task,
            seeds=args.seeds,
            model=args.model,
            temperature=args.temperature,
            out_dir=args.out_dir,
            concurrency=args.concurrency,
        )
    )


if __name__ == "__main__":
    main()
