"""T11 — tinytq v0.1 then v0.2 across TWO ACTUAL sessions.

Differs from T7 (which packs all 3 sessions into a single SDK query — same
agent context throughout, no real cross-session pressure): this task ships
two PHASE prompts that the runner sends as SEPARATE `query()` calls in the
same workspace, with agent context reset between phases. Filesystem and
.edp/ store persist; agent attention does not.

This is the only honest test design for EDP's claimed value: "decisions
made in session 1 survive into session 2 where they would otherwise be
forgotten." Single-session tests cannot exercise that claim by construction.

Drift hypotheses (measurable mechanically post-run):

  1. Sync-vs-async drift — if session 1 picked sync, does session 2 add
     async code (async def, asyncio import, aiohttp dep)?
  2. ID-type drift — if session 1 picked int IDs, does session 2 introduce
     uuid imports or random string IDs?
  3. Dep-creep drift — does session 2 import a major framework
     (fastapi, flask, sqlalchemy) when session 1 stayed stdlib-only?
  4. Test-pattern drift — does session 2's tests use a different framework
     than session 1's?

We do NOT pre-seed any decisions. The agent must record its own commitments
in session 1 (or not — that's also a measurable behaviour).
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

from benchmark.tasks import TaskConfig


# ── Phase prompts ───────────────────────────────────────────────────────────

_PHASE_1_PROMPT = """\
You are starting a tiny Python library called `tinytq` — a minimal task queue.
Today you ship v0.1.

Goal: implement `tinytq/__init__.py` exposing a `Queue` class with three
public methods, plus a test file `tests/test_queue.py` that exercises them:

  Queue.enqueue(payload: <your decision>) -> <your decision>      # adds a task, returns its id
  Queue.dequeue() -> tuple | None                                 # removes oldest, returns it
  Queue.complete(task_id) -> bool                                 # marks a dequeued task done

Before you write the code, make THREE architectural commitments and state
them clearly in your reply:

  (a) Sync vs async public API?
  (b) ID strategy: sequential int, UUID, ULID, or other?
  (c) Visibility/retry semantics if a worker crashes between dequeue and
      complete — visibility-timeout requeue, dead-letter, or drop?

These three commitments WILL bind future development of tinytq (v0.2, v0.3).
If you have access to EDP tools (mcp__edp__edp_record etc.), use them to
record each commitment with explicit invariants. If not, just write the
commitments into a top-level docstring or design note file.

In-memory only for v0.1 (no persistence yet). Standard library only — no
external deps. Type hints throughout. When the unit tests pass, stop.
"""


_PHASE_2_PROMPT = """\
You are continuing work on `tinytq`. v0.1 already exists in this workspace.
Your task: ship v0.2 — add an HTTP server endpoint.

Goal: add a `tinytq/server.py` module exposing the queue over HTTP with
three endpoints matching the v0.1 method semantics:

  POST /enqueue       body=<payload>           -> {"task_id": ...}
  POST /dequeue                                 -> {"task_id": ..., "payload": ...}  OR 204 if empty
  POST /complete/<task_id>                      -> 200 OK or 404

Also: add a small CLI entry point `python -m tinytq.server --port 8080`
to launch it.

Tests for the HTTP layer go into `tests/test_server.py`.

IMPORTANT — this is a fresh session: your earlier reasoning is no longer in
context. Before writing the HTTP layer:

  1. Inspect the existing `tinytq/` code and tests to understand v0.1's
     architecture (sync/async? id type? retry semantics?).
  2. If your harness gives you tools to read prior commitments (e.g.
     mcp__edp__edp_show, an active block, design notes in the repo) USE
     them — your v0.2 HTTP layer must remain consistent with v0.1.
  3. If you find a v0.1 commitment that conflicts with how you would
     naturally implement v0.2, either honour the commitment OR formally
     supersede it (with a stated reason), but DO NOT silently violate it.

Standard library still preferred; if you need an HTTP framework, justify
the choice and verify it does not contradict v0.1 sync/async stance.

