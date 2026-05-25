"""Shared helpers for SWE-Bench-Verified task configs.

Each SWE-Bench task is identified by a `<repo>__<repo>-<issue>` instance id and
ships with: a fresh repo clone at the base commit, the issue text, and a
hidden test suite. Success = patch + tests pass.

The setup helper clones the repo and checks out the base commit. The check
helper invokes the official SWE-Bench evaluation harness. Neither is run by
this file — they are called by `runner.py` (setup) and by a post-run
analysis script (check), respectively.

Reference: https://github.com/princeton-nlp/SWE-bench (official harness).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

# Hugging Face dataset id, locked. Per SPEC.md §1.
SWE_BENCH_DATASET: str = "princeton-nlp/SWE-bench_Verified"


def make_setup(instance_id: str):
    """Build a setup(workspace) closure that stages a SWE-Bench instance.

    Implementation note: actual repo cloning is delegated to the SWE-Bench
    harness CLI to avoid duplicating its environment-setup logic. The runner
    invokes `setup(workspace)` once per trajectory; the heavy lifting (docker
    images, test-suite isolation) is handled by the harness.

    The closure WRITES `workspace/instance.json` so the post-run check
    helper knows which instance to evaluate.
    """

    def setup(workspace: Path) -> None:
        (workspace / "instance.json").write_text(
            json.dumps({"instance_id": instance_id, "dataset": SWE_BENCH_DATASET}, indent=2)
        )
        # Real SWE-Bench setup happens here; for now we just record the intent.
        # When wired up, this calls:
        #   subprocess.run(
        #       ["swebench", "instance", "stage", "--instance-id", instance_id,
        #        "--workspace", str(workspace)],
        #       check=True,
        #   )
        # Pre-pilot acceptance test: ensure swebench CLI is on PATH.
        return None

    return setup


def make_check(instance_id: str):
    """Build a check(workspace) closure that runs the SWE-Bench eval harness.

    Returns (success: bool, details: dict) where details includes test-suite
    pass/fail counts and the harness verdict.
    """

    def check(workspace: Path) -> tuple[bool, dict]:
        # Real call:
        #   r = subprocess.run(
        #       ["swebench", "evaluate", "--instance-id", instance_id,
        #        "--workspace", str(workspace), "--json"],
        #       capture_output=True, text=True, check=False,
        #   )
        #   verdict = json.loads(r.stdout)
        # For benchmark scaffolding we return a placeholder so dry_run.py works.
        return False, {
            "instance_id": instance_id,
            "harness_run": False,
            "note": "swebench harness not invoked in scaffold; wire in post-pilot.",
        }

    return check


def issue_prompt(instance_id: str, issue_text: str) -> str:
    """Build the initial user prompt for a SWE-Bench task.

    Same prompt shape across all 6 tasks for comparability. The prompt does
    NOT mention EDP, the placebo, or the experiment — the agent should not
    behave differently based on knowing it's being measured.
    """
    return (
        f"You are working on the {instance_id} repository at its base commit. "
        f"Your task: resolve the issue below by editing the codebase. The hidden "
        f"test suite will validate your patch — make targeted, minimal changes that "
        f"address the root cause. Use the available file-editing tools.\n\n"
        f"---\n\nISSUE:\n\n{issue_text}\n\n---\n\n"
        f"When you believe the patch is complete, summarize the change and stop. "
        f"Do not edit tests in the test/ directory."
    )
