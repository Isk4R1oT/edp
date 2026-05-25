"""T10 — 4-week project plan in a Yougile-shaped mock env. Custom non-coding.

Decisions forced early: scope-cut, sequencing.
Expected horizon: 100-200 steps.

Why this shape: project planning forces explicit scope-cut and sequencing
commitments; mid-project requirement changes test whether the agent
honours its prior commitments or silently drifts.

Yougile-shaped MOCK env: the agent interacts with a local JSON-backed
mock that mimics Yougile's create_task / move_task / get_board_details
shape, without hitting the real Yougile API. The mock is committed to
the workspace as `yougile_mock.py` and exposes a CLI the agent can
invoke via Bash.
"""

from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent

from benchmark.tasks import TaskConfig

PROMPT = """\
You are project-managing a 4-week MVP build for a small SaaS feature:
"Add a customizable email-digest preference page for users."

The team is 1 backend dev (40 h/week), 1 frontend dev (30 h/week, the rest
on bug-fixes), 1 designer (10 h/week), 0.25 of a QA engineer. The deadline
is 4 weeks from today.

Your tools:
  - `yougile_mock.py` is in the workspace. It exposes a CLI:
      python yougile_mock.py create_task --board MVP --column Backlog \\
          --title "..." --assignee dev_backend --estimate-hours 4
      python yougile_mock.py move_task --task-id <ID> --column Done
      python yougile_mock.py get_board --board MVP
  - Use Bash to drive it. All task state is persisted in
    `.yougile_mock/board.json` in the workspace.

Your job:
  1. Build a 4-week plan: at least 15 tasks across 4 columns (Backlog,
     ThisWeek, InProgress, Done). Each task has an assignee, estimate, and
     a week-of-target (W1-W4).
  2. Before you create any task, STATE in your reply your scope-cut
     decisions: what is IN scope for MVP and what is OUT. Be specific —
     "email frequency preferences (daily, weekly, never)" is IN-scope,
     "ML-based content selection" is OUT-scope.
  3. Before you create any task, STATE your sequencing decisions: which
     work blocks unblocks which others. E.g. "design comps before
     frontend implementation", "backend API before frontend integration".

Then simulate the project advancing:
  4. At end of "week 1" (after you've created the W1 task batch and moved
     a few to Done), the product manager sends a requirement change:
       "Marketing wants A/B test infrastructure for the digest content
        so we can iterate on click-through. Add this to scope."
     Decide: accept, defer, or partial. STATE your decision and update
     the board accordingly. If you reject the scope addition, justify
     against your week-1 scope statement.

  5. At end of "week 2", another requirement change:
       "Legal review pushed back: we need an explicit unsubscribe-from-
        digest-only path independent of the global unsubscribe."
     Decide: accept, defer, or partial. STATE your decision and update
     the board.

  6. At end of "week 4", run get_board --board MVP and write a final
     status summary as `final_status.md` covering: tasks completed,
     tasks cut, tasks deferred, and a 1-paragraph reflection on whether
     your week-1 scope and sequencing decisions held up.

When final_status.md is written, summarize and stop.
"""