When v0.2 tests pass, summarise what you built (and which v0.1 commitments
it honours) and stop.
"""


# ── Setup ──────────────────────────────────────────────────────────────────


def _setup(workspace: Path) -> None:
    """Create an empty tinytq scaffold. Agent builds the rest in phase 1."""
    pkg = workspace / "tinytq"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text("# tinytq scaffold — agent fills this in\n")
    tests_dir = workspace / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    (tests_dir / "__init__.py").write_text("")
    (workspace / "README.md").write_text("# tinytq\n\nBuilt in two phases by the EDP benchmark.\n")


# ── Success check (mechanical) ──────────────────────────────────────────────


def _check(workspace: Path) -> tuple[bool, dict]:
    """Pass when v0.2 has visible artifacts. Strict mechanical checks; no
    LLM judging. The drift_check below is the analytically interesting one.
    """
    server_py = workspace / "tinytq" / "server.py"
    init_py = workspace / "tinytq" / "__init__.py"
    test_server = workspace / "tests" / "test_server.py"
    queue_class_in_init = "class Queue" in (init_py.read_text() if init_py.exists() else "")
    server_exists = server_py.exists() and len(server_py.read_text()) > 200
    test_server_exists = test_server.exists()
    all_pass = queue_class_in_init and server_exists and test_server_exists
    return all_pass, {
        "queue_class_in_init": queue_class_in_init,
        "server_py_exists": server_exists,
        "test_server_py_exists": test_server_exists,
    }


# ── Drift checker ──────────────────────────────────────────────────────────


def _file_text(p: Path) -> str:
    try:
        return p.read_text(errors="replace")
    except (OSError, UnicodeDecodeError):
        return ""


def _scan_phase1_artefacts(workspace: Path) -> dict:
    """Snapshot the architectural choices visible in v0.1 source.

    Scans ALL `tinytq/*.py` files EXCEPT server.py (v0.2 artefact) — agent
    typically splits Queue into a submodule (queue.py, types.py, etc), so
    just reading __init__.py misses the bulk of the implementation.
    Tests under tests/ matching the v0.1 surface are included.
    """
    pkg_dir = workspace / "tinytq"
    tests_dir = workspace / "tests"
    v1_sources: list[str] = []
    if pkg_dir.is_dir():
        for f in sorted(pkg_dir.glob("*.py")):
            if f.name == "server.py":  # v0.2 artefact
                continue
            v1_sources.append(_file_text(f))
    if tests_dir.is_dir():
        for f in sorted(tests_dir.glob("test_*.py")):
            if "server" in f.name:  # v0.2 tests
                continue
            v1_sources.append(_file_text(f))
    combined = "\n".join(v1_sources)

    phase1 = {
        "uses_async_def": bool(re.search(r"\basync\s+def\s+", combined)),
        "imports_asyncio": bool(re.search(r"^\s*import\s+asyncio", combined, re.MULTILINE)),
        "imports_uuid": bool(re.search(r"^\s*import\s+uuid|^\s*from\s+uuid\s+import", combined, re.MULTILINE)),
        "id_is_int_typed": bool(re.search(r"->\s*int\b", combined)) or bool(re.search(r":\s*int\s*=\s*0", combined)),
        "id_is_str_typed": bool(re.search(r"->\s*str\b", combined)),
        "imports_fastapi": "fastapi" in combined.lower(),
        "imports_flask": "flask" in combined.lower(),
        "imports_sqlalchemy": "sqlalchemy" in combined.lower(),
        "any_external_dep": False,  # filled below
    }
    # Quick external-dep heuristic: any top-level import not in stdlib whitelist
    stdlib = {
        "os", "sys", "json", "re", "uuid", "time", "datetime", "typing",
        "collections", "dataclasses", "pathlib", "asyncio", "subprocess",
        "functools", "itertools", "enum", "logging", "argparse", "threading",
        "queue", "tempfile", "shutil", "io", "abc", "contextlib", "concurrent",
        "pytest", "unittest", "tinytq", "warnings", "string", "random",
        "hashlib", "secrets", "math", "statistics",
    }
    external = set()
    for m in re.finditer(r"^\s*(?:from\s+([A-Za-z_][\w.]*)|import\s+([A-Za-z_][\w.]*))", combined, re.MULTILINE):
        mod = (m.group(1) or m.group(2)).split(".")[0]
        if mod and mod not in stdlib:
            external.add(mod)
    phase1["external_deps_phase1"] = sorted(external)
    phase1["any_external_dep"] = len(external) > 0
    return phase1


def _scan_phase2_artefacts(workspace: Path) -> dict:
    """Snapshot what v0.2 introduced — server.py + test_server.py + any
    new modules under tinytq/ added during phase 2 (heuristic: any *.py file
    newer than the phase-1 ones; but we can also just check server.py +
    test_server.py since the task prompt scopes v0.2 to those)."""
    server_py = _file_text(workspace / "tinytq" / "server.py")
    test_server = _file_text(workspace / "tests" / "test_server.py")
    # Also include any server-companion modules the agent may add
    pkg_dir = workspace / "tinytq"
    extras: list[str] = []
    if pkg_dir.is_dir():
        for f in sorted(pkg_dir.glob("*.py")):
            if f.name in ("server.py", "__init__.py", "queue.py", "types.py", "__main__.py"):
                continue
            # Anything else is likely a v0.2 addition
            extras.append(_file_text(f))
    combined = server_py + "\n" + test_server + "\n" + "\n".join(extras)
    phase2 = {
        "uses_async_def": bool(re.search(r"\basync\s+def\s+", combined)),
        "imports_asyncio": bool(re.search(r"^\s*import\s+asyncio", combined, re.MULTILINE)),
        "imports_uuid": bool(re.search(r"^\s*import\s+uuid|^\s*from\s+uuid\s+import", combined, re.MULTILINE)),
        "imports_fastapi": "fastapi" in combined.lower(),
        "imports_flask": "flask" in combined.lower(),
        "imports_aiohttp": "aiohttp" in combined.lower(),
        "imports_uvicorn": "uvicorn" in combined.lower(),
        "imports_sqlalchemy": "sqlalchemy" in combined.lower(),
    }
    stdlib = {
        "os", "sys", "json", "re", "uuid", "time", "datetime", "typing",
        "collections", "dataclasses", "pathlib", "asyncio", "subprocess",
        "functools", "itertools", "enum", "logging", "argparse", "threading",
        "queue", "tempfile", "shutil", "io", "abc", "contextlib", "concurrent",
        "pytest", "unittest", "tinytq", "warnings", "string", "random",
        "hashlib", "secrets", "math", "statistics", "http", "urllib",
        "wsgiref", "socketserver", "email",
    }
    external = set()
    for m in re.finditer(r"^\s*(?:from\s+([A-Za-z_][\w.]*)|import\s+([A-Za-z_][\w.]*))", combined, re.MULTILINE):
        mod = (m.group(1) or m.group(2)).split(".")[0]
        if mod and mod not in stdlib:
            external.add(mod)
    phase2["external_deps_phase2"] = sorted(external)
    return phase2


def _drift_check(workspace: Path) -> tuple[int, dict]:
    """Count mechanical drift instances between phase 1 and phase 2 artefacts.

    Each drift is a SPECIFIC architectural commitment from phase 1 that
    phase 2 contradicts. Returns (drift_count, per-axis details).
    """
    p1 = _scan_phase1_artefacts(workspace)
    p2 = _scan_phase2_artefacts(workspace)

    drifts: dict[str, dict] = {}

    # 1. Sync→async drift: phase 1 had NO async, phase 2 added async
    drift_sync_async = (not p1["uses_async_def"]) and p2["uses_async_def"]
    drifts["sync_to_async"] = {
        "drift": drift_sync_async,
        "p1_uses_async": p1["uses_async_def"],
        "p2_uses_async": p2["uses_async_def"],
        "p2_imports_asyncio": p2["imports_asyncio"],
    }

    # 2. ID type drift: phase 1 didn't use uuid, phase 2 introduced it
    drift_uuid_added = (not p1["imports_uuid"]) and p2["imports_uuid"]
    drifts["uuid_added"] = {
        "drift": drift_uuid_added,
        "p1_uuid": p1["imports_uuid"],
        "p2_uuid": p2["imports_uuid"],
    }

    # 3. External-dep creep: phase 1 was stdlib-only, phase 2 added external deps
    new_external = set(p2.get("external_deps_phase2", [])) - set(p1.get("external_deps_phase1", []))
    # Filter "expected" v0.2-stage additions out — we LET HTTP frameworks be added
    # IF justified, but flag specific async / heavyweight frameworks.
    forbidden_v2 = {"fastapi", "starlette", "aiohttp", "uvicorn", "tornado"} & new_external
    drift_async_framework = (not p1["uses_async_def"]) and bool(forbidden_v2)
    drifts["async_framework_added"] = {
        "drift": drift_async_framework,
        "p1_sync": not p1["uses_async_def"],
        "forbidden_async_frameworks_in_p2": sorted(forbidden_v2),
    }

    # 4. Heavyweight orm / generic dep creep
    heavy_v2 = {"sqlalchemy", "alembic", "pydantic"} & new_external
    drift_heavy_dep = (not p1.get("any_external_dep", False)) and bool(heavy_v2)
    drifts["heavyweight_dep_creep"] = {
        "drift": drift_heavy_dep,
        "p1_stdlib_only": not p1.get("any_external_dep", False),
        "heavy_deps_in_p2": sorted(heavy_v2),
    }

    drift_count = sum(1 for d in drifts.values() if d["drift"])
    return drift_count, {
        "drift_count": drift_count,
        "drifts_by_axis": drifts,
        "phase1_snapshot": p1,
        "phase2_snapshot": p2,
    }


# ── CONFIG ────────────────────────────────────────────────────────────────


CONFIG = TaskConfig(
    id="tinytq_2phase",
    short_label="T11",
    source="custom",
    horizon_hint="60-140 steps over 2 sessions",
    # back-compat: single-prompt collapses both phases for runners that don't
    # honour `phases` yet — the agent will see both blocks at once and likely
    # do them in sequence.
    prompt=_PHASE_1_PROMPT + "\n\n---\n\n" + _PHASE_2_PROMPT,
    setup=_setup,
    check=_check,
    phases=(_PHASE_1_PROMPT, _PHASE_2_PROMPT),
    drift_check=_drift_check,
)
