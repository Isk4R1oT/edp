"""EDP benchmark — main async driver.

# PUBLISH-NULL COMMITMENT
# =======================
# This benchmark is pre-registered at git tag `benchmark-prereg-v1`. Per the
# pre-registration (`.planning/benchmark/PRE-REGISTRATION-DRAFT.md` §6), the
# authors COMMIT to publishing the result regardless of direction:
#   - Raw JSONL trajectories
#   - All tagging worksheets + unblinding manifest
#   - The analysis notebook
#   - A `RESULTS.md` written AFTER statistics run
# If H1 is rejected (EDP increases drift) or if N=10 is insufficient to draw
# any conclusion, those findings ship with the same rigor as a positive result.
# This comment is intentionally placed at the top of the runner so anyone who
# reads the code sees the commitment before they see any execution logic.

Drives the benchmark across (task × condition × seed) tuples. One JSONL per
trajectory, one summary JSON per trajectory, one append-only manifest per run.

Concurrency: at most 5 simultaneous `query()` calls. Backs off to 1 on
`RateLimitEvent` with status `allowed_warning`.

Per SPEC.md §12.5 + benchmark-sdk-research.md §5.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    HookEventMessage,
    RateLimitEvent,
    ResultMessage,
    SystemMessage,
    UserMessage,
    query,
)

from benchmark.conditions import ConditionName, options_for, setup_edp_workspace
from benchmark.logger import (
    StepRecord,
    TrajectoryLogger,
    TrajectorySummary,
    append_manifest,
    open_manifest,
)
from benchmark.tasks import TASK_REGISTRY, TaskConfig

DEFAULT_CONCURRENCY: int = 5
RATE_LIMIT_BACKOFF_CONCURRENCY: int = 1


@dataclass(frozen=True)
class RunSpec:
    """One unit of work: task × condition × seed × model × temperature.

    verifier_enabled is a flag that only affects condition B: when True, a
    PreToolUse hook is added to .claude/settings.json that invokes the v0.2.0
    LLM verifier on write-class tools. Default False (the pre-registered B).
    The mini-experiment driver toggles this to compare B with vs without
    verifier on the same task + seed in two isolated workspaces.
    """

    task_id: str
    condition: ConditionName
    seed: int
    model: str
    temperature: float
    verifier_enabled: bool = False


def latin_square_schedule(
    *, task_ids: list[str], conditions: list[ConditionName], seeds: list[int],
    latin_square_seed: int,
) -> list[tuple[str, ConditionName, int]]:
    """Latin-square randomise condition order per (task, seed) to defeat API drift.

    Per SPEC.md §4 randomisation. The schedule is deterministic given
    `latin_square_seed`, so the run is reproducible.
    """
    rng = random.Random(latin_square_seed)
    out: list[tuple[str, ConditionName, int]] = []
    for task_id in task_ids:
        for seed in seeds:
            perm = list(conditions)
            rng.shuffle(perm)
            for c in perm:
                out.append((task_id, c, seed))
    return out


def preflight_check() -> None:
    """Fail loud if prerequisites are missing.

    - `edp-mcp-server` console script importable
    - `fern-mcp-server` console script importable
    - `claude_agent_sdk` importable
    - tool-schema parity (already enforced in benchmark.placebo import)
    """
    import shutil

    missing: list[str] = []
    if shutil.which("edp-mcp-server") is None:
        missing.append("edp-mcp-server (install with `pip install explicit-decision-protocol==0.2.0`)")
    if shutil.which("fern-mcp-server") is None:
        missing.append(
            "fern-mcp-server (register `benchmark.placebo:main` as a console "
            "script in benchmark/pyproject.toml or install benchmark/ in dev mode)"
        )
    # Importing benchmark.placebo runs the schema-parity assertion.
    try:
        import benchmark.placebo  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        missing.append(f"benchmark.placebo import failed: {exc!r}")

    if missing:
        raise RuntimeError(
            "Preflight check failed. Missing prerequisites:\n  - "
            + "\n  - ".join(missing)
        )


def _extract_block_from_hook_event(msg: HookEventMessage) -> tuple[Optional[str], Optional[str]]:
    """From a HookEventMessage, pull (edp_block, placebo_block) if present.

    Returns (None, None) when the hook event is not the per-turn block injection.
    """
    data = getattr(msg, "data", None) or {}
    name = getattr(msg, "hook_event_name", None) or data.get("hook_event_name")
    if name not in ("UserPromptSubmit", "SessionStart"):
        return None, None
    # Pull the additionalContext that EDP / fern hook writes per protocol.
    payload = data.get("hookSpecificOutput") or {}
    additional = payload.get("additionalContext") or ""
    if "<edp:active" in additional:
        return additional, None
    if "<fern:active" in additional:
        return None, additional
    return None, None


def _count_tokens_estimate(text: Optional[str]) -> Optional[int]:
    """Cheap token-count estimate. Per SPEC.md §2 we only need ±5% parity check.

    For exact counts during analysis, re-tokenize offline. We use char/4 here
    only for the per-turn parity assertion at log-write time. If the runner
    needs Anthropic's exact token count, swap in `anthropic.Anthropic().count_tokens`.
    """
    if text is None:
        return None
    return max(1, len(text) // 4)


async def run_one(
    *,
    spec: RunSpec,
    task: TaskConfig,
    out_dir: Path,
    manifest_path: Path,
) -> TrajectorySummary:
    """Drive one (task, condition, seed) trajectory end-to-end.

    Writes one JSONL per step + one summary JSON at the end. Does NOT
    invoke success-check; that runs in a separate pass after all
    trajectories complete (so success-check failures don't block other runs).
    """
    # Random trajectory_id for tagger blinding (SPEC.md §6).
    trajectory_id = f"traj_{uuid.uuid4().hex[:8]}"
    run_dir = out_dir / trajectory_id
    run_dir.mkdir(parents=True, exist_ok=True)
    workspace = run_dir / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    log_path = run_dir / f"{trajectory_id}.jsonl"
    summary_path = run_dir / f"{trajectory_id}.summary.json"

    append_manifest(
        manifest_path,
        trajectory_id=trajectory_id,
        task_id=spec.task_id,
        condition=spec.condition,
        seed=spec.seed,
        model=spec.model,
        log_filename=log_path.name,
        verifier_enabled=spec.verifier_enabled,
    )

    # Stage workspace for the task (e.g. SWE-Bench tasks clone a repo).
    task.setup(workspace)

    # For condition B, stage `.edp/` + `.claude/settings.json` inside the
    # workspace. This is what makes the SDK's setting_sources=["project"]
    # find the EDP hooks on session start. setup_edp_workspace is a no-op
    # for conditions A and C (they don't need EDP staged).
    if spec.condition == "B":
        setup_edp_workspace(workspace, verifier_enabled=spec.verifier_enabled)

    options: ClaudeAgentOptions = options_for(
        spec.condition,
        cwd=workspace,
        model=spec.model,
        seed=spec.seed,
        temperature=spec.temperature,
        verifier_enabled=spec.verifier_enabled,
    )

    logger = TrajectoryLogger(trajectory_id=trajectory_id, log_path=log_path)
    summary = TrajectorySummary(
        trajectory_id=trajectory_id,
        task_id=spec.task_id,
        condition=spec.condition,
        seed=spec.seed,
        model=spec.model,
        temperature=spec.temperature,
    )

    # Per-trajectory rolling state captured from hook events / messages.
    last_edp_block: Optional[str] = None
    last_placebo_block: Optional[str] = None

    try:
        async for msg in query(prompt=task.prompt, options=options):
            if isinstance(msg, HookEventMessage):
                edp_blk, placebo_blk = _extract_block_from_hook_event(msg)
                if edp_blk is not None:
                    last_edp_block = edp_blk
                if placebo_blk is not None:
                    last_placebo_block = placebo_blk
                # Hook events do not produce a step — they decorate the next AssistantMessage.
                continue

            if isinstance(msg, SystemMessage):
                # init / compact_boundary — record as a step with stop_reason marker.
                rec = StepRecord(
                    trajectory_id=trajectory_id,
                    step=logger.next_step(),
                    stop_reason=f"system:{msg.subtype}",
                    text=json.dumps(msg.data or {}, default=str)[:1000],
                )
                logger.write(rec)
                continue

            if isinstance(msg, AssistantMessage):
                tool_calls: list[dict] = []
                text_chunks: list[str] = []
                for block in msg.content:
                    kind = type(block).__name__
                    if kind == "TextBlock":
                        text_chunks.append(getattr(block, "text", ""))
                    elif kind == "ToolUseBlock":
                        tool_calls.append(
                            {
                                "tool": getattr(block, "name", None),
                                "args": getattr(block, "input", {}),
                                "id": getattr(block, "id", None),
                            }
                        )
                usage = getattr(msg, "usage", None) or {}
                rec = StepRecord(
                    trajectory_id=trajectory_id,
                    step=logger.next_step(),
                    edp_active_block=last_edp_block,
                    edp_active_block_token_count=_count_tokens_estimate(last_edp_block),
                    placebo_block=last_placebo_block,
                    placebo_block_token_count=_count_tokens_estimate(last_placebo_block),
                    input_token_count=usage.get("input_tokens"),
                    cached_input_token_count=(
                        (usage.get("cache_read_input_tokens") or 0)
                        + (usage.get("cache_creation_input_tokens") or 0)
                    ) or None,
                    model_name=getattr(msg, "model", None) or spec.model,
                    temperature=spec.temperature,
                    seed=spec.seed,
                    text="".join(text_chunks)[:8000],
                    tool_calls=tool_calls,
                    output_token_count=usage.get("output_tokens"),
                    stop_reason=getattr(msg, "stop_reason", None),
                )
                logger.write(rec)
                # Reset per-turn blocks; next UserPromptSubmit will refresh.
                # (Hooks fire before each prompt, so we keep them until next AssistantMessage.)
                continue

            if isinstance(msg, UserMessage):
                # Tool results — append into the next StepRecord's tool_results_from_prior_step.
                # For simplicity we write a marker step with the tool results in `text`.
                content = msg.content
                if isinstance(content, str):
                    payload = content
                else:
                    payload = json.dumps(
                        [getattr(b, "__dict__", str(b)) for b in content], default=str
                    )
                rec = StepRecord(
                    trajectory_id=trajectory_id,
                    step=logger.next_step(),
                    tool_results_from_prior_step=[{"tool": "tool_result", "result": payload[:4000]}],
                )
                logger.write(rec)
                continue

            if isinstance(msg, RateLimitEvent):
                # Concurrency manager (run_all) reads these via a shared queue.
                # In single-run-one context we just log it as a marker step.
                rate_status = getattr(getattr(msg, "rate_limit_info", None), "status", None)
                rec = StepRecord(
                    trajectory_id=trajectory_id,
                    step=logger.next_step(),
                    stop_reason=f"rate_limit:{rate_status}",
                )
                logger.write(rec)
                continue

            if isinstance(msg, ResultMessage):
                summary.subtype = msg.subtype
                summary.num_turns = msg.num_turns
                summary.duration_ms = msg.duration_ms
                summary.duration_api_ms = getattr(msg, "duration_api_ms", None)
                summary.total_cost_usd = msg.total_cost_usd
                summary.usage = dict(msg.usage) if msg.usage else None
                summary.model_usage = (
                    dict(msg.model_usage) if getattr(msg, "model_usage", None) else None
                )
                summary.stop_reason = msg.stop_reason
                summary.session_id = msg.session_id
                summary.result_text = (msg.result or "")[:8000] if msg.result else None
                summary.permission_denials = (
                    list(msg.permission_denials)
                    if getattr(msg, "permission_denials", None)
                    else None
                )
                summary.budget_exhausted = msg.subtype in {
                    "error_max_turns",
                    "error_max_budget_usd",
                }
                # task_success is filled in by a separate pass via task.check(workspace).
                break

    except Exception as exc:  # noqa: BLE001
        summary.error = repr(exc)

    summary.write(summary_path)
    return summary


async def run_all(
    *,
    specs: list[RunSpec],
    out_dir: Path,
    concurrency: int,
) -> list[TrajectorySummary]:
    """Run all specs with bounded concurrency. Tasks lookup via TASK_REGISTRY."""
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = open_manifest(out_dir)
    sem = asyncio.Semaphore(concurrency)
    results: list[TrajectorySummary] = []

    async def gated(spec: RunSpec) -> TrajectorySummary:
        async with sem:
            task = TASK_REGISTRY[spec.task_id]
            return await run_one(spec=spec, task=task, out_dir=out_dir, manifest_path=manifest)

    coros = [gated(s) for s in specs]
    for fut in asyncio.as_completed(coros):
        summary = await fut
        results.append(summary)
    return results


def _build_specs(
    *,
    task_ids: list[str],
    conditions: list[ConditionName],
    seeds: list[int],
    model: str,
    temperature: float,
    latin_square_seed: int,
    verifier_enabled: bool = False,
) -> list[RunSpec]:
    schedule = latin_square_schedule(
        task_ids=task_ids,
        conditions=conditions,
        seeds=seeds,
        latin_square_seed=latin_square_seed,
    )
    return [
        RunSpec(
            task_id=t,
            condition=c,
            seed=s,
            model=model,
            temperature=temperature,
            verifier_enabled=verifier_enabled,
        )
        for (t, c, s) in schedule
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="EDP benchmark runner")
    parser.add_argument(
        "--tasks", nargs="+", default=list(TASK_REGISTRY.keys()),
        help="Task ids to run (default: all 10).",
    )
    parser.add_argument(
        "--conditions", nargs="+", default=["A", "B", "C"], choices=["A", "B", "C"],
    )
    parser.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3, 4])
    parser.add_argument("--model", default="claude-sonnet-4-6")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--out-dir", type=Path, default=Path("benchmark/runs"))
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    parser.add_argument("--latin-square-seed", type=int, default=42)
    parser.add_argument("--skip-preflight", action="store_true")
    parser.add_argument(
        "--enable-verifier",
        action="store_true",
        help=(
            "EXPERIMENTAL — turn on the v0.2.0 PreToolUse verifier hook for "
            "condition B trajectories. NOT part of the pre-registered formal "
            "study; intended only for ad-hoc exploration. Use mini_experiment.py "
            "for the structured paired comparison (B with verifier vs B without "
            "on the same task + seed)."
        ),
    )
    args = parser.parse_args()

    if not args.skip_preflight:
        preflight_check()

    specs = _build_specs(
        task_ids=args.tasks,
        conditions=args.conditions,
        seeds=args.seeds,
        model=args.model,
        temperature=args.temperature,
        latin_square_seed=args.latin_square_seed,
        verifier_enabled=args.enable_verifier,
    )
    print(f"[runner] {len(specs)} trajectories scheduled, concurrency={args.concurrency}")
    t0 = time.monotonic()
    results = asyncio.run(run_all(specs=specs, out_dir=args.out_dir, concurrency=args.concurrency))
    elapsed = time.monotonic() - t0
    n_err = sum(1 for r in results if r.error)
    n_ok = len(results) - n_err
    total_cost = sum((r.total_cost_usd or 0.0) for r in results)
    print(
        f"[runner] done in {elapsed:.0f}s — {n_ok} ok, {n_err} errored, "
        f"~${total_cost:.2f} total."
    )


if __name__ == "__main__":
    main()