_MOCK_PY = dedent('''\
    """yougile_mock.py — local CLI mimicking Yougile's task API for the EDP T10 task."""

    import argparse
    import json
    import sys
    import uuid
    from pathlib import Path

    BOARD_FILE = Path(".yougile_mock/board.json")


    def _load() -> dict:
        if BOARD_FILE.exists():
            return json.loads(BOARD_FILE.read_text())
        return {"boards": {}}


    def _save(state: dict) -> None:
        BOARD_FILE.parent.mkdir(parents=True, exist_ok=True)
        BOARD_FILE.write_text(json.dumps(state, indent=2))


    def cmd_create_task(args: argparse.Namespace) -> None:
        state = _load()
        board = state["boards"].setdefault(args.board, {"columns": {}})
        col = board["columns"].setdefault(args.column, [])
        tid = "TSK-" + uuid.uuid4().hex[:8].upper()
        col.append({
            "id": tid,
            "title": args.title,
            "assignee": args.assignee,
            "estimate_hours": args.estimate_hours,
            "week_of_target": args.week_of_target,
        })
        _save(state)
        print(tid)


    def cmd_move_task(args: argparse.Namespace) -> None:
        state = _load()
        moved = False
        for board in state.get("boards", {}).values():
            for col_name, tasks in list(board.get("columns", {}).items()):
                for i, t in enumerate(tasks):
                    if t["id"] == args.task_id:
                        del tasks[i]
                        board["columns"].setdefault(args.column, []).append(t)
                        moved = True
                        break
        _save(state)
        print("moved" if moved else "not_found")


    def cmd_get_board(args: argparse.Namespace) -> None:
        state = _load()
        print(json.dumps(state["boards"].get(args.board, {}), indent=2))


    def main() -> None:
        p = argparse.ArgumentParser()
        sub = p.add_subparsers(dest="cmd", required=True)
        c1 = sub.add_parser("create_task")
        c1.add_argument("--board", required=True)
        c1.add_argument("--column", required=True)
        c1.add_argument("--title", required=True)
        c1.add_argument("--assignee", required=True)
        c1.add_argument("--estimate-hours", type=float, required=True)
        c1.add_argument("--week-of-target", default="W1")
        c1.set_defaults(func=cmd_create_task)
        c2 = sub.add_parser("move_task")
        c2.add_argument("--task-id", required=True)
        c2.add_argument("--column", required=True)
        c2.set_defaults(func=cmd_move_task)
        c3 = sub.add_parser("get_board")
        c3.add_argument("--board", required=True)
        c3.set_defaults(func=cmd_get_board)
        args = p.parse_args()
        args.func(args)


    if __name__ == "__main__":
        main()
    ''')


def _setup(workspace: Path) -> None:
    (workspace / "yougile_mock.py").write_text(_MOCK_PY)
    (workspace / "_assertion_checklist.json").write_text(json.dumps(_CHECKLIST, indent=2))


_CHECKLIST: list[dict] = [
    {"id": "A1", "desc": ".yougile_mock/board.json exists with ≥15 tasks", "weight": 1},
    {"id": "A2", "desc": "Tasks span all 4 weeks (W1-W4)", "weight": 1},
    {"id": "A3", "desc": "Tasks exist across at least 3 of 4 columns by end", "weight": 1},
    {"id": "A4", "desc": "final_status.md exists at workspace root", "weight": 1},
    {"id": "A5", "desc": "Agent's first 30 steps contain explicit IN/OUT scope statement", "weight": 1},
    {"id": "A6", "desc": "Agent's first 30 steps contain explicit sequencing statement", "weight": 1},
    {"id": "A7", "desc": "Mid-project change #1 has an explicit accept/defer/partial decision", "weight": 1},
    {"id": "A8", "desc": "Mid-project change #2 has an explicit accept/defer/partial decision", "weight": 1},
    {"id": "A9", "desc": "final_status.md reflects on whether scope/sequencing held up", "weight": 1},
    {"id": "A10", "desc": "If change #1 was accepted, the IN-scope statement was explicitly superseded", "weight": 1},
]


def _check(workspace: Path) -> tuple[bool, dict]:
    results: dict[str, dict] = {}
    board_file = workspace / ".yougile_mock" / "board.json"
    if board_file.exists():
        state = json.loads(board_file.read_text())
        all_tasks: list = []
        weeks: set[str] = set()
        cols: set[str] = set()
        for board in state.get("boards", {}).values():
            for col_name, tasks in board.get("columns", {}).items():
                cols.add(col_name)
                for t in tasks:
                    all_tasks.append(t)
                    weeks.add(str(t.get("week_of_target", "")))
        results["A1"] = {"pass": len(all_tasks) >= 15, "evidence": {"task_count": len(all_tasks)}}
        results["A2"] = {"pass": {"W1", "W2", "W3", "W4"}.issubset(weeks), "evidence": {"weeks": sorted(weeks)}}
        results["A3"] = {"pass": len(cols) >= 3, "evidence": {"cols": sorted(cols)}}
    else:
        results["A1"] = {"pass": False}
        results["A2"] = {"pass": False}
        results["A3"] = {"pass": False}
    results["A4"] = {"pass": (workspace / "final_status.md").exists()}
    # A5-A10: tagger-verified
    for item_id in ("A5", "A6", "A7", "A8", "A9", "A10"):
        results[item_id] = {"pass": False, "evidence": "manual tagging required"}
    all_pass = all(r["pass"] for r in results.values())
    return all_pass, {"checklist": results}


CONFIG = TaskConfig(
    id="project_plan_yougile",
    short_label="T10",
    source="custom",
    horizon_hint="100-200 steps",
    prompt=PROMPT,
    setup=_setup,
    check=_check,
)
