"""JSONL writer for per-step trajectory logs — `schema_version 1.0` (LOCKED).

The schema is locked at git tag `benchmark-prereg-v1`. Mid-study evolution
is forbidden (SPEC.md §7). If a needed field is discovered missing, the
study halts and a `schema_version 1.1` is opened, with all earlier runs
re-classified as pilot.

This module emits exactly the schema in SPEC.md §7. The runner is
responsible for piping `query()` message stream events through it.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# Locked schema version. Bumping requires opening a new pre-registration cycle.
SCHEMA_VERSION: str = "1.0"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _sha256(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class StepRecord:
    """One step of a trajectory. Fields locked at SCHEMA_VERSION 1.0."""

    trajectory_id: str
    step: int

    # turn_input
    system_prompt_hash: Optional[str] = None
    user_message: Optional[str] = None
    tool_results_from_prior_step: list[dict] = field(default_factory=list)
    edp_active_block: Optional[str] = None
    edp_active_block_token_count: Optional[int] = None
    placebo_block: Optional[str] = None
    placebo_block_token_count: Optional[int] = None
    input_token_count: Optional[int] = None
    cached_input_token_count: Optional[int] = None

    # model
    model_name: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    seed: Optional[int] = None

    # turn_output
    text: Optional[str] = None
    tool_calls: list[dict] = field(default_factory=list)
    output_token_count: Optional[int] = None
    stop_reason: Optional[str] = None

    # edp_state_after_step (None for conditions A and C)
    active_decision_ids: Optional[list[str]] = None
    decisions_read_this_step: Optional[list[str]] = None
    decisions_written_this_step: Optional[list[str]] = None
    decisions_superseded_this_step: Optional[list[str]] = None

    # cost (per-step)
    input_usd: Optional[float] = None
    cached_input_usd: Optional[float] = None
    output_usd: Optional[float] = None
    step_total_usd: Optional[float] = None

    # latency + errors
    latency_ms: Optional[int] = None
    errors: Optional[str] = None

    # internal — not written
    _ts: str = field(default_factory=_now_iso)

    def to_jsonl_dict(self) -> dict[str, Any]:
        """Serialize to the locked SCHEMA_VERSION 1.0 dict shape."""
        edp_state: Optional[dict[str, Any]]
        if self.active_decision_ids is None and self.decisions_read_this_step is None:
            edp_state = None
        else:
            edp_state = {
                "active_decision_ids": self.active_decision_ids or [],
                "decisions_read_this_step": self.decisions_read_this_step or [],
                "decisions_written_this_step": self.decisions_written_this_step or [],
                "decisions_superseded_this_step": self.decisions_superseded_this_step or [],
            }

        return {
            "schema_version": SCHEMA_VERSION,
            "trajectory_id": self.trajectory_id,
            "step": self.step,
            "ts": self._ts,
            "turn_input": {
                "system_prompt_hash": self.system_prompt_hash,
                "user_message": self.user_message,
                "tool_results_from_prior_step": self.tool_results_from_prior_step,
                "edp_active_block": self.edp_active_block,
                "edp_active_block_token_count": self.edp_active_block_token_count,
                "placebo_block": self.placebo_block,
                "placebo_block_token_count": self.placebo_block_token_count,
                "input_token_count": self.input_token_count,
                "cached_input_token_count": self.cached_input_token_count,
            },
            "model": {
                "name": self.model_name,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "seed": self.seed,
            },
            "turn_output": {
                "text": self.text,
                "tool_calls": self.tool_calls,
                "output_token_count": self.output_token_count,
                "stop_reason": self.stop_reason,
            },
            "edp_state_after_step": edp_state,
            "cost": {
                "input_usd": self.input_usd,
                "cached_input_usd": self.cached_input_usd,
                "output_usd": self.output_usd,
                "step_total_usd": self.step_total_usd,
            },
            "latency_ms": self.latency_ms,
            "errors": self.errors,
        }


@dataclass
class TrajectoryLogger:
    """Append-only JSONL writer for one trajectory. Caller drives `write()` per step."""

    trajectory_id: str
    log_path: Path
    _t_start_monotonic: float = field(default_factory=time.monotonic)
    _step_counter: int = 0

    def __post_init__(self) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        # Pre-warm the file so partial trajectories are still inspectable on crash.
        with self.log_path.open("a") as f:
            f.write("")

    def next_step(self) -> int:
        """Increment and return the step counter. Use to label `StepRecord.step`."""
        self._step_counter += 1
        return self._step_counter

    def write(self, record: StepRecord) -> None:
        """Append one record as a single JSONL line."""
        with self.log_path.open("a") as f:
            f.write(json.dumps(record.to_jsonl_dict(), default=str) + "\n")

    def hash_system_prompt(self, text: str) -> str:
        """Compute the locked `sha256:` system_prompt_hash format."""
        return _sha256(text)


@dataclass
class TrajectorySummary:
    """Terminal summary written alongside the JSONL, distilled from ResultMessage.

    Pre-tag auto-fill source for the tagger's worksheet (SPEC.md §6).
    """

    trajectory_id: str
    task_id: str
    condition: str
    seed: int
    model: str
    temperature: float

    subtype: Optional[str] = None
    num_turns: Optional[int] = None
    duration_ms: Optional[int] = None
    duration_api_ms: Optional[int] = None
    total_cost_usd: Optional[float] = None
    usage: Optional[dict] = None
    model_usage: Optional[dict] = None
    stop_reason: Optional[str] = None
    session_id: Optional[str] = None
    result_text: Optional[str] = None
    permission_denials: Optional[list] = None
    task_success: Optional[bool] = None
    budget_exhausted: Optional[bool] = None
    error: Optional[str] = None

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w") as f:
            json.dump(self.__dict__, f, indent=2, default=str)


def open_manifest(out_dir: Path) -> Path:
    """Return the path to the (run-wide) blinding manifest. Caller appends entries.

    Manifest is held by the runner author only; taggers do not see it. After
    tagging is closed, the manifest is committed to git via
    `benchmark/analysis/commit_tagging.py` (per SPEC.md §6 unblinding).
    """
    manifest = out_dir / "manifest.jsonl"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    if not manifest.exists():
        manifest.touch()
    return manifest


def append_manifest(
    manifest_path: Path,
    *,
    trajectory_id: str,
    task_id: str,
    condition: str,
    seed: int,
    model: str,
    log_filename: str,
    verifier_enabled: bool = False,
) -> None:
    """Append one (trajectory_id → (task, condition, seed, verifier_enabled)) mapping.

    `verifier_enabled` distinguishes pre-registered B (False) from mini-experiment
    Bv (True) at the manifest level so the analysis step can stratify.
    """
    entry = {
        "trajectory_id": trajectory_id,
        "task_id": task_id,
        "condition": condition,
        "seed": seed,
        "model": model,
        "verifier_enabled": verifier_enabled,
        "log_filename": log_filename,
        "appended_at": _now_iso(),
    }
    with manifest_path.open("a") as f:
        f.write(json.dumps(entry) + "\n")
