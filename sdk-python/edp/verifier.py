"""Pre-action verifier — checks planned tool calls against active invariants.

Per SPEC.md §3.6 (v0.2 extension): when an agent is about to execute a
non-trivial action, the verifier reads the action description and the
list of active decisions' invariants, and returns one of three verdicts:

  - "compatible": no active invariant is violated; proceed
  - "violated": at least one invariant is violated; do not execute
  - "uncertain": more evidence needed; escalate to user or supersede

Mechanism: the verifier calls a cheap model (default Haiku 4.5) with
structured tool_use, returning a `CompatibilityReport`. Per the source
`decision-framework-reliability.md` §3 cost-benefit table, this lands at
"Eng cost: 1wk, Run cost: +5%, Gain: -25% silent failures" — the
intervention earns its place specifically for the decision-drift
failure mode that EDP targets.

This module is OPTIONAL: it is imported lazily so the core SDK does not
require the `anthropic` dependency. To use:

    pip install "explicit-decision-protocol[verifier]"
    export ANTHROPIC_API_KEY=sk-ant-...

Then in code:

    from edp.verifier import verify
    report = verify(
        planned_action="add /reports endpoint with XML response",
        active_decisions=store.list_active(),
    )
    if report.verdict == "violated":
        print(f"BLOCKED: {report.reasoning}")
        for dec_id in report.violated_decision_ids:
            print(f"  cite: {dec_id}")
"""

from __future__ import annotations

import json
import os
from typing import Optional

from edp.models import CompatibilityReport, Decision

# Default to Haiku 4.5 per the source-doc's cost-benefit ("verifier should
# be cheap; Haiku-class is the right tier"). Operators MAY override via
# the EDP_VERIFIER_MODEL env var.
DEFAULT_MODEL = "claude-haiku-4-5-20251001"


VERIFIER_TOOL_SCHEMA = {
    "name": "report_compatibility",
    "description": (
        "Report whether the planned action is compatible with the active "
        "EDP decisions and their invariants. You MUST call this tool exactly "
        "once with your verdict."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {
                "type": "string",
                "enum": ["compatible", "violated", "uncertain"],
                "description": (
                    "'compatible' = no active invariant is violated by the "
                    "planned action. 'violated' = at least one invariant is "
                    "violated; the action MUST NOT be executed. 'uncertain' "
                    "= you need more evidence (action ambiguous, invariants "
                    "ambiguous, or relevant invariant references state you "
                    "cannot inspect)."
                ),
            },
            "reasoning": {
                "type": "string",
                "description": (
                    "One short paragraph (≤300 chars) explaining the verdict. "
                    "For 'violated': quote the violated invariant verbatim "
                    "and name how the action contradicts it. For 'compatible': "
                    "name the invariants you checked. For 'uncertain': name "
                    "the specific evidence gap."
                ),
            },
            "violated_decision_ids": {
                "type": "array",
                "items": {"type": "string", "pattern": r"^DEC-\d{4,}$"},
                "description": (
                    "DEC-NNNN ids whose invariants are violated. REQUIRED "
                    "if verdict == 'violated'. Empty list otherwise."
                ),
            },
        },
        "required": ["verdict", "reasoning", "violated_decision_ids"],
    },
}


SYSTEM_PROMPT = """You are an EDP verifier. Your job: given a planned agent action and a list of active architectural decisions, determine whether the action violates any decision's invariants.

You are NOT the agent. You do not propose alternatives or suggest workarounds. You only verify.

Rules:
1. An invariant is violated only if the planned action would directly contradict it. Tangential overlap is NOT a violation.
2. If an invariant is ambiguous or the action is too vague to evaluate, return 'uncertain' — do not guess.
3. If multiple decisions overlap, list ALL violated decision ids.
4. Be strict but precise. False positives ('violated' when compatible) erode trust as much as false negatives.
5. You MUST call the report_compatibility tool exactly once. Do not respond in plain text."""


def _format_decisions_for_verifier(decisions: list[Decision]) -> str:
    """Render active decisions in a compact form the verifier model can scan."""
    if not decisions:
        return "(no active decisions — vacuously compatible)"
    lines = []
    for d in decisions:
        # Prefer invariants (v0.2 field) if present; fall back to key_constraints.
        # Both are listed so the verifier sees the full constraint surface.
        lines.append(f"{d.id} [{d.status}] {d.title}")
        if d.invariants:
            for inv in d.invariants:
                lines.append(f"  INV: {inv}")
        for kc in d.key_constraints:
            lines.append(f"  CON: {kc}")
        if d.revision_conditions:
            # Surface revision_conditions too — an action that triggers a
            # revision_condition is "uncertain" not "violated".
            for rc in d.revision_conditions:
                lines.append(f"  TRIGGER (revise-if): {rc}")
    return "\n".join(lines)


class VerifierUnavailable(RuntimeError):
    """Raised when the verifier cannot run (missing `anthropic` extra, no API key, etc)."""


def verify(
    planned_action: str,
    active_decisions: list[Decision],
    *,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    max_tokens: int = 512,
) -> CompatibilityReport:
    """Verify a planned action against active decisions; return a CompatibilityReport.

    Raises VerifierUnavailable if the `anthropic` SDK is not installed
    or if no API key is configured. The CALLER decides whether to fail-
    closed (block the action) or fail-open (let the action proceed with
    a warning) when the verifier is unavailable — EDP itself does not
    take a position. The opt-in PreToolUse hook in the Claude Code
    adapter fails OPEN by default (the agent's session is never broken
    by missing verifier infrastructure); explicit `--verifier-required`
    flag flips this to fail CLOSED.
    """
    try:
        import anthropic  # type: ignore[import-not-found]
    except ImportError as e:
        raise VerifierUnavailable(
            "anthropic SDK not installed. Install with: "
            "pip install 'explicit-decision-protocol[verifier]'"
        ) from e

    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise VerifierUnavailable(
            "ANTHROPIC_API_KEY not set. Export the key or pass api_key= to verify()."
        )

    model_id = model or os.environ.get("EDP_VERIFIER_MODEL") or DEFAULT_MODEL

    client = anthropic.Anthropic(api_key=key)

    user_message = (
        f"Planned action:\n{planned_action}\n\n"
        f"Active decisions:\n{_format_decisions_for_verifier(active_decisions)}"
    )

    response = client.messages.create(
        model=model_id,
        max_tokens=max_tokens,
        system=SYSTEM_PROMPT,
        tools=[VERIFIER_TOOL_SCHEMA],
        tool_choice={"type": "tool", "name": "report_compatibility"},
        messages=[{"role": "user", "content": user_message}],
    )

    # The tool_choice forces the model to call report_compatibility; extract args.
    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "report_compatibility":
            return CompatibilityReport(**block.input)

    # Defensive: if the model somehow didn't call the tool, return uncertain
    # rather than crashing. This MUST be rare given tool_choice="tool".
    return CompatibilityReport(
        verdict="uncertain",
        reasoning=(
            "verifier model did not call the report_compatibility tool; "
            "raw response: " + json.dumps([b.model_dump() for b in response.content])[:200]
        ),
        violated_decision_ids=[],
    )
