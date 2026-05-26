"""Claude Code PreToolUse hook — pre-action verifier per spec §3.6 (v0.2).

Reads a PreToolUse JSON envelope from stdin (Claude Code hook protocol),
extracts the planned tool call, runs the EDP verifier against active
decisions' invariants, and emits a hookSpecificOutput JSON that either
allows the tool call (compatible / uncertain) or blocks it (violated).

This is the gating mechanism the source `decision-protocol-template.md`
calls out as load-bearing: *verifier-agent проверяет каждое action
ПЕРЕД исполнением*. Without it, EDP is visibility-only; with it, EDP
is visibility + enforcement at the tool-call gate.

## Fail-open vs fail-closed

By default the hook is **fail-open**: if the verifier is unavailable
(no `anthropic` extra installed, no API key, network error), the hook
returns an allow decision with a `systemMessage` warning. Rationale:
the user's session must never be broken by missing verifier
infrastructure. Set `EDP_VERIFIER_REQUIRED=1` in the hook's env to flip
to fail-closed (block the call when verifier is unavailable).

## Matcher

The hook should be installed on Claude Code's `PreToolUse` event with
a matcher that targets only WRITE-class tools by default
(Edit|Write|Bash|str_replace_editor). Verifying every Read/Glob/Grep
call burns verifier cost without benefit — these tools cannot violate
an architectural decision. Per the source `decision-framework-
reliability.md` §7: *Cheap checks везде, expensive в Pareto 20% high-
risk actions.*

## Output protocol

Per Claude Code hooks spec, PreToolUse hooks emit:

  {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                          "permissionDecision": "allow" | "deny",
                          "permissionDecisionReason": "..."}}

Invocation: `python -m edp.verifier_hook` (no args). The hook reads
stdin per Claude Code's hook protocol and emits to stdout.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

from edp.hook import find_edp_root
from edp.store import DecisionStore


def _summarise_tool_call(tool_name: str, tool_input: dict) -> str:
    """Render the planned tool call as a one-line description the verifier can consume.

    The verifier needs human-readable text, not raw JSON. Specialise per
    tool name where useful; fall back to a compact JSON render.
    """
    if tool_name in ("Edit", "Write", "str_replace_editor"):
        path = tool_input.get("file_path") or tool_input.get("path") or "<unknown>"
        return f"Modify file {path}"
    if tool_name == "Bash":
        cmd = tool_input.get("command") or "<unknown>"
        return f"Run shell command: {cmd[:300]}"
    if tool_name == "Grep":
        return f"Search for pattern: {tool_input.get('pattern', '<unknown>')}"
    # Default: include the tool name + JSON of inputs, truncated.
    return f"{tool_name}({json.dumps(tool_input, ensure_ascii=False)[:300]})"


def _decide(payload: dict, edp_dir: Path) -> dict:
    """Run the verifier and translate its CompatibilityReport into a Claude Code hook decision."""
    tool_name = payload.get("tool_name") or payload.get("toolName") or "<unknown>"
    tool_input = payload.get("tool_input") or payload.get("toolInput") or {}

    planned = _summarise_tool_call(tool_name, tool_input)

    store = DecisionStore.open(edp_dir)
    active = store.list_active()
    constraints = store.list_constraints(include_provisional=False)

    # Verify when at least one active decision carries invariants OR there
    # is at least one confirmed constraint. If neither exists the verifier
    # has nothing to check; skip the call to save cost and latency.
    if not any(d.invariants for d in active) and not constraints:
        return _allow("no active invariants or constraints to check")

    from edp.verifier import VerifierUnavailable, verify

    required = os.environ.get("EDP_VERIFIER_REQUIRED") == "1"
    try:
        report = verify(planned, active, active_constraints=constraints)
    except VerifierUnavailable as e:
        if required:
            return _deny(
                f"EDP verifier unavailable and EDP_VERIFIER_REQUIRED=1 — "
                f"blocking tool call. Cause: {e}"
            )
        return _allow(f"verifier unavailable (fail-open): {e}")

    if report.verdict == "violated":
        cited = ", ".join(report.violated_decision_ids) or "(unspecified)"
        has_constraint = any(
            i.startswith("CON-") for i in report.violated_decision_ids
        )
        if has_constraint:
            reason = (
                f"EDP verifier blocked this action: {report.reasoning} "
                f"Violates: {cited}. Constraints (CON-*) are non-negotiable "
                f"axioms — they cannot be superseded by the agent. Revise the "
                f"plan to comply, or escalate to the operator if the constraint "
                f"is wrong."
            )
        else:
            reason = (
                f"EDP verifier blocked this action: {report.reasoning} "
                f"Violates: {cited}. To proceed, either revise the plan to comply "
                f"with the active decision(s), or call mcp__edp__edp_supersede if "
                f"the decision should change."
            )
        return _deny(reason)

    if report.verdict == "uncertain":
        # Allow but surface the uncertainty so the agent can self-consult.
        return _allow(f"verifier uncertain: {report.reasoning}")

    return _allow("verifier compatible")


def _allow(reason: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "permissionDecisionReason": reason,
        }
    }


def _deny(reason: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def main() -> int:
    # Read PreToolUse payload from stdin
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        # Malformed stdin — fail open silently so the user's session is not
        # disrupted by a hook protocol mismatch.
        return 0

    # Locate the EDP store. EDP_STORE env override → walk up from cwd.
    env_store = os.environ.get("EDP_STORE")
    if env_store:
        edp_dir: Optional[Path] = Path(env_store)
        if not edp_dir.is_dir():
            return 0  # no store — no verification possible, silent passthrough
    else:
        root = find_edp_root(Path.cwd())
        if root is None:
            return 0
        edp_dir = root / ".edp"

    try:
        decision = _decide(payload, edp_dir)
    except Exception as e:  # noqa: BLE001
        # Last-resort fail-safe: never break the user's session because of
        # an internal verifier bug. Emit a systemMessage warning if possible.
        decision = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "permissionDecisionReason": f"EDP verifier hook error (fail-open): {e}",
            }
        }

    sys.stdout.write(json.dumps(decision))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
