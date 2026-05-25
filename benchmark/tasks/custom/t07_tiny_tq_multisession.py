"""T7 — tiny-tq v0.1 → v0.2 → v0.3 across 3 sessions. Custom multi-session.

Decisions forced early: sync vs async, ID strategy, retry semantics.
Expected horizon: 120-250 steps over 3 sessions.

Why multi-session: tests EDP's value-add when the agent re-enters a project
and must honour its OWN previous architectural commitments. Single-session
tasks under-test the cross-session memory case.
"""

from __future__ import annotations

import json
from pathlib import Path

from benchmark.tasks import TaskConfig

# Three sessions, three sequential prompts. The runner sends prompt session 1
# first, runs to completion, then session 2 with the same workspace + same
# EDP store, etc. For benchmark scaffolding we concatenate them into a single
# initial prompt with explicit session markers; full multi-session driver
# can be added in pilot.
PROMPT = """\
You are implementing `tiny-tq`, a tiny task queue library in Python. The
project will be built across THREE work sessions; treat each session as a
distinct work block but build on prior commitments.

=== SESSION 1: v0.1 — minimal in-memory queue ===

Goal: ship v0.1 with these features:
  - Queue.enqueue(payload) → str (task_id)
  - Queue.dequeue() → tuple[str, payload] | None
  - Queue.complete(task_id) → bool
  - In-memory storage only (no persistence)
  - Public API in `tinytq/__init__.py`
  - Type-checked with mypy --strict
  - Unit tests passing

Before you write code, decide and STATE in your reply:
  1. Sync vs async — which one defines the public API surface?
  2. ID strategy — sequential ints, UUIDs, ULIDs, or something else?
  3. What happens to a dequeued task if the worker crashes before
     calling .complete()? Visibility-timeout retry, dead-letter, or
     drop-on-the-floor?

Make these three commitments NOW. Write the code. Commit when tests pass.

=== SESSION 2: v0.2 — add persistence ===

Add SQLite persistence WITHOUT changing the public API. Same enqueue /
dequeue / complete signatures. Migrations should be automatic on first
import. Existing v0.1 tests must still pass.

CRITICAL: re-check your three commitments from session 1 before you write
code. If sync vs async, ID strategy, or retry semantics are in tension
with persistence, EITHER honour the original decision OR explicitly
supersede it with a stated reason.

=== SESSION 3: v0.3 — add HTTP API ===

Wrap v0.2 in a tiny HTTP server (FastAPI or stdlib http.server, your
choice). The HTTP API should expose the same enqueue / dequeue / complete
operations as POST endpoints. Once again — re-check your three commitments
before writing the HTTP layer. If async-vs-sync was a sync decision in
v0.1, an async HTTP framework is a contradiction — supersede or honour.

When v0.3 tests pass, summarize what you built and stop.
"""


def _setup(workspace: Path) -> None:
    """Create empty `tinytq/` skeleton + assertion checklist file."""
    pkg = workspace / "tinytq"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text("# tiny-tq scaffold\n")
    (workspace / "README.md").write_text("# tiny-tq\n\nBuilt by the EDP benchmark.\n")
    (workspace / "_assertion_checklist.json").write_text(
        json.dumps(_CHECKLIST, indent=2)
    )


_CHECKLIST: list[dict] = [
    {"id": "A1", "desc": "tinytq/__init__.py exports Queue", "weight": 1},
    {"id": "A2", "desc": "Queue.enqueue, dequeue, complete are callable", "weight": 1},
    {"id": "A3", "desc": "v0.1: in-memory only; no sqlite imports", "weight": 1},
    {"id": "A4", "desc": "v0.2: sqlite imported AND .db file created on first enqueue", "weight": 1},
    {"id": "A5", "desc": "v0.2: enqueue/dequeue/complete public signatures unchanged from v0.1", "weight": 1},
    {"id": "A6", "desc": "v0.3: HTTP endpoint POST /enqueue exists and accepts JSON payload", "weight": 1},
    {"id": "A7", "desc": "v0.3: HTTP endpoint POST /dequeue exists and returns JSON {task_id, payload}", "weight": 1},
    {"id": "A8", "desc": "v0.3: HTTP endpoint POST /complete/<task_id> exists and returns 200/404", "weight": 1},
    {"id": "A9", "desc": "Tests pass for v0.1, v0.2, v0.3 layers", "weight": 1},
    {"id": "A10", "desc": "Session-1 decisions on sync/async + ID strategy + retry are stated explicitly in agent text", "weight": 1},
]


def _check(workspace: Path) -> tuple[bool, dict]:
    """Mechanical assertion checklist. Returns (all_pass, per-item details).

    For real evaluation, replace each block with a real check (import the
    package, hit the HTTP endpoint, etc). Scaffold returns False for safety.
    """
    results: dict[str, dict] = {}
    pkg = workspace / "tinytq"
    init_py = pkg / "__init__.py"
    pkg_text = init_py.read_text() if init_py.exists() else ""
    results["A1"] = {"pass": "Queue" in pkg_text, "evidence": "imports check"}
    # Remaining assertions: real implementation would import the package and
    # exercise it. Placeholder returns False to keep dry_run honest.
    for item in _CHECKLIST[1:]:
        results[item["id"]] = {"pass": False, "evidence": "not yet wired in scaffold"}
    all_pass = all(r["pass"] for r in results.values())
    return all_pass, {"checklist": results}


CONFIG = TaskConfig(
    id="tiny_tq_multisession",
    short_label="T7",
    source="custom",
    horizon_hint="120-250 steps over 3 sessions",
    prompt=PROMPT,
    setup=_setup,
    check=_check,
)
